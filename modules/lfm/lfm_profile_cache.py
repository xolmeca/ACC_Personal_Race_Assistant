# -*- coding: utf-8 -*-
"""
modules/lfm/lfm_profile_cache.py

LFM sürücü profillerini yarış ÖNCESİ çekip data/lfm_cache/profiles.json içinde
tek dosyada toplar: {"generated_at": ..., "profiles": {steamid: {...}}}.
Yarış sırasında yalnızca read_profile_cache() kullanılır (ağ çağrısı YOK).

Yapı (ağ / normalize / birleştirme / cache ayrı):
  1) fetch_profile()          -> ağ çağrısı (yalnızca yarış öncesi)
  2) normalize_profile()      -> SAF: ağ/disk/saat/log yok
  3) merge_profiles()         -> SAF: mevcut profilleri korur, yenisi eskinin yerine geçer
  4) write_profile_cache() / read_profile_cache() / guncelle_cache()

UYARI: Profil uç noktası ve alan adları DOĞRULANMAMIŞTIR. Aday isimler
settings.json -> lfm.field_map içinde "profile_" önekiyle tutulur.
"""

import argparse
import json
import re
import sys
import tempfile
import time
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

# Önceki modüller değiştirilmeden yeniden kullanılıyor
from modules.lfm.lfm_track_history import (
    LOGGER, PROJE_KOK, log_kur, read_cache, sec, simdi_utc_iso, write_cache,
)
from modules.lfm.lfm_lobby_cache import (
    lobby_ayar_yukle, lobby_id_dogrula, read_lobby_cache, sayi_cevir, token_oku,
)

BILGI_ONEKI = "[BİLGİ]"  # normalize mesajlarında bilgi (uyarı olmayan) satırı işareti

# settings.json'da yoksa kullanılacak profil alan adayları
PROFIL_ALANLARI = {
    "profile_lfm_id": ["lfm_id", "lfmid", "userid", "user_id", "id"],
    "profile_steamid": ["steamid", "steam_id", "steamId"],
    "profile_name": ["name", "username", "driver_name", "drivername"],
    "profile_elo": ["elo", "rating"],
    "profile_safetyrating": ["safetyrating", "safety_rating", "sr"],
    "profile_license": ["license", "licence"],
    "profile_carclass": ["carclass", "car_class", "class"],
    "profile_carmodel": ["carmodel", "car_model", "car"],
    "profile_split": ["split"],
    "profile_car_preferences": ["car_preferences", "carpreferences",
                                "favorite_cars", "preferred_cars"],
    # iç içe gelen profil için kök yolları (noktalı yol desteklenir), ilk bulunan kullanılır
    "profile_root_keys": ["data.user", "profile.user", "profile", "user", "data"],
}

VARSAYILAN_PROFIL_AYAR = {
    "profile_url_template": "",            # örn. https://.../profile/{steamid}
    "profile_request_delay_s": 1,          # lobi çekiminde istekler arası bekleme (sn)
    "profile_cache_path": "data/lfm_cache/profiles.json",
}

# (alan, tip): m = metin, s = sayı, l = liste. Çıktı sırası da budur.
CIKTI_ALANLARI = [("name", "m"), ("elo", "s"), ("safetyrating", "s"),
                  ("license", "m"), ("carclass", "m"), ("carmodel", "m"),
                  ("split", "m"), ("car_preferences", "l")]


# ---------------------------------------------------------------- ayar / doğrulama
def profile_ayar_yukle():
    """Lobi ayarlarının üzerine eksik profil anahtarlarını varsayılanla tamamlar."""
    ayar = lobby_ayar_yukle()
    for k, v in VARSAYILAN_PROFIL_AYAR.items():
        ayar.setdefault(k, v)
    for k, v in PROFIL_ALANLARI.items():
        ayar["field_map"].setdefault(k, v)
    return ayar


def steamid_dogrula(sid):
    """SAF. (geçerli_mi, mesaj). Kural: tam 17 haneli rakam. Biçim değişirse TEK yer burası."""
    if isinstance(sid, bool) or not isinstance(sid, (str, int)) \
            or not re.fullmatch(r"\d{17}", str(sid).strip()):
        girilen = repr(sid)[:30]
        return False, (f"Geçersiz Steam ID (girilen: {girilen}): "
                       "tam olarak 17 haneli rakamlardan oluşmalıdır.")
    return True, ""


def bekleme_suresi(deger):
    """SAF. (saniye, uyarı|None). Negatif/geçersiz -> 0 ve uyarı, 0 -> bekleme yok."""
    v = sayi_cevir(deger)
    if v is None:
        return 0, f"profile_request_delay_s geçersiz ({deger!r}), 0 kabul edildi."
    if v < 0:
        return 0, f"profile_request_delay_s negatif ({v}), 0 kabul edildi."
    return v, None


def p_aday(fm, ad):
    """field_map'te 'profile_<ad>' yoksa yerleşik adayları kullanır."""
    return fm.get("profile_" + ad) or PROFIL_ALANLARI["profile_" + ad]


def mesajlari_logla(mesajlar, limit=10):
    """Bilgi satırlarını INFO, diğerlerini WARNING yazar; uyarılar 'limit' ile sınırlı."""
    n = 0
    for m in mesajlar:
        if m.startswith(BILGI_ONEKI):
            LOGGER.info(m[len(BILGI_ONEKI):].strip())
            continue
        n += 1
        if n <= limit:
            LOGGER.warning(m)
    if n > limit:
        LOGGER.warning("... ve %d uyarı daha.", n - limit)


# ---------------------------------------------------------------- 1) AĞ
def fetch_profile(steamid, ayar):
    """Tek sürücü profilini çeker. Başarısızsa None. SADECE yarış öncesi."""
    ok, mesaj = steamid_dogrula(steamid)
    if not ok:
        LOGGER.error(mesaj)
        return None
    sid = str(steamid).strip()
    sablon = ayar.get("profile_url_template", "")
    if not sablon or "{steamid}" not in sablon:
        LOGGER.warning("settings.json'da profile_url_template boş veya {steamid} içermiyor.")
        return None
    if requests is None:
        LOGGER.warning("requests kurulu değil, profil çekilemedi.")
        return None
    url = sablon.replace("{steamid}", sid)
    token = token_oku(ayar)
    basliklar = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.get(url, headers=basliklar, timeout=ayar.get("request_timeout", 15))
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        LOGGER.warning("Profil çekilemedi (%s): %s", url, e)
        return None


# ---------------------------------------------------------------- 2) NORMALİZE (SAF)
def yol_coz(ham, yol):
    """SAF. 'data.user' gibi noktalı yolu çözer; sonuç sözlük değilse None."""
    cur = ham
    for parca in yol.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(parca)
    return cur if isinstance(cur, dict) else None


def profil_koku_bul(ham, fm):
    """SAF. (profil_sözlüğü, kullanılan_kök|None). Birden fazla kök varsa İLK bulunan."""
    if not isinstance(ham, dict):
        return None, None
    for yol in p_aday(fm, "root_keys"):
        s = yol_coz(ham, yol)
        if s is not None:
            return s, yol
    return ham, None  # düz (iç içe olmayan) profil


def car_preferences_normalize(deger):
    """SAF. liste -> olduğu gibi; metin -> tek elemanlı liste; sözlük -> anahtar listesi; diğer -> None."""
    if isinstance(deger, list):
        return list(deger)
    if isinstance(deger, str):
        m = deger.strip()
        return [m] if m else None
    if isinstance(deger, dict):
        return [str(k) for k in deger.keys()]
    return None


def normalize_profile(ham, fm, istenen_steamid=None):
    """
    SAF: ağ/disk/saat kullanmaz, log yazmaz. (profil|None, mesajlar) döner.
    steamid yoksa/geçersizse (veya istenenden farklıysa) kayıt atlanır -> None.
    elo/safetyrating çevrilemezse None olur, profil KALIR.
    """
    uyarilar = []
    try:
        kok, kok_ad = profil_koku_bul(ham, fm)
        if kok is None:
            return None, ["Profil verisi sözlük biçiminde değil, kayıt atlandı."]
        if kok_ad:
            uyarilar.append(f"{BILGI_ONEKI} Profil kök anahtarı kullanıldı: {kok_ad}")
        sid_ham = sec(kok, p_aday(fm, "steamid"))
        if sid_ham is None:
            return None, uyarilar + ["Profilde steamid yok, kayıt atlandı."]
        ok, mesaj = steamid_dogrula(sid_ham)
        if not ok:
            return None, uyarilar + [f"Profildeki steamid geçersiz, kayıt atlandı. {mesaj}"]
        sid = str(sid_ham).strip()
        if istenen_steamid is not None and sid != str(istenen_steamid).strip():
            return None, uyarilar + [f"Profildeki steamid ({sid}) istenenle ({istenen_steamid}) "
                                     "uyuşmuyor, kayıt atlandı."]
        lfm_ham = sec(kok, p_aday(fm, "lfm_id"))
        lfm_id = str(lfm_ham).strip() if lfm_ham is not None else ""
        if not lfm_id:
            uyarilar.append(f"Sürücü {sid}: 'lfm_id' alanı eksik.")
        profil = {"lfm_id": lfm_id or None, "steamid": sid}
        for alan, tip in CIKTI_ALANLARI:
            ham_d = sec(kok, p_aday(fm, alan))
            if ham_d is None:
                uyarilar.append(f"Sürücü {sid}: '{alan}' alanı eksik.")
                profil[alan] = None
            elif tip == "s":
                v = sayi_cevir(ham_d)
                if v is None:
                    uyarilar.append(f"Sürücü {sid}: '{alan}' sayıya çevrilemedi.")
                profil[alan] = v
            elif tip == "l":
                v = car_preferences_normalize(ham_d)
                if v is None:
                    uyarilar.append(f"Sürücü {sid}: '{alan}' desteklenmeyen biçimde, None yapıldı.")
                profil[alan] = v
            else:
                m = str(ham_d).strip()
                profil[alan] = m if m else None
        return profil, uyarilar
    except Exception as e:  # savunmacı: hiçbir profil tüm işlemi çökertmesin
        return None, uyarilar + [f"Profil işlenirken beklenmeyen hata: {e}"]


# ---------------------------------------------------------------- 3) BİRLEŞTİR (SAF)
def merge_profiles(mevcut, yeni, zaman):
    """
    SAF: girdileri değiştirmez. Mevcut profiller KORUNUR; aynı steamid'in yenisi
    eskisinin yerine geçer ve yeni 'fetched_at' alır.
    """
    sonuc = {k: dict(v) for k, v in (mevcut or {}).items() if isinstance(v, dict)}
    for sid, profil in (yeni or {}).items():
        p = dict(profil)
        p["fetched_at"] = zaman
        sonuc[sid] = p
    return sonuc


# ---------------------------------------------------------------- 4) CACHE
def profil_cache_yolu(ayar):
    return PROJE_KOK / ayar["profile_cache_path"]


def _cache_oku(ayar):
    """(profiller_sözlüğü, bozuk_mu). Dosya yoksa ({}, False); bozuksa ({}, True)."""
    yol = profil_cache_yolu(ayar)
    if not yol.is_file():
        return {}, False
    veri = read_cache(yol)
    if not isinstance(veri, dict) or not isinstance(veri.get("profiles"), dict):
        LOGGER.warning("profiles.json bozuk veya biçimi geçersiz: %s", yol)
        return {}, True
    return veri["profiles"], False


def read_profile_cache(ayar=None):
    """Yarış sırasında TEK okuma noktası: yalnızca diskten okur, {steamid: profil} döner."""
    ayar = ayar or profile_ayar_yukle()
    return _cache_oku(ayar)[0]


def write_profile_cache(profiller, ayar=None, zaman=None):
    """Atomik yazar (.tmp sonra replace). Tüm (birleştirilmiş) profilleri yazar."""
    ayar = ayar or profile_ayar_yukle()
    yol = profil_cache_yolu(ayar)
    write_cache(yol, {"generated_at": zaman or simdi_utc_iso(), "profiles": profiller})
    return yol


def guncelle_cache(yeni, ayar, zaman=None):
    """
    Yeni profilleri mevcutla birleştirip yazar. Yeni profil yoksa dosyaya DOKUNMAZ (None).
    Mevcut dosya bozuksa üzerine yazmadan önce .bozuk olarak yedekler.
    """
    if not yeni:
        LOGGER.warning("Yeni profil yok, profiles.json'a dokunulmadı.")
        return None
    mevcut, bozuk = _cache_oku(ayar)
    yol = profil_cache_yolu(ayar)
    if bozuk:
        try:
            yol.replace(yol.with_suffix(".bozuk"))
            LOGGER.warning("Bozuk profiles.json yedeklendi: %s", yol.with_suffix(".bozuk"))
        except OSError as e:
            LOGGER.warning("Bozuk dosya yedeklenemedi: %s", e)
    zaman = zaman or simdi_utc_iso()
    return write_profile_cache(merge_profiles(mevcut, yeni, zaman), ayar, zaman)


# ---------------------------------------------------------------- ÇOKLU ÇEKİM
def lobi_profilleri_cek(steamidler, ayar, fetch_fn=fetch_profile, bekle_fn=time.sleep):
    """
    Steam ID listesini sırayla çeker (tekrarlar atılır, geçersizler çekilmeden reddedilir,
    biri başarısız olursa diğerlerine devam edilir). (yeni_profiller, özet) döner.
    fetch_fn / bekle_fn test için değiştirilebilir.
    """
    sure, uyari = bekleme_suresi(ayar.get("profile_request_delay_s", 1))
    if uyari:
        LOGGER.warning(uyari)
    ozet = {"istenen": 0, "basarili": 0, "basarisiz": 0, "atlanan": 0}
    gorulen, sirali = set(), []
    for s in steamidler:
        ok, mesaj = steamid_dogrula(s)
        if not ok:
            LOGGER.error("Steam ID atlandı, çekilmedi. %s", mesaj)
            ozet["atlanan"] += 1
            continue
        sid = str(s).strip()
        if sid not in gorulen:
            gorulen.add(sid)
            sirali.append(sid)
    ozet["istenen"] = len(sirali)
    yeni = {}
    for i, sid in enumerate(sirali):
        if i > 0 and sure > 0:
            bekle_fn(sure)
        ham = fetch_fn(sid, ayar)
        if ham is None:
            LOGGER.warning("Profil çekilemedi: %s", sid)
            ozet["basarisiz"] += 1
            continue
        profil, mesajlar = normalize_profile(ham, ayar["field_map"], sid)
        mesajlari_logla(mesajlar)
        if profil is None:
            ozet["basarisiz"] += 1
            continue
        yeni[profil["steamid"]] = profil
        ozet["basarili"] += 1
    return yeni, ozet


# ---------------------------------------------------------------- KOMUTLAR
def _ozet_yaz(yeni, ozet, yol):
    LOGGER.info("Profil cache güncellendi: %s | %s", yol, ozet)
    print(f"Tamam: {yol} | istenen={ozet['istenen']} başarılı={ozet['basarili']} "
          f"başarısız={ozet['basarisiz']} atlanan={ozet['atlanan']}")


def komut_fetch(ayar, steamidler, fetch_fn=fetch_profile, bekle_fn=time.sleep):
    yeni, ozet = lobi_profilleri_cek(steamidler, ayar, fetch_fn, bekle_fn)
    if not yeni:
        print("[HATA] Hiç profil alınamadı; profiles.json'a dokunulmadı. Ayrıntı: logs/lfm.log")
        return 1
    yol = guncelle_cache(yeni, ayar)
    _ozet_yaz(yeni, ozet, yol)
    return 0


def komut_fetch_lobby(ayar, lobby_id, fetch_fn=fetch_profile, bekle_fn=time.sleep):
    ok, mesaj = lobby_id_dogrula(lobby_id)
    if not ok:
        print(f"[HATA] {mesaj}")
        return 1
    lobi = read_lobby_cache(lobby_id, ayar)
    if lobi is None:
        print(f"[HATA] Lobi cache'i yok veya okunamadı: {lobby_id}. Önce şunu çalıştırın: "
              f"python -m modules.lfm.lfm_lobby_cache --fetch {lobby_id}")
        return 1
    steamidler = [d.get("steamid") for d in lobi["drivers"] if isinstance(d, dict)]
    if not steamidler:
        print("[HATA] Lobi cache'inde sürücü yok; profiles.json'a dokunulmadı.")
        return 1
    return komut_fetch(ayar, steamidler, fetch_fn, bekle_fn)


def komut_show(ayar, steamid):
    ok, mesaj = steamid_dogrula(steamid)
    if not ok:
        print(f"[HATA] {mesaj}")
        return 1
    profil = read_profile_cache(ayar).get(str(steamid).strip())
    if profil is None:
        print(f"Steam ID {steamid} profil cache'inde yok.")
        return 1
    print(json.dumps(profil, ensure_ascii=False, indent=2))
    return 0


def _sahte_profil(sid, elo=2400, **ek):
    p = {"lfm_id": "9" + sid[-3:], "steamid": sid, "name": "S" + sid[-2:], "elo": elo,
         "safetyrating": 3.5, "license": "Gold", "carclass": "GT3",
         "carmodel": "ferrari_296_gt3", "split": 1, "car_preferences": ["GT3"]}
    p.update(ek)
    return p


def komut_selftest(ayar):
    """Sahte verilerle normalize/merge/cache/lobi birleştirme testi (ağ yok, bekleme yok)."""
    fm = ayar["field_map"]
    A, B, C = "76561190000000001", "76561190000000002", "76561190000000003"

    # 1) steamid doğrulaması ve yardımcılar
    for kotu in ["123", "7656119000000000a", "", None, True, "765611900000000011", 1.5]:
        assert steamid_dogrula(kotu)[0] is False, kotu
    assert steamid_dogrula(A)[0] and steamid_dogrula(int(A))[0]
    assert car_preferences_normalize(["a", "b"]) == ["a", "b"]
    assert car_preferences_normalize("GT3") == ["GT3"]
    assert car_preferences_normalize({"a": 1, "b": 2}) == ["a", "b"]
    assert car_preferences_normalize(None) is None and car_preferences_normalize(5) is None
    assert car_preferences_normalize("") is None and car_preferences_normalize([]) == []
    assert bekleme_suresi(0) == (0, None) and bekleme_suresi(2) == (2, None)
    assert bekleme_suresi(-1)[0] == 0 and bekleme_suresi(-1)[1]
    assert bekleme_suresi("abc")[0] == 0 and bekleme_suresi("abc")[1]

    # 2) normalize: düz profil + iç içe profil (profile_root_keys)
    pa, ua = normalize_profile(_sahte_profil(A), fm, A)
    assert pa and pa["steamid"] == A and pa["elo"] == 2400 and pa["car_preferences"] == ["GT3"], pa
    assert (pa, ua) == normalize_profile(_sahte_profil(A), fm, A), "SAF olmalı"
    ic = {"data": {"user": _sahte_profil(B, elo="2500", car_preferences="BMW")}}
    pb, ub = normalize_profile(ic, fm, B)
    assert pb and pb["elo"] == 2500 and pb["car_preferences"] == ["BMW"], pb
    assert any("data.user" in u for u in ub), ub
    iki_kok = {"profile": {"user": _sahte_profil(B, name="PROFIL")},
               "data": {"user": _sahte_profil(B, name="DATA")}}
    assert normalize_profile(iki_kok, fm)[0]["name"] == "DATA"  # ilk bulunan kök
    fm2 = dict(fm, profile_root_keys=["profile.user", "data.user"])
    pb2, ub2 = normalize_profile(iki_kok, fm2)
    assert pb2["name"] == "PROFIL" and any("profile.user" in u for u in ub2)

    # 3) geçersiz/eksik steamid: kayıt atlanır
    assert normalize_profile({"name": "x"}, fm)[0] is None
    assert normalize_profile(_sahte_profil("123"), fm)[0] is None
    assert normalize_profile(_sahte_profil(A), fm, B)[0] is None  # istenenle uyuşmuyor

    with tempfile.TemporaryDirectory() as t:
        a = dict(ayar, profile_cache_path=str(Path(t) / "profiles.json"), lobby_cache_dir=t)

        # 4) yaz-oku gidiş-dönüş (2 profil)
        yol = guncelle_cache({A: pa, B: pb}, a, "2026-11-02T10:00:00Z")
        assert yol.is_file() and not list(Path(t).glob("*.tmp")), ".tmp kalmamalı"
        ham_dosya = json.loads(yol.read_text(encoding="utf-8"))
        assert ham_dosya["generated_at"] == "2026-11-02T10:00:00Z"
        okunan = read_profile_cache(a)
        assert set(okunan) == {A, B}
        assert okunan[A] == dict(pa, fetched_at="2026-11-02T10:00:00Z"), "yaz -> oku aynı olmalı"

        # 5) merge: mevcut korunur, aynı steamid güncellenir (girdi değişmez)
        mevcut = {A: dict(pa, fetched_at="T1"), B: dict(pb, fetched_at="T1")}
        kopya = json.loads(json.dumps(mevcut))
        yeniA = dict(pa, elo=2999)
        birlesik = merge_profiles(mevcut, {A: yeniA}, "T2")
        assert mevcut == kopya, "merge girdiyi değiştirmemeli"
        assert birlesik[A]["elo"] == 2999 and birlesik[A]["fetched_at"] == "T2"
        assert birlesik[B] == mevcut[B], "güncellenmeyen profil korunmalı"
        guncelle_cache({A: yeniA}, a, "T2")
        okunan = read_profile_cache(a)
        assert okunan[A]["elo"] == 2999 and okunan[A]["fetched_at"] == "T2"
        assert okunan[B]["fetched_at"] == "2026-11-02T10:00:00Z", "B korunmalı"

        # 6) yeni profil yoksa dosya YAZILMAZ
        once = yol.read_bytes()
        assert guncelle_cache({}, a) is None and yol.read_bytes() == once

        # 7) --fetch-lobby birleştirme (sahte çekici, sahte bekleme)
        from modules.lfm.lfm_lobby_cache import lobi_veri_olustur, write_lobby_cache
        lobi = lobi_veri_olustur("test-lobi", [{"steamid": A}, {"steamid": C}, {"steamid": "123"},
                                               {"steamid": "76561190000000004"}, {"steamid": C}],
                                 "2026-11-02T10:00:00Z")
        write_lobby_cache("test-lobi", lobi, a)
        cagrilar, beklemeler = [], []

        def sahte_cek(sid, ayar_):
            cagrilar.append(sid)
            if sid.endswith("4"):
                return None  # biri başarısız: diğerleri devam etmeli
            return _sahte_profil(sid, elo=3100)

        ayar_bekle = dict(a, profile_request_delay_s=0.5)
        assert komut_fetch_lobby(ayar_bekle, "test-lobi", sahte_cek, beklemeler.append) == 0
        assert cagrilar == [A, C, "76561190000000004"], cagrilar  # "123" çekilmeden reddedildi, tekrar atıldı
        assert beklemeler == [0.5, 0.5], beklemeler
        okunan = read_profile_cache(a)
        assert set(okunan) == {A, B, C}, set(okunan)
        assert okunan[B]["fetched_at"] == "2026-11-02T10:00:00Z", "mevcut profil KORUNMALI"
        assert okunan[A]["elo"] == 3100 and okunan[C]["elo"] == 3100
        # bekleme 0 -> hiç bekleme yok
        beklemeler.clear()
        komut_fetch_lobby(dict(a, profile_request_delay_s=0), "test-lobi", sahte_cek, beklemeler.append)
        assert beklemeler == []

        # 8) lobi cache yok / sürücüsüz: net hata, profiles.json'a dokunulmaz
        once = (Path(t) / "profiles.json").read_bytes()
        assert komut_fetch_lobby(a, "yok-lobi", sahte_cek, beklemeler.append) == 1
        write_lobby_cache("bos-lobi", lobi_veri_olustur("bos-lobi", [], "T"), a)
        assert komut_fetch_lobby(a, "bos-lobi", sahte_cek, beklemeler.append) == 1
        assert (Path(t) / "profiles.json").read_bytes() == once
    print("SELFTEST TAMAM: tüm kontroller geçti.")
    return 0


def komut_badtest(ayar):
    """Boş/bozuk/steamid'siz veriyle çökmediğini doğrular."""
    fm = ayar["field_map"]
    for kotu in [None, "", "{bad", 5, [], {}, [1], {"data": "x"}, {"profile": {"user": {}}},
                 {"steamid": None}, {"steamid": "abc"}]:
        profil, mesajlar = normalize_profile(kotu, fm)
        assert profil is None and mesajlar, (kotu, profil, mesajlar)
    # yalnızca geçerli steamid olan profil: KALMALI, alanlar None
    p, m = normalize_profile({"steamid": "76561190000000001"}, fm)
    assert p and p["elo"] is None and p["car_preferences"] is None and len(m) >= 9, (p, m)
    # çevrilemeyen sayı ve desteklenmeyen car_preferences: profil kalır
    p, m = normalize_profile({"steamid": "76561190000000001", "elo": "abc",
                              "car_preferences": 7}, fm)
    assert p and p["elo"] is None and p["car_preferences"] is None
    with tempfile.TemporaryDirectory() as t:
        yol = Path(t) / "profiles.json"
        a = dict(ayar, profile_cache_path=str(yol), lobby_cache_dir=t, profile_url_template="")
        assert read_profile_cache(a) == {}  # dosya yok
        for icerik in ["{not json", "[]", '{"profiles": []}', ""]:
            yol.write_text(icerik, encoding="utf-8")
            assert read_profile_cache(a) == {}, icerik
        # bozuk dosya üzerine yazılmadan önce yedeklenir
        yol.write_text("{not json", encoding="utf-8")
        yeni, _ = normalize_profile(_sahte_profil("76561190000000001"), fm)
        guncelle_cache({yeni["steamid"]: yeni}, a)
        assert (Path(t) / "profiles.bozuk").is_file() and "76561190000000001" in read_profile_cache(a)
        once = yol.read_bytes()
        # ağa çıkmadan None dönmeli (geçersiz id / boş şablon)
        assert fetch_profile("../x", a) is None and fetch_profile("76561190000000001", a) is None
        # yalnızca geçersiz Steam ID'ler: hata, dosyaya dokunma
        assert komut_fetch(a, ["abc", "1", None], lambda s, y: None, lambda s: None) == 1
        assert komut_show(a, "abc") == 1
        assert yol.read_bytes() == once
    print("BADTEST TAMAM: bozuk veri çökmedi, uyarılar logs/lfm.log içinde.")
    return 0


def main():
    p = argparse.ArgumentParser(description="LFM sürücü profili cache")
    p.add_argument("--fetch", metavar="STEAMID", action="append",
                   help="profili çek (birden fazla kez verilebilir)")
    p.add_argument("--fetch-lobby", metavar="LOBBY_ID", help="lobideki tüm sürücülerin profilini çek")
    p.add_argument("--show", metavar="STEAMID", help="cache'teki profili göster")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--badtest", action="store_true")
    a = p.parse_args()
    ayar = profile_ayar_yukle()
    log_kur(ayar["log_path"])
    if a.selftest:
        return komut_selftest(ayar)
    if a.badtest:
        return komut_badtest(ayar)
    if a.fetch_lobby:
        return komut_fetch_lobby(ayar, a.fetch_lobby)
    if a.fetch:
        return komut_fetch(ayar, a.fetch)
    if a.show:
        return komut_show(ayar, a.show)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
