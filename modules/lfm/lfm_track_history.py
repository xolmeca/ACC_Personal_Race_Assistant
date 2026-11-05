# -*- coding: utf-8 -*-
"""
modules/lfm/lfm_track_history.py

LFM yaris sonuclarindan pist + arac modeli bazinda pace gecmisi cikarir.
Bu modul YARIS ONCESI calisir. Yaris sirasinda yalnizca cache dosyasi okunur.
"""

import argparse
import json
import logging
import re
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

PROJE_KOK = Path(__file__).resolve().parents[2]
AYAR_YOLU = PROJE_KOK / "config" / "settings.json"
LOGGER = logging.getLogger("lfm_track_history")

VARSAYILAN_AYAR = {
    "min_races_for_reliable": 3,
    "trend_threshold_ms": 100,
    "lap_time_unit": "ms",
    "request_timeout": 15,
    "cache_path": "data/lfm_cache/track_history.json",
    "raw_results_dir": "data/lfm_cache/raw_results",
    "log_path": "logs/lfm.log",
    "results_urls": [],
    "field_map": {
        "steamid": ["steamid", "steam_id", "steamId"],
        "track": ["track", "trackname", "track_name"],
        "carmodel": ["carmodel", "car_model", "car"],
        "best_lap": ["bestlap", "best_lap", "best_lap_time", "fastestlap"],
        "avg_lap": ["avglap", "avg_lap", "average_lap", "averagelap"],
        "race_id": ["raceid", "race_id", "id"],
        "finished_at": ["date", "finished_at", "timestamp", "race_date"],
        "rows_keys": ["results", "drivers", "entries", "data"],
    },
}


def simdi_utc_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ayar_yukle(ayar_yolu=AYAR_YOLU):
    ayar = json.loads(json.dumps(VARSAYILAN_AYAR))
    try:
        with open(ayar_yolu, "r", encoding="utf-8") as f:
            lfm = json.load(f).get("lfm", {})
        for k, v in lfm.items():
            if k == "field_map" and isinstance(v, dict):
                ayar["field_map"].update(v)
            else:
                ayar[k] = v
    except FileNotFoundError:
        print(f"[UYARI] {ayar_yolu} bulunamadi, varsayilan ayarlar kullaniliyor.")
    except (json.JSONDecodeError, OSError, AttributeError) as e:
        print(f"[UYARI] settings.json okunamadi ({e}), varsayilanlar kullaniliyor.")
    return ayar


def log_kur(log_yolu):
    yol = PROJE_KOK / log_yolu
    yol.parent.mkdir(parents=True, exist_ok=True)
    if LOGGER.handlers:
        return
    LOGGER.setLevel(logging.INFO)
    bicim = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(yol, encoding="utf-8"), logging.StreamHandler()):
        h.setFormatter(bicim)
        LOGGER.addHandler(h)


def sec(sozluk, anahtarlar):
    if not isinstance(sozluk, dict):
        return None
    for k in anahtarlar:
        v = sozluk.get(k)
        if v not in (None, ""):
            return v
    return None


def parse_lap_ms(deger, birim="ms"):
    try:
        if deger is None or isinstance(deger, bool):
            return None
        if isinstance(deger, str):
            m = re.match(r"^\s*(\d+):(\d{1,2})(?:[.,](\d{1,3}))?\s*$", deger)
            if m:
                ms = (int(m.group(1)) * 60 + int(m.group(2))) * 1000
                ms += int((m.group(3) or "0").ljust(3, "0"))
                return ms if ms > 0 else None
            deger = float(deger.replace(",", "."))
        v = float(deger) * (1000 if birim == "s" else 1)
        return round(v) if v > 0 else None
    except (ValueError, TypeError):
        return None


def fetch_race_results(url, timeout=15):
    if requests is None:
        LOGGER.warning("requests kurulu degil, agdan veri cekilemedi.")
        return None
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        LOGGER.warning("Veri cekilemedi (%s): %s", url, e)
        return None


def normalize_row(satir, meta, fm, birim):
    try:
        steamid = sec(satir, fm["steamid"])
        track = sec(satir, fm["track"]) or sec(meta, fm["track"])
        car = sec(satir, fm["carmodel"])
        if steamid is None or track is None or car is None:
            return None, "steamid/pist/arac alani eksik"
        best = parse_lap_ms(sec(satir, fm["best_lap"]), birim)
        avg = parse_lap_ms(sec(satir, fm["avg_lap"]), birim)
        if best is None and avg is None:
            return None, "tur suresi alani yok veya gecersiz"
        return {
            "steamid": str(steamid),
            "track": str(track).strip().lower(),
            "car": str(car).strip().lower(),
            "best_ms": best,
            "avg_ms": avg,
            "race_id": str(sec(satir, fm["race_id"]) or sec(meta, fm["race_id"]) or ""),
            "date": str(sec(satir, fm["finished_at"]) or sec(meta, fm["finished_at"]) or ""),
        }, None
    except Exception as e:
        return None, f"beklenmeyen hata: {e}"


def satirlari_cikar(ham, fm):
    if isinstance(ham, list):
        return {}, [x for x in ham if isinstance(x, dict)]
    if isinstance(ham, dict):
        for k in fm["rows_keys"]:
            if isinstance(ham.get(k), list):
                return ham, [x for x in ham[k] if isinstance(x, dict)]
        alt = _liste_bul(ham.get("race_results"))
        if alt:
            return ham, alt
    return {}, []


def _liste_bul(v):
    """Ic ice sozlukte ilk dict listesini bulur (race_results > sinif > OVERALL)."""
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)] or None
    if isinstance(v, dict):
        for x in v.values():
            r = _liste_bul(x)
            if r:
                return r
    return None


def load_raw_results(klasor, fm, birim):
    kayitlar = []
    klasor = Path(klasor)
    if not klasor.is_dir():
        LOGGER.warning("Ham sonuc klasoru yok: %s", klasor)
        return kayitlar
    for dosya in sorted(klasor.glob("*.json")):
        try:
            with open(dosya, "r", encoding="utf-8") as f:
                ham = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            LOGGER.warning("Dosya okunamadi, atlandi (%s): %s", dosya.name, e)
            continue
        meta, satirlar = satirlari_cikar(ham, fm)
        if not satirlar:
            LOGGER.warning("Dosyada satir bulunamadi: %s", dosya.name)
            continue
        atlanan = 0
        for i, s in enumerate(satirlar):
            kayit, neden = normalize_row(s, meta, fm, birim)
            if kayit is None:
                atlanan += 1
                if atlanan <= 3:
                    LOGGER.warning("%s satir %d atlandi: %s", dosya.name, i, neden)
                continue
            if not kayit["race_id"]:
                kayit["race_id"] = dosya.stem
            kayitlar.append(kayit)
        if atlanan:
            LOGGER.warning("%s: toplam %d satir atlandi.", dosya.name, atlanan)
    return kayitlar


def compute_track_history(kayitlar, min_races=3, trend_esik_ms=100,
                          olusturma_zamani=""):
    gruplar = {}
    for k in kayitlar:
        anahtar = (k["steamid"], k["track"], k["car"])
        gruplar.setdefault(anahtar, {})[k["race_id"]] = k

    surucular = {}
    for (sid, track, car) in sorted(gruplar):
        yarislar = sorted(gruplar[(sid, track, car)].values(),
                          key=lambda r: (r["date"], r["race_id"]))
        bests = [r["best_ms"] for r in yarislar if r["best_ms"] is not None]
        avgs = [r["avg_ms"] for r in yarislar if r["avg_ms"] is not None]
        egim, etiket = None, "yetersiz_veri"
        if len(avgs) >= 2:
            egim = round(statistics.linear_regression(range(len(avgs)), avgs).slope, 1)
            etiket = ("iyilesiyor" if egim <= -trend_esik_ms
                      else "kotulesiyor" if egim >= trend_esik_ms else "sabit")
        n = len(yarislar)
        surucular.setdefault(sid, {}).setdefault(track, {})[car] = {
            "n_races": n,
            "reliable": n >= min_races,
            "best_lap_ms": min(bests) if bests else None,
            "avg_race_lap_ms": round(statistics.mean(avgs)) if avgs else None,
            "trend_ms_per_race": egim,
            "trend": etiket,
            "last_race": yarislar[-1]["date"] or None,
        }
    return {"generated_at": olusturma_zamani,
            "min_races_for_reliable": min_races,
            "drivers": surucular}


def write_cache(yol, veri):
    yol = Path(yol)
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(".tmp")
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=2, sort_keys=True)
    gecici.replace(yol)


def read_cache(yol):
    try:
        with open(yol, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        LOGGER.warning("Cache okunamadi (%s): %s", yol, e)
        return None


def komut_build(ayar, cek):
    raw_dir = PROJE_KOK / ayar["raw_results_dir"]
    if cek:
        raw_dir.mkdir(parents=True, exist_ok=True)
        damga = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        if not ayar["results_urls"]:
            LOGGER.warning("settings.json'da results_urls bos, agdan cekilmedi.")
        for i, url in enumerate(ayar["results_urls"]):
            veri = fetch_race_results(url, ayar["request_timeout"])
            if veri is not None:
                with open(raw_dir / f"cekilen_{damga}_{i}.json", "w", encoding="utf-8") as f:
                    json.dump(veri, f, ensure_ascii=False)
    kayitlar = load_raw_results(raw_dir, ayar["field_map"], ayar["lap_time_unit"])
    sonuc = compute_track_history(kayitlar, ayar["min_races_for_reliable"],
                                  ayar["trend_threshold_ms"], simdi_utc_iso())
    write_cache(PROJE_KOK / ayar["cache_path"], sonuc)
    LOGGER.info("Cache yazildi: %d kayit, %d surucu.", len(kayitlar), len(sonuc["drivers"]))


def komut_show(ayar, steamid):
    veri = read_cache(PROJE_KOK / ayar["cache_path"])
    if not veri:
        print("Cache yok veya okunamadi. Once --build calistirin.")
        return
    d = veri.get("drivers", {}).get(str(steamid))
    print(json.dumps(d, ensure_ascii=False, indent=2) if d
          else f"Steam ID {steamid} cache'te yok.")


def komut_ornek_veri(ayar):
    raw_dir = PROJE_KOK / ayar["raw_results_dir"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    for i, (b, a) in enumerate([(105000, 106000), (104500, 105500), (104000, 105000)], 1):
        veri = {"raceid": f"ornek_{i}", "date": f"2026-10-0{i}T20:00:00Z", "track": "monza",
                "results": [{"steamid": "76561190000000001", "carmodel": "ferrari_296_gt3",
                             "bestlap": b, "avglap": a}]}
        with open(raw_dir / f"ornek_yaris_{i}.json", "w", encoding="utf-8") as f:
            json.dump(veri, f)
    print(f"3 ornek dosya yazildi: {raw_dir}")


def komut_selftest():
    assert parse_lap_ms("1:45.123") == 105123
    assert parse_lap_ms(105.5, "s") == 105500
    assert parse_lap_ms(-1) is None and parse_lap_ms("abc") is None
    k = lambda sid, rid, d, b, a: {"steamid": sid, "track": "monza", "car": "x",
                                   "best_ms": b, "avg_ms": a, "race_id": rid, "date": d}
    kayit = [k("1", "r1", "2026-10-01", 105000, 106000),
             k("1", "r2", "2026-10-02", 104500, 105500),
             k("1", "r3", "2026-10-03", 104000, 105000),
             k("1", "r3", "2026-10-03", 104000, 105000),
             k("2", "r1", "2026-10-01", 107000, 108000)]
    s1 = compute_track_history(kayit, 3, 100, "T")
    a = s1["drivers"]["1"]["monza"]["x"]
    assert a["n_races"] == 3 and a["reliable"] is True, a
    assert a["best_lap_ms"] == 104000 and a["avg_race_lap_ms"] == 105500, a
    assert a["trend_ms_per_race"] == -500.0 and a["trend"] == "iyilesiyor", a
    b = s1["drivers"]["2"]["monza"]["x"]
    assert b["reliable"] is False and b["trend"] == "yetersiz_veri", b
    assert s1 == compute_track_history(kayit, 3, 100, "T")
    print("SELFTEST TAMAM: tum kontroller gecti.")


def komut_badtest(ayar):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / "bos.json").write_text("", encoding="utf-8")
        (t / "bozuk.json").write_text("{not json", encoding="utf-8")
        (t / "liste.json").write_text('[1, "a", null]', encoding="utf-8")
        (t / "eksik.json").write_text('{"results":[{"foo":1}]}', encoding="utf-8")
        kayitlar = load_raw_results(t, ayar["field_map"], ayar["lap_time_unit"])
    assert kayitlar == [], kayitlar
    assert compute_track_history([])["drivers"] == {}
    assert load_raw_results(t / "yok", ayar["field_map"], "ms") == []
    print("BADTEST TAMAM: bozuk veri cokmedi, uyarilar logs/lfm.log icinde.")


def main():
    p = argparse.ArgumentParser(description="LFM pist/arac pace gecmisi")
    p.add_argument("--build", action="store_true")
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--show", metavar="STEAMID")
    p.add_argument("--ornek-veri", action="store_true")
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--badtest", action="store_true")
    a = p.parse_args()
    ayar = ayar_yukle()
    log_kur(ayar["log_path"])
    if a.selftest:
        komut_selftest()
    elif a.badtest:
        komut_badtest(ayar)
    elif a.ornek_veri:
        komut_ornek_veri(ayar)
    elif a.build:
        komut_build(ayar, a.fetch)
    elif a.show:
        komut_show(ayar, a.show)
    else:
        p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
