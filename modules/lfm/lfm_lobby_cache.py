# -*- coding: utf-8 -*-
"""
modules/lfm/lfm_lobby_cache.py

LFM lobi katılımcılarını yarış ÖNCESİ çekip data/lfm_cache/lobby_<id>.json
olarak saklar. Yarış sırasında yalnızca read_lobby_cache() kullanılır
(ağ çağrısı YOK).

Yapı (ağ / hesaplama / cache ayrı):
  1) fetch_lobby()            -> ağ çağrısı (yalnızca yarış öncesi)
  2) normalize_participants() -> SAF: ağ/disk/saat kullanmaz
  3) write_lobby_cache() / read_lobby_cache() -> atomik yazma, tek okuma noktası

UYARI: Lobi uç noktası ve alan adları DOĞRULANMAMIŞTIR. Aday isimler
settings.json -> lfm.field_map içinde "lobby_" önekiyle tutulur.
"""

import argparse
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# lfm_track_history.py içindeki ortak yardımcılar yeniden kullanılıyor
from modules.lfm.lfm_track_history import (
    LOGGER, PROJE_KOK, ayar_yukle, log_kur, read_cache, sec,
    simdi_utc_iso, write_cache,
)

# settings.json'da yoksa kullanılacak lobi alan adayları
LOBBY_ALANLARI = {
    "lobby_steamid": ["steamid", "steam_id", "steamId"],
    "lobby_name": ["name", "username", "driver_name", "drivername"],
    "lobby_elo": ["elo", "rating"],
    "lobby_safetyrating": ["safetyrating", "safety_rating", "sr"],
    "lobby_license": ["license", "licence"],
    "lobby_carclass": ["carclass", "car_class", "class"],
    "lobby_carmodel": ["carmodel", "car_model", "car"],
    "lobby_split": ["split"],
    "lobby_rows_keys": ["participants", "drivers", "entries", "results", "users", "data"],
}

VARSAYILAN_LOBI_AYAR = {
    "lobby_url_template": "",          # örn. https://.../lobby/{lobby_id}
    "lobby_cache_dir": "data/lfm_cache",
    "lobby_token_env": "LFM_API_TOKEN",  # .env içindeki değişken adı
}

# (alan, tip): m = metin, s = sayı. Çıktı sırası da budur.
CIKTI_ALANLARI = [("name", "m"), ("elo", "s"), ("safetyrating", "s"),
                  ("license", "m"), ("carclass", "m"), ("carmodel", "m"),
                  ("split", "m")]


# ---------------------------------------------------------------- ayar / doğrulama
def lobby_ayar_yukle():
    """Mevcut ayarları okur, eksik lobi anahtarlarını varsayılanla tamamlar."""
    ayar = ayar_yukle()
    for k, v in VARSAYILAN_LOBI_AYAR.items():
        ayar.setdefault(k, v)
    for k, v in LOBBY_ALANLARI.items():
        ayar["field_map"].setdefault(k, v)
    return ayar


def lobby_id_dogrula(lobby_id):
    """SAF. (geçerli_mi, hata_mesajı) döner. Kural: [A-Za-z0-9_-], 1-64 karakter."""
    if not isinstance(lobby_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", lobby_id):
        return False, ("Geçersiz lobi kimliği: yalnızca harf, rakam, '-' ve '_' "
                       "kullanılabilir ve uzunluk 1-64 karakter olmalıdır.")
    return True, ""


def sayi_cevir(deger):
    """SAF. Sayıya çevirir; çevrilemezse None. Tam sayı ise int döner."""
    try:
        if deger is None or isinstance(deger, bool):
            return None
        v = float(deger.replace(",", ".")) if isinstance(deger, str) else float(deger)
        if not math.isfinite(v):
            return None
        return int(v) if v.is_integer() else v
    except (ValueError, TypeError, AttributeError):
        return None


def aday(fm, ad):
    """field_map'te 'lobby_<ad>' yoksa yerleşik adayları kullanır."""
    return fm.get("lobby_" + ad) or LOBBY_ALANLARI["lobby_" + ad]


# ---------------------------------------------------------------- 1) AĞ
def token_oku(ayar):
    """Token'ı .env'den okur (koda sabit yazılmaz). Yoksa None + uyarı."""
    if load_dotenv is None:
        LOGGER.warning("python-dotenv kurulu değil, .env okunamadı.")
    else:
        env_yolu = PROJE_KOK / ".env"
        if env_yolu.is_file():
            load_dotenv(env_yolu)
        else:
            LOGGER.warning(".env dosyası bulunamadı, token olmadan denenecek.")
    token = os.environ.get(ayar["lobby_token_env"]) or None
    if token is None:
        LOGGER.warning("Token bulunamadı (%s), istek token'sız yapılacak.",
                       ayar["lobby_token_env"])
    return token


def fetch_lobby(lobby_id, ayar):
    """Lobi JSON'unu çeker. Başarısızsa None. SADECE yarış öncesi."""
    ok, mesaj = lobby_id_dogrula(lobby_id)
    if not ok:
        LOGGER.error(mesaj)
        return None
    sablon = ayar.get("lobby_url_template", "")
    if not sablon or "{lobby_id}" not in sablon:
        LOGGER.warning("settings.json'da lobby_url_template boş veya {lobby_id} içermiyor.")
        return None
    if requests is None:
        LOGGER.warning("requests kurulu değil, lobi çekilemedi.")
        return None
    url = sablon.replace("{lobby_id}", lobby_id)
    token = token_oku(ayar)
    basliklar = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.get(url, headers=basliklar, timeout=ayar.get("request_timeout", 15))
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        LOGGER.warning("Lobi çekilemedi (%s): %s", url, e)
        return None


# ---------------------------------------------------------------- 2) NORMALİZE (SAF)
def satirlari_cikar_lobi(ham, fm):
    """SAF. Ham JSON'dan katılımcı satırlarını (dict listesi) çıkarır."""
    if isinstance(ham, list):
        return [x for x in ham if isinstance(x, dict)]
    if isinstance(ham, dict):
        for k in aday(fm, "rows_keys"):
            if isinstance(ham.get(k), list):
                return [x for x in ham[k] if isinstance(x, dict)]
    return []


def normalize_participants(ham, fm):
    """
    SAF: ağ/disk/saat kullanmaz, log yazmaz. (sürücü_listesi, uyarılar) döner.
    Aynı steamid iki kez gelirse SON kayıt geçerlidir.
    elo/safetyrating çevrilemezse None olur, sürücü listede KALIR.
    """
    uyarilar = []
    satirlar = satirlari_cikar_lobi(ham, fm)
    if not satirlar:
        return [], ["Lobi verisinde katılımcı satırı bulunamadı."]
    sonuc = {}
    for i, s in enumerate(satirlar):
        try:
            sid_ham = sec(s, aday(fm, "steamid"))
            sid = str(sid_ham).strip() if sid_ham is not None else ""
            if not sid:
                uyarilar.append(f"Satır {i} atlandı: steamid yok.")
                continue
            kayit = {"steamid": sid}
            for alan, tip in CIKTI_ALANLARI:
                ham_d = sec(s, aday(fm, alan))
                if ham_d is None:
                    uyarilar.append(f"Sürücü {sid}: '{alan}' alanı eksik.")
                    kayit[alan] = None
                elif tip == "s":
                    v = sayi_cevir(ham_d)
                    if v is None:
                        uyarilar.append(f"Sürücü {sid}: '{alan}' sayıya çevrilemedi.")
                    kayit[alan] = v
                else:
                    m = str(ham_d).strip()
                    kayit[alan] = m if m else None
            if sid in sonuc:
                uyarilar.append(f"Sürücü {sid} lobide birden fazla kez geldi, "
                                "son kayıt geçerli sayıldı.")
            sonuc[sid] = kayit
        except Exception as e:  # savunmacı: tek satır tüm işlemi çökertmesin
            uyarilar.append(f"Satır {i} atlandı: beklenmeyen hata: {e}")
    return list(sonuc.values()), uyarilar


def lobi_veri_olustur(lobby_id, suruculer, olusturma_zamani):
    """SAF. Cache'e yazılacak sözlüğü kurar."""
    return {"lobby_id": lobby_id, "generated_at": olusturma_zamani,
            "driver_count": len(suruculer), "drivers": suruculer}


# ---------------------------------------------------------------- 3) CACHE
def cache_yolu(lobby_id, ayar):
    return PROJE_KOK / ayar["lobby_cache_dir"] / f"lobby_{lobby_id}.json"


def write_lobby_cache(lobby_id, veri, ayar=None):
    """Atomik yazar (.tmp sonra replace). Geçersiz id'de ValueError, dosya yazmaz."""
    ok, mesaj = lobby_id_dogrula(lobby_id)
    if not ok:
        raise ValueError(mesaj)
    ayar = ayar or lobby_ayar_yukle()
    yol = cache_yolu(lobby_id, ayar)
    write_cache(yol, veri)
    return yol


def read_lobby_cache(lobby_id, ayar=None):
    """Yarış sırasında TEK okuma noktası: yalnızca diskten okur. Sorunda None."""
    ok, mesaj = lobby_id_dogrula(lobby_id)
    if not ok:
        LOGGER.error(mesaj)
        return None
    ayar = ayar or lobby_ayar_yukle()
    veri = read_cache(cache_yolu(lobby_id, ayar))
    if not isinstance(veri, dict) or not isinstance(veri.get("drivers"), list):
        if veri is not None:
            LOGGER.warning("Lobi cache biçimi geçersiz: lobby_%s", lobby_id)
        return None
    return veri


# ---------------------------------------------------------------- KOMUTLAR
def uyarilari_logla(uyarilar, limit=10):
    """Log şişmesin: ilk 'limit' uyarıyı yaz, kalanını say."""
    for u in uyarilar[:limit]:
        LOGGER.warning(u)
    if len(uyarilar) > limit:
        LOGGER.warning("... ve %d uyarı daha.", len(uyarilar) - limit)


def komut_fetch(ayar, lobby_id):
    ok, mesaj = lobby_id_dogrula(lobby_id)
    if not ok:
        print(f"[HATA] {mesaj}")
        return 1
    ham = fetch_lobby(lobby_id, ayar)
    if ham is None:
        print("[HATA] Lobi verisi çekilemedi. Ayrıntı: logs/lfm.log")
        return 1
    suruculer, uyarilar = normalize_participants(ham, ayar["field_map"])
    uyarilari_logla(uyarilar)
    if not suruculer:
        print("[HATA] Katılımcı bulunamadı; mevcut cache korundu (üzerine yazılmadı).")
        return 1
    yol = write_lobby_cache(lobby_id, lobi_veri_olustur(lobby_id, suruculer, simdi_utc_iso()), ayar)
    LOGGER.info("Lobi cache yazıldı: %s (%d sürücü, %d uyarı)", yol, len(suruculer), len(uyarilar))
    print(f"Tamam: {yol} ({len(suruculer)} sürücü, {len(uyarilar)} uyarı)")
    return 0


def komut_show(ayar, lobby_id):
    veri = read_lobby_cache(lobby_id, ayar)
    if veri is None:
        print("Cache yok veya okunamadı. Önce --fetch çalıştırın (ayrıntı: logs/lfm.log).")
        return 1
    print(f"Lobi {veri.get('lobby_id')} | {veri.get('generated_at')} | "
          f"{veri.get('driver_count')} sürücü")
    for d in veri["drivers"]:
        print(f"  {d.get('steamid')} | {d.get('name')} | elo={d.get('elo')} | "
              f"sr={d.get('safetyrating')} | {d.get('carmodel')} | split={d.get('split')}")
    return 0


def komut_selftest(ayar):
    """Sahte 3 sürücülü lobi: normalize + cache gidiş-dönüş testi (ağ yok)."""
    fm = ayar["field_map"]
    ham = {"participants": [
        {"steamid": "76561190000000001", "name": "Ali", "elo": 2400, "safetyrating": 3.5,
         "license": "Gold", "carclass": "GT3", "carmodel": "ferrari_296_gt3", "split": 1},
        {"steamid": 76561190000000002, "name": "Veli", "elo": "2500", "safetyrating": "4,1",
         "license": "Gold", "carclass": "GT3", "carmodel": "bmw_m4_gt3", "split": 1},
        {"steamid": "76561190000000003", "name": "Can", "elo": "abc", "safetyrating": 2.0,
         "license": "Silver", "carclass": "GT3", "carmodel": "audi_r8_lms_evo_ii", "split": 2},
        # yinelenen sürücü: SON kayıt geçerli olmalı
        {"steamid": "76561190000000001", "name": "Ali", "elo": 2600, "safetyrating": 3.6,
         "license": "Gold", "carclass": "GT3", "carmodel": "ferrari_296_gt3", "split": 1},
    ]}
    drv, uy = normalize_participants(ham, fm)
    assert len(drv) == 3, drv
    por = {d["steamid"]: d for d in drv}
    assert por["76561190000000001"]["elo"] == 2600, "son kayıt geçerli olmalı"
    assert por["76561190000000002"]["steamid"] == "76561190000000002"  # int -> metin
    assert por["76561190000000002"]["elo"] == 2500 and por["76561190000000002"]["safetyrating"] == 4.1
    assert por["76561190000000003"]["elo"] is None, "çevrilemeyen elo None olmalı"
    assert any("birden fazla" in u for u in uy) and any("sayıya çevrilemedi" in u for u in uy)
    assert (drv, uy) == normalize_participants(ham, fm), "SAF olmalı"

    with tempfile.TemporaryDirectory() as t:
        a = dict(ayar, lobby_cache_dir=t)  # gerçek cache'e dokunma
        veri = lobi_veri_olustur("test-1_X", drv, "2026-11-02T10:00:00Z")
        yol = write_lobby_cache("test-1_X", veri, a)
        assert yol.name == "lobby_test-1_X.json" and yol.is_file()
        assert read_lobby_cache("test-1_X", a) == veri, "yaz -> oku aynı olmalı"
        assert not list(Path(t).glob("*.tmp")), ".tmp dosyası kalmamalı"
        # lobby_id doğrulaması
        for kotu in ["", "../x", "a b", "a" * 65, "x.json", None]:
            assert lobby_id_dogrula(kotu)[0] is False, kotu
            try:
                write_lobby_cache(kotu, veri, a)
                raise AssertionError("geçersiz id kabul edildi")
            except ValueError:
                pass
        for iyi in ["abc-1_X", "a" * 64, "7"]:
            assert lobby_id_dogrula(iyi)[0] is True, iyi
        assert [p.name for p in Path(t).iterdir()] == ["lobby_test-1_X.json"], "fazladan dosya yazılmış"
    print("SELFTEST TAMAM: tüm kontroller geçti.")
    return 0


def komut_badtest(ayar):
    """Boş/bozuk/eksik alanlı veriyle çökmediğini doğrular."""
    fm = ayar["field_map"]
    for kotu in [None, "", "{bad", 5, [], {}, [1, "a", None],
                 {"participants": [{"foo": 1}]}, {"participants": "x"}]:
        drv, uy = normalize_participants(kotu, fm)
        assert drv == [] and uy, (kotu, drv, uy)
    # yalnızca steamid olan satır: sürücü KALMALI, alanlar None
    drv, uy = normalize_participants({"participants": [{"steamid": "1"}]}, fm)
    assert len(drv) == 1 and drv[0]["elo"] is None and len(uy) >= 7, (drv, uy)
    with tempfile.TemporaryDirectory() as t:
        a = dict(ayar, lobby_cache_dir=t)
        (Path(t) / "lobby_bozuk.json").write_text("{not json", encoding="utf-8")
        (Path(t) / "lobby_liste.json").write_text("[]", encoding="utf-8")
        assert read_lobby_cache("bozuk", a) is None
        assert read_lobby_cache("liste", a) is None
        assert read_lobby_cache("yok", a) is None
        assert read_lobby_cache("../x", a) is None
        b = dict(a, lobby_url_template="")  # ağa çıkmadan None dönmeli
        assert fetch_lobby("abc", b) is None
        assert fetch_lobby("../x", b) is None
    print("BADTEST TAMAM: bozuk veri çökmedi, uyarılar logs/lfm.log içinde.")
    return 0


def main():
    p = argparse.ArgumentParser(description="LFM lobi katılımcıları cache")
    p.add_argument("--fetch", metavar="LOBBY_ID", help="lobiyi çek ve cache'e yaz")
    p.add_argument("--show", metavar="LOBBY_ID", help="cache'teki lobiyi göster")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--badtest", action="store_true")
    a = p.parse_args()
    ayar = lobby_ayar_yukle()
    log_kur(ayar["log_path"])
    if a.selftest:
        return komut_selftest(ayar)
    if a.badtest:
        return komut_badtest(ayar)
    if a.fetch:
        return komut_fetch(ayar, a.fetch)
    if a.show:
        return komut_show(ayar, a.show)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
