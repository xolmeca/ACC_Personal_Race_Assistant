# -*- coding: utf-8 -*-
"""
modules/acc/acc_shared_memory_reader.py

ACC Shared Memory'yi (physics, graphics, static) YALNIZCA OKUMA modunda okur.
Ham veri katmanidir: filtreleme (komsu arac vb.) acc_player_tracker'da yapilir.
Tus gonderimi yok, ag yok, ACC'ye hicbir sey yazilmaz.
"""

import argparse
import ctypes
import json
import logging
import math
import mmap
import sys
import tempfile
import time
from pathlib import Path

from modules.lfm.lfm_track_history import AYAR_YOLU, PROJE_KOK, simdi_utc_iso

LOGGER = logging.getLogger("acc_shared_memory_reader")

FILE_MAP_READ = 0x0004
WATCH_ARALIK_S = 0.5

AC_LIVE = 2
DURUM_ADLARI = {0: "AC_OFF", 1: "AC_REPLAY", 2: "AC_LIVE", 3: "AC_PAUSE"}
OTURUM_ADLARI = {-1: "UNKNOWN", 0: "PRACTICE", 1: "QUALIFY", 2: "RACE", 3: "HOTLAP",
                 4: "TIME_ATTACK", 5: "DRIFT", 6: "DRAG", 7: "HOTSTINT", 8: "HOTSTINTSUPERPOLE"}
BAYRAK_ADLARI = {0: "NO_FLAG", 1: "BLUE", 2: "YELLOW", 3: "BLACK", 4: "WHITE",
                 5: "CHECKERED", 6: "PENALTY", 7: "GREEN", 8: "ORANGE"}

DOGRULANMADI = {
    "physics.tyre_dirty_level": "SDK'da var ama ACC'de kullanilmiyor olabilir (genelde 0).",
    "physics.turbo_boost": "Aracin turbosu yoksa 0 olabilir; anlami dogrulanmadi.",
    "physics.number_of_tyres_out": "Pist disi tanimi gercek oturumda dogrulanmadi.",
    "physics.gear": "ACC'de 0=geri, 1=bos, 2=1. vites olabilir; dogrulanmadi.",
    "graphics.is_valid_lap": "Ne zaman degistigi gercek oturumda dogrulanmadi.",
    "graphics.penalty_time": "Birimi ve davranisi dogrulanmadi.",
    "graphics.penalty": "Sayisal anlami dogrulanmadi (ham deger).",
    "graphics.flag": "Bayrak numaralari dokumana gore eslendi, gercek oturumda dogrulanmadi.",
    "graphics.mfd_tyre_pressure": "MFD ekranindaki deger; canli basinc icin physics.tyre_pressure_psi.",
    "session.session_time_left": "Birim ms varsayildi, dogrulanmadi.",
}

VARSAYILAN_AYAR = {
    "memory_names": {
        "physics": "Local\\acpmf_physics",
        "graphics": "Local\\acpmf_graphics",
        "static": "Local\\acpmf_static",
    },
    "poll_interval_ms": 50,
    "log_path": "logs/acc.log",
    "ranges": {
        "speed_kmh": [0, 400],
        "rpm": [0, 12000],
        "gear": [-1, 8],
        "fuel": [0, 200],
    },
    "warn_interval_s": 5,
}

F = ctypes.c_float
I = ctypes.c_int32
W15 = ctypes.c_uint16 * 15
W33 = ctypes.c_uint16 * 33


class PhysicsSayfa(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", I), ("gas", F), ("brake", F), ("fuel", F), ("gear", I), ("rpms", I),
        ("steerAngle", F), ("speedKmh", F), ("velocity", F * 3), ("accG", F * 3),
        ("wheelSlip", F * 4), ("wheelLoad", F * 4), ("wheelsPressure", F * 4),
        ("wheelAngularSpeed", F * 4), ("tyreWear", F * 4), ("tyreDirtyLevel", F * 4),
        ("tyreCoreTemperature", F * 4), ("camberRAD", F * 4), ("suspensionTravel", F * 4),
        ("drs", F), ("tc", F), ("heading", F), ("pitch", F), ("roll", F), ("cgHeight", F),
        ("carDamage", F * 5), ("numberOfTyresOut", I), ("pitLimiterOn", I), ("abs", F),
        ("kersCharge", F), ("kersInput", F), ("autoShifterOn", I), ("rideHeight", F * 2),
        ("turboBoost", F), ("ballast", F), ("airDensity", F), ("airTemp", F), ("roadTemp", F),
        ("localAngularVel", F * 3), ("finalFF", F), ("performanceMeter", F),
        ("engineBrake", I), ("ersRecoveryLevel", I), ("ersPowerLevel", I),
        ("ersHeatCharging", I), ("ersIsCharging", I), ("kersCurrentKJ", F),
        ("drsAvailable", I), ("drsEnabled", I), ("brakeTemp", F * 4),
    ]


class GraphicsSayfa(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("packetId", I), ("status", I), ("session", I),
        ("currentTime", W15), ("lastTime", W15), ("bestTime", W15), ("split", W15),
        ("completedLaps", I), ("position", I), ("iCurrentTime", I), ("iLastTime", I),
        ("iBestTime", I), ("sessionTimeLeft", F), ("distanceTraveled", F), ("isInPit", I),
        ("currentSectorIndex", I), ("lastSectorTime", I), ("numberOfLaps", I),
        ("tyreCompound", W33), ("replayTimeMultiplier", F), ("normalizedCarPosition", F),
        ("activeCars", I), ("carCoordinates", (F * 3) * 60), ("carID", I * 60),
        ("playerCarID", I), ("penaltyTime", F), ("flag", I), ("penalty", I),
        ("idealLineOn", I), ("isInPitLane", I), ("surfaceGrip", F), ("mandatoryPitDone", I),
        ("windSpeed", F), ("windDirection", F), ("isSetupMenuVisible", I),
        ("mainDisplayIndex", I), ("secondaryDisplayIndex", I), ("TC", I), ("TCCut", I),
        ("EngineMap", I), ("ABS", I), ("fuelXLap", F), ("rainLights", I),
        ("flashingLights", I), ("lightsStage", I), ("exhaustTemperature", F), ("wiperLV", I),
        ("driverStintTotalTimeLeft", I), ("driverStintTimeLeft", I), ("rainTyres", I),
        ("sessionIndex", I), ("usedFuel", F), ("deltaLapTime", W15), ("iDeltaLapTime", I),
        ("estimatedLapTime", W15), ("iEstimatedLapTime", I), ("isDeltaPositive", I),
        ("iSplit", I), ("isValidLap", I), ("fuelEstimatedLaps", F), ("trackStatus", W33),
        ("missingMandatoryPits", I), ("clock", F), ("directionLightsLeft", I),
        ("directionLightsRight", I), ("globalYellow", I), ("globalYellow1", I),
        ("globalYellow2", I), ("globalYellow3", I), ("globalWhite", I), ("globalGreen", I),
        ("globalChequered", I), ("globalRed", I), ("mfdTyreSet", I), ("mfdFuelToAdd", F),
        ("mfdTyrePressureLF", F), ("mfdTyrePressureRF", F), ("mfdTyrePressureLR", F),
        ("mfdTyrePressureRR", F), ("trackGripStatus", I), ("rainIntensity", I),
        ("rainIntensityIn10min", I), ("rainIntensityIn30min", I), ("currentTyreSet", I),
        ("strategyTyreSet", I),
    ]


class StaticSayfa(ctypes.Structure):
    _pack_ = 4
    _fields_ = [
        ("smVersion", W15), ("acVersion", W15), ("numberOfSessions", I), ("numCars", I),
        ("carModel", W33), ("track", W33), ("playerName", W33), ("playerSurname", W33),
        ("playerNick", W33), ("sectorCount", I), ("maxTorque", F), ("maxPower", F),
        ("maxRpm", I), ("maxFuel", F),
    ]


def _birlestir(varsayilan, kullanici):
    sonuc = json.loads(json.dumps(varsayilan))
    for k, v in (kullanici or {}).items():
        if isinstance(v, dict) and isinstance(sonuc.get(k), dict):
            sonuc[k].update(v)
        else:
            sonuc[k] = v
    return sonuc


def _sayi(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def acc_ayar_yukle(ayar_yolu=AYAR_YOLU):
    ham = {}
    try:
        with open(ayar_yolu, "r", encoding="utf-8") as f:
            ham = json.load(f).get("acc", {})
        if not isinstance(ham, dict):
            print("[UYARI] settings.json icindeki 'acc' bolumu sozluk degil, varsayilanlar kullaniliyor.")
            ham = {}
    except FileNotFoundError:
        print(f"[UYARI] {ayar_yolu} bulunamadi, ACC icin varsayilan ayarlar kullaniliyor.")
    except (json.JSONDecodeError, OSError, AttributeError) as e:
        print(f"[UYARI] settings.json okunamadi ({e}), ACC icin varsayilanlar kullaniliyor.")
    ayar = _birlestir(VARSAYILAN_AYAR, ham)
    p = _sayi(ayar.get("poll_interval_ms"))
    if p is None or p <= 0:
        print(f"[UYARI] poll_interval_ms gecersiz ({ayar.get('poll_interval_ms')!r}), 50 kullaniliyor.")
        ayar["poll_interval_ms"] = 50
    for ad, varsayilan in VARSAYILAN_AYAR["ranges"].items():
        r = ayar["ranges"].get(ad)
        ok = (isinstance(r, (list, tuple)) and len(r) == 2
              and _sayi(r[0]) is not None and _sayi(r[1]) is not None and r[0] <= r[1])
        if not ok:
            print(f"[UYARI] ranges.{ad} gecersiz ({r!r}), varsayilan {varsayilan} kullaniliyor.")
            ayar["ranges"][ad] = list(varsayilan)
    return ayar


def acc_log_kur(log_yolu):
    yol = Path(log_yolu)
    if not yol.is_absolute():
        yol = PROJE_KOK / yol
    yol.parent.mkdir(parents=True, exist_ok=True)
    if LOGGER.handlers:
        return
    LOGGER.setLevel(logging.INFO)
    bicim = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.FileHandler(yol, encoding="utf-8"), logging.StreamHandler()):
        h.setFormatter(bicim)
        LOGGER.addHandler(h)


_SON_UYARI = {}


def uyari_yaz(anahtar, mesaj, ayar=None):
    try:
        aralik = float((ayar or {}).get("warn_interval_s", 5))
    except (TypeError, ValueError):
        aralik = 5.0
    simdi = time.monotonic()
    son = _SON_UYARI.get(anahtar)
    if son is not None and simdi - son < aralik:
        return
    _SON_UYARI[anahtar] = simdi
    LOGGER.warning(mesaj)


def _uyarilari_yaz(onek, uyarilar, ayar, toplayici):
    for u in uyarilar:
        uyari_yaz(f"{onek}:{u.split(':')[0]}", f"{onek}: {u}", ayar)
        if toplayici is not None:
            toplayici.append(f"{onek}: {u}")


def _fl(arr, ad, uyarilar):
    sonuc = [_sayi(v) for v in arr]
    if any(v is None for v in sonuc):
        uyarilar.append(f"{ad}: NaN/sonsuz deger var, None yapildi.")
    return sonuc


def _fs(deger, ad, uyarilar):
    v = _sayi(deger)
    if v is None:
        uyarilar.append(f"{ad}: NaN/sonsuz deger, None yapildi.")
    return v


def _wstr(arr):
    ham = b"".join(int(x).to_bytes(2, "little") for x in arr)
    return ham.decode("utf-16-le", errors="replace").split("\x00")[0].strip()


def aralik_kontrol(ad, deger, aralik, uyarilar):
    if deger is None:
        return
    try:
        lo, hi = aralik
        if not (lo <= deger <= hi):
            uyarilar.append(f"{ad}: aralik disi deger {deger} (beklenen {lo}..{hi}).")
    except (TypeError, ValueError):
        uyarilar.append(f"{ad}: aralik ayari gecersiz, kontrol atlandi.")


def _kes(ham, sinif):
    boyut = ctypes.sizeof(sinif)
    if not isinstance(ham, (bytes, bytearray)) or len(ham) < boyut:
        return None, f"veri: kisa veya gecersiz (beklenen en az {boyut} bayt)."
    try:
        return sinif.from_buffer_copy(bytes(ham[:boyut])), None
    except (ValueError, TypeError) as e:
        return None, f"veri: yapi olusturulamadi: {e}"


def parse_physics(ham, araliklar=None):
    araliklar = araliklar or VARSAYILAN_AYAR["ranges"]
    p, hata = _kes(ham, PhysicsSayfa)
    if p is None:
        return None, [hata]
    u = []
    d = {
        "packet_id": int(p.packetId),
        "gas": _fs(p.gas, "gas", u),
        "brake": _fs(p.brake, "brake", u),
        "fuel": _fs(p.fuel, "fuel", u),
        "gear": int(p.gear),
        "rpm": int(p.rpms),
        "steer_angle": _fs(p.steerAngle, "steer_angle", u),
        "speed_kmh": _fs(p.speedKmh, "speed_kmh", u),
        "velocity": _fl(p.velocity, "velocity", u),
        "acc_g": _fl(p.accG, "acc_g", u),
        "wheel_slip": _fl(p.wheelSlip, "wheel_slip", u),
        "tyre_pressure_psi": _fl(p.wheelsPressure, "tyre_pressure_psi", u),
        "tyre_dirty_level": _fl(p.tyreDirtyLevel, "tyre_dirty_level", u),
        "tyre_core_temp_c": _fl(p.tyreCoreTemperature, "tyre_core_temp_c", u),
        "tc": _fs(p.tc, "tc", u),
        "abs": _fs(p.abs, "abs", u),
        "heading": _fs(p.heading, "heading", u),
        "pitch": _fs(p.pitch, "pitch", u),
        "roll": _fs(p.roll, "roll", u),
        "car_damage": _fl(p.carDamage, "car_damage", u),
        "number_of_tyres_out": int(p.numberOfTyresOut),
        "pit_limiter_on": int(p.pitLimiterOn),
        "turbo_boost": _fs(p.turboBoost, "turbo_boost", u),
        "air_temp": _fs(p.airTemp, "air_temp", u),
        "road_temp": _fs(p.roadTemp, "road_temp", u),
        "local_angular_vel": _fl(p.localAngularVel, "local_angular_vel", u),
        "brake_temp_c": _fl(p.brakeTemp, "brake_temp_c", u),
    }
    aralik_kontrol("speed_kmh", d["speed_kmh"], araliklar.get("speed_kmh"), u)
    aralik_kontrol("rpm", d["rpm"], araliklar.get("rpm"), u)
    aralik_kontrol("gear", d["gear"], araliklar.get("gear"), u)
    aralik_kontrol("fuel", d["fuel"], araliklar.get("fuel"), u)
    return d, u


def parse_graphics(ham):
    g, hata = _kes(ham, GraphicsSayfa)
    if g is None:
        return None, [hata]
    u = []
    n = int(g.activeCars)
    if n < 0 or n > 60:
        u.append(f"active_cars: aralik disi deger {n} (beklenen 0..60), kirpildi.")
        n = max(0, min(60, n))
    d = {
        "packet_id": int(g.packetId),
        "status": int(g.status),
        "status_name": DURUM_ADLARI.get(int(g.status), f"BILINMIYOR({int(g.status)})"),
        "session_type": int(g.session),
        "session_type_name": OTURUM_ADLARI.get(int(g.session), f"BILINMIYOR({int(g.session)})"),
        "completed_laps": int(g.completedLaps),
        "current_lap": int(g.completedLaps) + 1,
        "position": int(g.position),
        "current_time_ms": int(g.iCurrentTime),
        "last_time_ms": int(g.iLastTime),
        "best_time_ms": int(g.iBestTime),
        "session_time_left": _fs(g.sessionTimeLeft, "session_time_left", u),
        "distance_traveled": _fs(g.distanceTraveled, "distance_traveled", u),
        "is_in_pit": int(g.isInPit),
        "is_in_pit_lane": int(g.isInPitLane),
        "current_sector_index": int(g.currentSectorIndex),
        "number_of_laps": int(g.numberOfLaps),
        "tyre_compound": _wstr(g.tyreCompound),
        "normalized_car_position": _fs(g.normalizedCarPosition, "normalized_car_position", u),
        "active_cars": n,
        "car_coordinates": [[_sayi(v) for v in g.carCoordinates[i]] for i in range(n)],
        "car_id": [int(g.carID[i]) for i in range(n)],
        "player_car_id": int(g.playerCarID),
        "penalty_time": _fs(g.penaltyTime, "penalty_time", u),
        "flag": int(g.flag),
        "flag_name": BAYRAK_ADLARI.get(int(g.flag), f"BILINMIYOR({int(g.flag)})"),
        "penalty": int(g.penalty),
        "is_valid_lap": int(g.isValidLap),
        "mandatory_pit_done": int(g.mandatoryPitDone),
        "surface_grip": _fs(g.surfaceGrip, "surface_grip", u),
        "wind_speed": _fs(g.windSpeed, "wind_speed", u),
        "wind_direction": _fs(g.windDirection, "wind_direction", u),
        "used_fuel": _fs(g.usedFuel, "used_fuel", u),
        "fuel_estimated_laps": _fs(g.fuelEstimatedLaps, "fuel_estimated_laps", u),
        "global_yellow": int(g.globalYellow),
        "global_white": int(g.globalWhite),
        "global_green": int(g.globalGreen),
        "global_chequered": int(g.globalChequered),
        "global_red": int(g.globalRed),
        "mfd_tyre_pressure": [_sayi(g.mfdTyrePressureLF), _sayi(g.mfdTyrePressureRF),
                              _sayi(g.mfdTyrePressureLR), _sayi(g.mfdTyrePressureRR)],
        "track_grip_status": int(g.trackGripStatus),
        "rain_intensity": int(g.rainIntensity),
        "rain_intensity_in_10min": int(g.rainIntensityIn10min),
        "rain_intensity_in_30min": int(g.rainIntensityIn30min),
        "current_tyre_set": int(g.currentTyreSet),
        "strategy_tyre_set": int(g.strategyTyreSet),
    }
    return d, u


def parse_static(ham):
    s, hata = _kes(ham, StaticSayfa)
    if s is None:
        return None, [hata]
    u = []
    d = {
        "sm_version": _wstr(s.smVersion),
        "ac_version": _wstr(s.acVersion),
        "number_of_sessions": int(s.numberOfSessions),
        "num_cars": int(s.numCars),
        "car_model": _wstr(s.carModel),
        "track": _wstr(s.track),
        "player_name": _wstr(s.playerName),
        "player_surname": _wstr(s.playerSurname),
        "player_nick": _wstr(s.playerNick),
        "sector_count": int(s.sectorCount),
        "max_rpm": int(s.maxRpm),
        "max_fuel": _fs(s.maxFuel, "max_fuel", u),
    }
    return d, u


def graphics_gecerli_mi(g):
    if not isinstance(g, dict):
        return False, "veri yok"
    if g.get("packet_id", 0) <= 0:
        return False, f"packetId gecersiz ({g.get('packet_id')})"
    if g.get("status") != AC_LIVE:
        return False, f"status={g.get('status_name')} (AC_LIVE degil)"
    return True, ""


def physics_gecerli_mi(p):
    if not isinstance(p, dict):
        return False, "veri yok"
    if p.get("packet_id", 0) <= 0:
        return False, f"packetId gecersiz ({p.get('packet_id')})"
    return True, ""


def static_gecerli_mi(s):
    if not isinstance(s, dict):
        return False, "veri yok"
    if not (s.get("sm_version") or s.get("track")):
        return False, "static sayfasi bos (oturum baslamamis)"
    return True, ""


def parse_session(physics, graphics, static):
    if not isinstance(graphics, dict):
        return None
    physics = physics if isinstance(physics, dict) else {}
    static = static if isinstance(static, dict) else {}
    return {
        "session_type": graphics.get("session_type"),
        "session_type_name": graphics.get("session_type_name"),
        "track": static.get("track") or None,
        "car_model": static.get("car_model") or None,
        "air_temp": physics.get("air_temp"),
        "road_temp": physics.get("road_temp"),
        "completed_laps": graphics.get("completed_laps"),
        "current_lap": graphics.get("current_lap"),
        "total_laps": graphics.get("number_of_laps"),
        "session_time_left": graphics.get("session_time_left"),
    }


def dogrulanmadi_notlari(sonuc):
    notlar = {}
    for yol, not_ in DOGRULANMADI.items():
        bolum, alan = yol.split(".", 1)
        if isinstance(sonuc.get(bolum), dict) and alan in sonuc[bolum]:
            notlar[yol] = not_
    return notlar


_K32 = None


def _kernel32():
    global _K32
    if _K32 is None:
        import ctypes.wintypes as wt
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenFileMappingW.argtypes = [wt.DWORD, wt.BOOL, wt.LPCWSTR]
        k.OpenFileMappingW.restype = wt.HANDLE
        k.CloseHandle.argtypes = [wt.HANDLE]
        k.CloseHandle.restype = wt.BOOL
        _K32 = k
    return _K32


def bellek_var_mi(ad):
    if sys.platform != "win32":
        return False
    try:
        k = _kernel32()
        h = k.OpenFileMappingW(FILE_MAP_READ, False, ad)
        if not h:
            return False
        k.CloseHandle(h)
        return True
    except (OSError, AttributeError) as e:
        LOGGER.warning("Bellek varlik kontrolu basarisiz (%s): %s", ad, e)
        return False


def _oku_ham(ad, boyut, etiket, ayar):
    if sys.platform != "win32":
        uyari_yaz(f"{etiket}:platform", f"ACC Shared Memory yalnizca Windows'ta okunabilir "
                  f"(platform: {sys.platform}).", ayar)
        return None
    if not bellek_var_mi(ad):
        uyari_yaz(f"{etiket}:yok", f"ACC Shared Memory bulunamadi ({ad}); ACC kapali olabilir.", ayar)
        return None
    mm = None
    try:
        mm = mmap.mmap(-1, boyut, tagname=ad, access=mmap.ACCESS_READ)
        return mm[:boyut]
    except (OSError, ValueError) as e:
        uyari_yaz(f"{etiket}:okuma", f"ACC Shared Memory okunamadi ({ad}): {e}", ayar)
        return None
    finally:
        if mm is not None:
            try:
                mm.close()
            except Exception:
                pass


def read_physics(ayar=None, uyari_toplayici=None):
    ayar = ayar or acc_ayar_yukle()
    ham = _oku_ham(ayar["memory_names"]["physics"], ctypes.sizeof(PhysicsSayfa), "physics", ayar)
    if ham is None:
        return None
    d, u = parse_physics(ham, ayar["ranges"])
    _uyarilari_yaz("physics", u, ayar, uyari_toplayici)
    ok, neden = physics_gecerli_mi(d)
    if not ok:
        uyari_yaz("physics:gecersiz", f"Physics verisi gecersiz sayildi: {neden}", ayar)
        return None
    return d


def read_graphics(ayar=None, uyari_toplayici=None):
    ayar = ayar or acc_ayar_yukle()
    ham = _oku_ham(ayar["memory_names"]["graphics"], ctypes.sizeof(GraphicsSayfa), "graphics", ayar)
    if ham is None:
        return None
    d, u = parse_graphics(ham)
    _uyarilari_yaz("graphics", u, ayar, uyari_toplayici)
    ok, neden = graphics_gecerli_mi(d)
    if not ok:
        uyari_yaz("graphics:gecersiz",
                  f"ACC canli oturumda degil, graphics verisi gecersiz sayildi: {neden}", ayar)
        return None
    return d


def read_static(ayar=None, uyari_toplayici=None):
    ayar = ayar or acc_ayar_yukle()
    ham = _oku_ham(ayar["memory_names"]["static"], ctypes.sizeof(StaticSayfa), "static", ayar)
    if ham is None:
        return None
    d, u = parse_static(ham)
    _uyarilari_yaz("static", u, ayar, uyari_toplayici)
    ok, neden = static_gecerli_mi(d)
    if not ok:
        uyari_yaz("static:gecersiz", f"Static verisi gecersiz sayildi: {neden}", ayar)
        return None
    return d


def read_session(ayar=None, uyari_toplayici=None):
    ayar = ayar or acc_ayar_yukle()
    g = read_graphics(ayar, uyari_toplayici)
    if g is None:
        return None
    return parse_session(read_physics(ayar, uyari_toplayici), g, read_static(ayar, uyari_toplayici))


def read_all(ayar=None, uyari_toplayici=None):
    ayar = ayar or acc_ayar_yukle()
    sonuc = {"timestamp": simdi_utc_iso(), "canli": False}
    g = read_graphics(ayar, uyari_toplayici)
    s = read_static(ayar, uyari_toplayici)
    if s is not None:
        sonuc["static"] = s
    if g is None:
        return sonuc
    p = read_physics(ayar, uyari_toplayici)
    sonuc["graphics"] = g
    if p is not None:
        sonuc["physics"] = p
    sonuc["session"] = parse_session(p, g, s)
    sonuc["canli"] = p is not None
    return sonuc


def komut_read(ayar):
    toplayici = []
    sonuc = read_all(ayar, toplayici)
    sonuc["DOGRULANMADI"] = dogrulanmadi_notlari(sonuc)
    sonuc["uyarilar"] = toplayici
    print(json.dumps(sonuc, ensure_ascii=False, indent=2))
    if not sonuc["canli"]:
        print("[BILGI] ACC canli oturumda degil veya okunamadi. Ayrinti: logs/acc.log")
        return 1
    return 0


def _ozet_satiri(r):
    if not r["canli"]:
        return f"{r['timestamp']} | ACC canli oturumda degil"
    p, g = r["physics"], r["graphics"]
    return (f"{r['timestamp']} | hiz={p['speed_kmh']:.0f} | vites={p['gear']} | rpm={p['rpm']} | "
            f"sira={g['position']} | tur={g['current_lap']} | pist disi={p['number_of_tyres_out']} | "
            f"pit={g['is_in_pit']} | bayrak={g['flag_name']}")


def komut_watch(ayar, saniye):
    bitis = time.monotonic() + saniye
    try:
        while time.monotonic() < bitis:
            print(_ozet_satiri(read_all(ayar)))
            time.sleep(WATCH_ARALIK_S)
    except KeyboardInterrupt:
        print("Durduruldu.")
    return 0


def _wyaz(arr, metin):
    ham = metin.encode("utf-16-le")
    for i in range(len(ham) // 2):
        arr[i] = int.from_bytes(ham[2 * i:2 * i + 2], "little")


def komut_selftest(ayar):
    beklenen = {
        PhysicsSayfa: (364, {"gas": 4, "gear": 16, "speedKmh": 28, "wheelsPressure": 88,
                             "tyreDirtyLevel": 136, "tyreCoreTemperature": 152, "heading": 208,
                             "numberOfTyresOut": 244, "pitLimiterOn": 248, "turboBoost": 276,
                             "airTemp": 288, "roadTemp": 292, "localAngularVel": 296,
                             "brakeTemp": 348}),
        GraphicsSayfa: (1580, {"status": 4, "currentTime": 12, "completedLaps": 132,
                               "sessionTimeLeft": 152, "isInPit": 160, "tyreCompound": 176,
                               "replayTimeMultiplier": 244, "activeCars": 252,
                               "carCoordinates": 256, "carID": 976, "playerCarID": 1216,
                               "penaltyTime": 1220, "flag": 1224, "isInPitLane": 1236,
                               "windSpeed": 1248, "usedFuel": 1324, "deltaLapTime": 1328,
                               "iDeltaLapTime": 1360, "isValidLap": 1408, "trackStatus": 1416,
                               "globalYellow": 1500, "mfdTyrePressureLF": 1540,
                               "trackGripStatus": 1556, "strategyTyreSet": 1576}),
        StaticSayfa: (420, {"numCars": 64, "carModel": 68, "track": 134, "playerName": 200,
                            "sectorCount": 400, "maxRpm": 412, "maxFuel": 416}),
    }
    for sinif, (boyut, ofsetler) in beklenen.items():
        assert ctypes.sizeof(sinif) == boyut, (sinif.__name__, ctypes.sizeof(sinif), boyut)
        for alan, ofs in ofsetler.items():
            assert getattr(sinif, alan).offset == ofs, (sinif.__name__, alan,
                                                         getattr(sinif, alan).offset, ofs)
    tp = dict(PhysicsSayfa._fields_)
    tg = dict(GraphicsSayfa._fields_)
    ts = dict(StaticSayfa._fields_)
    assert tp["gear"] is ctypes.c_int32 and tp["rpms"] is ctypes.c_int32
    assert tp["speedKmh"] is ctypes.c_float and tp["packetId"] is ctypes.c_int32
    assert tg["status"] is ctypes.c_int32 and tg["sessionTimeLeft"] is ctypes.c_float
    assert tg["isValidLap"] is ctypes.c_int32 and tg["penaltyTime"] is ctypes.c_float
    assert ts["maxRpm"] is ctypes.c_int32 and ts["maxFuel"] is ctypes.c_float

    p = PhysicsSayfa()
    p.packetId, p.gear, p.rpms, p.speedKmh, p.fuel = 5, 4, 7000, 150.5, 40.0
    for i in range(4):
        p.wheelsPressure[i] = 27.0 + i
        p.tyreCoreTemperature[i] = 80.0 + i
    d, u = parse_physics(bytes(p), ayar["ranges"])
    assert d["speed_kmh"] == 150.5 and d["gear"] == 4 and d["rpm"] == 7000 and not u, u
    assert d["tyre_pressure_psi"] == [27.0, 28.0, 29.0, 30.0]
    assert d["tyre_core_temp_c"][3] == 83.0
    p.speedKmh, p.gear, p.rpms, p.fuel = 450.0, 12, 20000, 999.0
    d, u = parse_physics(bytes(p), ayar["ranges"])
    assert d["speed_kmh"] == 450.0 and d["gear"] == 12, "anormal deger yine de donmeli"
    assert len(u) == 4, u
    p.speedKmh = float("nan")
    d, u = parse_physics(bytes(p), ayar["ranges"])
    assert d["speed_kmh"] is None and any("speed_kmh" in x for x in u)
    json.dumps(d, allow_nan=False)
    assert parse_physics(b"kisa", ayar["ranges"])[0] is None
    assert parse_physics(None, ayar["ranges"])[0] is None
    assert physics_gecerli_mi({"packet_id": 0})[0] is False

    g = GraphicsSayfa()
    g.packetId, g.status, g.session, g.position, g.completedLaps = 9, 2, 2, 7, 3
    g.activeCars, g.playerCarID, g.flag, g.isValidLap = 2, 1002, 2, 1
    g.carCoordinates[0][0], g.carCoordinates[1][2] = 1.5, -2.5
    g.carID[0], g.carID[1] = 1001, 1002
    _wyaz(g.tyreCompound, "dry_compound")
    d, u = parse_graphics(bytes(g))
    assert d["active_cars"] == 2 and len(d["car_coordinates"]) == 2 and d["car_id"] == [1001, 1002]
    assert d["car_coordinates"][0][0] == 1.5 and d["car_coordinates"][1][2] == -2.5
    assert d["tyre_compound"] == "dry_compound" and d["current_lap"] == 4
    assert d["status_name"] == "AC_LIVE" and d["session_type_name"] == "RACE"
    assert d["flag_name"] == "YELLOW" and not u, u
    assert graphics_gecerli_mi(d) == (True, "")
    for durum in (0, 1, 3):
        g.status = durum
        assert graphics_gecerli_mi(parse_graphics(bytes(g))[0])[0] is False, durum
    g.status, g.packetId = 2, 0
    assert graphics_gecerli_mi(parse_graphics(bytes(g))[0])[0] is False
    g.packetId, g.activeCars = 9, 99
    d, u = parse_graphics(bytes(g))
    assert d["active_cars"] == 60 and len(d["car_id"]) == 60 and any("active_cars" in x for x in u)
    assert graphics_gecerli_mi(None)[0] is False

    s = StaticSayfa()
    _wyaz(s.smVersion, "1.9.0")
    _wyaz(s.track, "monza")
    _wyaz(s.carModel, "ferrari_296_gt3")
    s.maxRpm, s.maxFuel = 8500, 120.0
    sd, _ = parse_static(bytes(s))
    assert sd["track"] == "monza" and sd["car_model"] == "ferrari_296_gt3" and sd["max_rpm"] == 8500
    assert static_gecerli_mi(sd)[0] is True
    assert static_gecerli_mi(parse_static(bytes(StaticSayfa()))[0])[0] is False
    g.packetId, g.activeCars, g.numberOfLaps = 9, 2, 0
    p.speedKmh = 100.0
    p.airTemp, p.roadTemp = 22.0, 30.5
    oturum = parse_session(parse_physics(bytes(p))[0], parse_graphics(bytes(g))[0], sd)
    assert oturum["track"] == "monza" and oturum["air_temp"] == 22.0 and oturum["current_lap"] == 4
    assert oturum["session_type_name"] == "RACE" and oturum["road_temp"] == 30.5
    assert parse_session(None, None, None) is None

    notlar = dogrulanmadi_notlari({"physics": d_fiz(p), "graphics": d, "session": oturum})
    assert "physics.tyre_dirty_level" in notlar and "graphics.flag" in notlar
    assert "session.session_time_left" in notlar

    with tempfile.TemporaryDirectory() as t:
        yol = Path(t) / "settings.json"
        lfm = {"min_races_for_reliable": 3, "field_map": {"track": ["track"]}}
        yol.write_text(json.dumps({"lfm": lfm, "acc": {"poll_interval_ms": -5,
                       "ranges": {"gear": [5, 1], "rpm": [0, 9000]},
                       "log_path": "logs/x.log"}}), encoding="utf-8")
        a2 = acc_ayar_yukle(yol)
        assert a2["poll_interval_ms"] == 50 and a2["ranges"]["gear"] == [-1, 8]
        assert a2["ranges"]["rpm"] == [0, 9000] and a2["log_path"] == "logs/x.log"
        assert a2["memory_names"]["physics"] == "Local\\acpmf_physics"
        assert json.loads(yol.read_text(encoding="utf-8"))["lfm"] == lfm, "lfm bozulmamali"
        assert acc_ayar_yukle(Path(t) / "yok.json")["poll_interval_ms"] == 50

    kayitlar = []

    class Yakala(logging.Handler):
        def emit(self, kayit):
            kayitlar.append(kayit.getMessage())

    h = Yakala()
    LOGGER.addHandler(h)
    _SON_UYARI.clear()
    for _ in range(5):
        uyari_yaz("test:tekrar", "test uyarisi", {"warn_interval_s": 60})
    LOGGER.removeHandler(h)
    assert kayitlar == ["test uyarisi"], kayitlar
    _SON_UYARI.clear()

    acc_acik = any(bellek_var_mi(ad) for ad in ayar["memory_names"].values())
    if acc_acik:
        print("[BILGI] ACC acik gorunuyor: 'ACC kapaliyken None' adimi atlandi.")
    else:
        assert read_physics(ayar) is None and read_graphics(ayar) is None
        assert read_static(ayar) is None and read_session(ayar) is None
        r = read_all(ayar)
        assert r["canli"] is False and set(r) == {"timestamp", "canli"}, r
        assert r["timestamp"].endswith("Z")
    print("Isaretli (DOGRULANMADI) alanlar: " + ", ".join(sorted(DOGRULANMADI)))
    print("SELFTEST TAMAM: tum kontroller gecti.")
    return 0


def d_fiz(p):
    return parse_physics(bytes(p))[0]


def main():
    ap = argparse.ArgumentParser(description="ACC Shared Memory okuyucu (ham veri katmani)")
    ap.add_argument("--selftest", action="store_true", help="yapi + parse testi (ACC kapaliyken)")
    ap.add_argument("--read", action="store_true", help="tek okuma, JSON yazdir (ACC acikken)")
    ap.add_argument("--watch", metavar="N", type=float,
                    help="N saniye boyunca her 0.5 sn oku (yalnizca test)")
    a = ap.parse_args()
    ayar = acc_ayar_yukle()
    acc_log_kur(ayar["log_path"])
    if a.selftest:
        return komut_selftest(ayar)
    if a.read:
        return komut_read(ayar)
    if a.watch is not None:
        if a.watch <= 0:
            print("[HATA] --watch icin N sifirdan buyuk olmalidir.")
            return 1
        return komut_watch(ayar, a.watch)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
