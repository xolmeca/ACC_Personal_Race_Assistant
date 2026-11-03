# -*- coding: utf-8 -*-
"""
modules/acc/acc_event_detector.py

ACC Personal Race Assistant - Olay dedektoru.
Girdi : acc_player_tracker.TakipDurumu (+ reader'dan EkGirdi)
Cikti : Olay listesi -> events.json (atomik yazim, son N olay)
Gecis tespiti: yalnizca komsu boyuna_m isaret degisimi (CrossingGate).
Yalnizca yerel isleme: internet yok, tus gonderimi yok, kayit yok.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import tempfile
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

PROJE_KOKU = Path(__file__).resolve().parents[2]
if str(PROJE_KOKU) not in sys.path:
    sys.path.insert(0, str(PROJE_KOKU))

from modules.acc import acc_player_tracker as T  # noqa: E402

LOG = logging.getLogger("acc_event_detector")

TUM_OLAYLAR = (
    "overtake_gained", "overtake_lost", "collision_suspect", "spin_suspect",
    "off_track", "pit_entry", "pit_exit", "penalty", "flag",
    "approaching_car", "closing_to_car_ahead",
)

FLAG_ADLARI = {0: "NO_FLAG", 1: "BLUE", 2: "YELLOW", 3: "BLACK",
               4: "WHITE", 5: "CHECKERED", 6: "PENALTY", 7: "GREEN", 8: "ORANGE"}

TARAF_ZAMAN_ASIMI_S = 3.0
G_MS2 = 9.81

_VARSAYILAN: Dict[str, Any] = {
    "etkin_olaylar": [
        "overtake_gained", "overtake_lost", "approaching_car",
        "closing_to_car_ahead", "pit_entry", "pit_exit", "flag", "penalty",
    ],
    "cooldown_s": {
        "overtake_gained": 3.0, "overtake_lost": 3.0,
        "approaching_car": 8.0, "closing_to_car_ahead": 8.0,
        "pit_entry": 5.0, "pit_exit": 5.0,
        "flag": 1.0, "penalty": 1.0,
        "off_track": 5.0, "collision_suspect": 5.0, "spin_suspect": 8.0,
    },
    "approaching_ttc_s": 3.0,
    "closing_ttc_s": 4.0,
    "yaklasma_max_mesafe_m": 50.0,
    "yaklasma_rearm_katsayi": 1.5,
    "gecis_histerezis_m": 1.5,
    "sira_pencere_s": 5.0,
    "gecis_debounce_s": 0.8,
    "komsu_menzil_m": 35.0,
    "gecis_cooldown_s": 10.0,
    "off_track_tekerlek_esik": 3,
    "off_track_esik_ms": 800.0,
    "collision_g_esik": 3.0,
    "collision_hiz_dusus_kmh": 15.0,
    "collision_komsu_m": 6.0,
    "collision_pencere_s": 0.5,
    "spin_yaw_hizi_esik": 1.5,
    "spin_heading_derece": 60.0,
    "spin_hiz_dusus_kmh": 20.0,
    "spin_pencere_s": 1.5,
    "events_dosya": "data/events.json",
    "max_olay": 2000,
}
_SAYISAL_DISI = ("etkin_olaylar", "cooldown_s", "events_dosya")


def varsayilan_ayar() -> Dict[str, Any]:
    a = dict(_VARSAYILAN)
    a["etkin_olaylar"] = list(_VARSAYILAN["etkin_olaylar"])
    a["cooldown_s"] = dict(_VARSAYILAN["cooldown_s"])
    return a


def _ayar_birlestir(bolum: Any) -> Dict[str, Any]:
    ayar = varsayilan_ayar()
    if not isinstance(bolum, dict):
        return ayar
    etkin = bolum.get("etkin_olaylar")
    if isinstance(etkin, (list, tuple, set)):
        gecerli: List[str] = []
        for x in etkin:
            if isinstance(x, str) and x in TUM_OLAYLAR:
                if x not in gecerli:
                    gecerli.append(x)
            else:
                LOG.warning("Bilinmeyen olay adi yok sayildi: %r", x)
        ayar["etkin_olaylar"] = gecerli
    cd = bolum.get("cooldown_s")
    if isinstance(cd, dict):
        for tip, v in cd.items():
            f = T._float_ya_da_none(v)
            if tip in TUM_OLAYLAR and f is not None and f >= 0:
                ayar["cooldown_s"][tip] = f
    for anahtar in _VARSAYILAN:
        if anahtar in _SAYISAL_DISI or anahtar not in bolum:
            continue
        f = T._float_ya_da_none(bolum[anahtar])
        if f is not None and f > 0:
            ayar[anahtar] = f
    ed = bolum.get("events_dosya")
    if isinstance(ed, str) and ed.strip():
        ayar["events_dosya"] = ed.strip()
    ayar["max_olay"] = max(1, int(ayar["max_olay"]))
    ayar["off_track_tekerlek_esik"] = min(4, max(1, int(ayar["off_track_tekerlek_esik"])))
    return ayar


def ayar_yukle(yol: Optional[Path] = None) -> Dict[str, Any]:
    yol = Path(yol) if yol else PROJE_KOKU / "config" / "thresholds.json"
    try:
        with open(yol, "r", encoding="utf-8-sig") as f:
            ham = json.load(f)
    except (OSError, ValueError) as e:
        LOG.warning("thresholds.json okunamadi (%s); olay dedektoru varsayilan ayarlari kullaniliyor.", e)
        return varsayilan_ayar()
    bolum = ham.get("event_detector") if isinstance(ham, dict) else None
    if not isinstance(bolum, dict):
        LOG.warning("thresholds.json icinde 'event_detector' bolumu yok; varsayilanlar kullaniliyor.")
        return varsayilan_ayar()
    return _ayar_birlestir(bolum)


def _simdi_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _temiz(v: Any, derinlik: int = 0) -> Any:
    if derinlik > 6:
        return None
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {str(k): _temiz(x, derinlik + 1) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_temiz(x, derinlik + 1) for x in v]
    return str(v)


def _vektor(v: Any, n: int) -> Optional[Tuple[float, ...]]:
    if not isinstance(v, (list, tuple)) or len(v) < n:
        return None
    cikti: List[float] = []
    for x in v[:n]:
        f = T._float_ya_da_none(x)
        if f is None:
            return None
        cikti.append(f)
    return tuple(cikti)


def _aci_fark(a: float, b: float) -> float:
    return (b - a + math.pi) % (2 * math.pi) - math.pi


@dataclass
class EkGirdi:
    flag: Optional[int] = None
    flag_adi: Optional[str] = None
    penalty: Optional[int] = None
    penalty_time: Optional[float] = None
    tyres_out: Optional[int] = None
    ang_vel: Any = None
    acc_g: Any = None
    wheel_slip: Any = None


@dataclass
class Olay:
    zaman_iso: str
    oturum_s: float
    tip: str
    siddet: str
    car_id: Optional[int]
    ayrinti: Dict[str, Any]
    guven: str

    def to_dict(self) -> Dict[str, Any]:
        return _temiz(asdict(self))


def reader_to_ek(tum: Any) -> Tuple[EkGirdi, List[str]]:
    eksik: List[str] = []
    try:
        k = T._kaynaklar(tum)
        g_t = ("graphics", "physics", "static", "session", "top")
        p_t = ("physics", "graphics", "static", "session", "top")

        def al(ad: str, adaylar: Tuple[str, ...], tercih: Tuple[str, ...]) -> Any:
            v = T._ara(k, adaylar, tercih)
            if v is T._YOK:
                eksik.append(ad)
                return None
            return v

        flag = al("flag", ("flag",), g_t)
        flag_adi = al("flag_name", ("flagname",), g_t)
        pen = al("penalty", ("penalty",), g_t)
        pen_t = al("penalty_time", ("penaltytime",), g_t)
        tyres = al("number_of_tyres_out", ("numberoftyresout",), p_t)
        av = al("local_angular_vel", ("localangularvel",), p_t)
        ag = al("acc_g", ("accg",), p_t)
        ws = al("wheel_slip", ("wheelslip",), p_t)
        ek = EkGirdi(
            flag=T._int_ya_da_none(flag),
            flag_adi=flag_adi if isinstance(flag_adi, str) else None,
            penalty=T._int_ya_da_none(pen),
            penalty_time=T._float_ya_da_none(pen_t),
            tyres_out=T._int_ya_da_none(tyres),
            ang_vel=_vektor(av, 3),
            acc_g=_vektor(ag, 3),
            wheel_slip=_vektor(ws, 4),
        )
        return ek, eksik
    except Exception as e:
        LOG.exception("Ek alan adaptoru hatasi")
        return EkGirdi(), ["adaptor_hatasi:" + type(e).__name__]


class CrossingGate:
    STAT_KEYS = ("histerezis_asildi", "olay_uretildi", "engel_debounce",
                 "engel_pencere", "engel_cooldown", "engel_menzil")

    def __init__(self, cfg: Optional[Dict[str, Any]] = None) -> None:
        cfg = cfg if isinstance(cfg, dict) else {}
        self.hyst = float(cfg.get("gecis_histerezis_m", 1.5))
        self.window = float(cfg.get("sira_pencere_s", 5.0))
        self.debounce = float(cfg.get("gecis_debounce_s", 0.8))
        self.rng = float(cfg.get("komsu_menzil_m", 35.0))
        self.cooldown = float(cfg.get("gecis_cooldown_s", 10.0))
        self.stats: Dict[str, int] = {k: 0 for k in self.STAT_KEYS}
        self._st: Dict[Any, Dict[str, Any]] = {}
        self._last_event: Dict[Any, float] = {}

    def reset(self) -> None:
        self._st.clear()

    def update(self, car_id: Any, t: float, boyuna_m: float) -> Optional[str]:
        d = boyuna_m
        if not math.isfinite(d) or not math.isfinite(t):
            return None
        if abs(d) > self.rng:
            st = self._st.pop(car_id, None)
            if st and st["flip"] is not None:
                self.stats["engel_menzil"] += 1
            return None
        st = self._st.setdefault(car_id, {"side": 0, "flip": None, "pend": None,
                                          "counted": False, "expired": False,
                                          "seen": t})
        st["seen"] = t
        raw = 1 if d > 0 else -1
        if st["side"] == 0:
            if abs(d) >= self.hyst:
                st["side"] = raw
            return None
        if raw == st["side"]:
            if st["pend"] is not None:
                self.stats["engel_debounce"] += 1
            st.update(flip=None, pend=None, counted=False, expired=False)
            return None
        if st["flip"] is None:
            st["flip"] = t
        if abs(d) < self.hyst:
            if st["pend"] is not None:
                self.stats["engel_debounce"] += 1
                st["pend"] = None
            if not st["expired"] and t - st["flip"] > self.window:
                self.stats["engel_pencere"] += 1
                st["expired"] = True
            return None
        if not st["counted"]:
            self.stats["histerezis_asildi"] += 1
            st["counted"] = True
        if st["pend"] is None:
            st["pend"] = t
        if t - st["pend"] < self.debounce:
            return None
        old = st["side"]
        expired = st["expired"] or (t - st["flip"] > self.window)
        if expired and not st["expired"]:
            self.stats["engel_pencere"] += 1
        st.update(side=raw, flip=None, pend=None, counted=False, expired=False)
        if expired:
            return None
        if t - self._last_event.get(car_id, -1e9) < self.cooldown:
            self.stats["engel_cooldown"] += 1
            return None
        self._last_event[car_id] = t
        self.stats["olay_uretildi"] += 1
        return "overtake_gained" if old > 0 else "overtake_lost"

    def prune(self, t: float, max_age: float) -> List[Tuple[Any, str]]:
        out: List[Tuple[Any, str]] = []
        for c, s in list(self._st.items()):
            age = t - s["seen"]
            if 0 <= age <= max_age:
                continue
            del self._st[c]
            if age < 0 or not s["counted"] or s["flip"] is None or s["expired"]:
                continue
            if s["seen"] - s["flip"] > self.window:
                continue
            self.stats["prune_onay"] = self.stats.get("prune_onay", 0) + 1
            if t - self._last_event.get(c, -1e9) < self.cooldown:
                self.stats["engel_cooldown"] += 1
                continue
            self._last_event[c] = t
            self.stats["olay_uretildi"] += 1
            out.append((c, "overtake_gained" if s["side"] > 0 else "overtake_lost"))
        return out

    def stats_line(self) -> str:
        return " | ".join(f"{k}={v}" for k, v in self.stats.items())


class OlayDedektoru:
    def __init__(self, ayar: Optional[Dict[str, Any]] = None) -> None:
        self.ayar = _ayar_birlestir(ayar)
        self.devre_disi: Set[str] = set()
        self._uyarilan: Set[str] = set()
        self._t0: Optional[float] = None
        self._son: Dict[Tuple[str, Optional[int]], float] = {}
        self._onceki_pit: Optional[bool] = None
        self._onceki_flag: Optional[int] = None
        self._onceki_penalty: Optional[int] = None
        self._gate = CrossingGate({k: self.ayar[k] for k in (
            "gecis_histerezis_m", "sira_pencere_s", "gecis_debounce_s",
            "komsu_menzil_m", "gecis_cooldown_s")})
        self._pit_ici_sifirla()

    def _a(self, anahtar: str) -> Any:
        return self.ayar[anahtar]

    def _etkin(self, tip: str) -> bool:
        return tip in self.ayar["etkin_olaylar"]

    def _cd(self, tip: str) -> float:
        return float(self.ayar["cooldown_s"].get(tip, 0.0))

    def _cooldown_ok(self, tip: str, key: Optional[int], t: float) -> bool:
        son = self._son.get((tip, key))
        if son is None or t < son:
            return True
        return (t - son) >= self._cd(tip)

    def _devre_disi_isaretle(self, tip: str, neden: str = "reader alani yok") -> None:
        self.devre_disi.add(tip)
        if tip not in self._uyarilan:
            self._uyarilan.add(tip)
            LOG.warning("Olay devre disi (%s): %s", neden, tip)

    def _uret(self, tip: str, siddet: str, car_id: Any, ayrinti: Dict[str, Any],
              guven: str, t: float, key: Optional[int], olaylar: List[Olay]) -> bool:
        if not self._etkin(tip) or not self._cooldown_ok(tip, key, t):
            return False
        t0 = self._t0 if self._t0 is not None else t
        o = Olay(zaman_iso=_simdi_iso(), oturum_s=round(t - t0, 3), tip=tip,
                 siddet=siddet, car_id=T._int_ya_da_none(car_id),
                 ayrinti=_temiz(ayrinti), guven=guven)
        self._son[(tip, key)] = t
        olaylar.append(o)
        return True

    def _pit_ici_sifirla(self) -> None:
        self._gate.reset()
        self._aktif: Set[Tuple[str, int]] = set()
        self._off_baslangic: Optional[float] = None
        self._off_atildi = False
        self._gecmis: Deque[Tuple[float, Optional[float], Optional[float]]] = deque(maxlen=400)

    def _durum_sifirla(self) -> None:
        self._onceki_pit = None
        self._onceki_flag = None
        self._onceki_penalty = None
        self._pit_ici_sifirla()

    def gecis_istatistik(self) -> str:
        return self._gate.stats_line()

    @staticmethod
    def _ek_temizle(ek: Any) -> EkGirdi:
        if not isinstance(ek, EkGirdi):
            return EkGirdi()
        return EkGirdi(
            flag=T._int_ya_da_none(ek.flag),
            flag_adi=ek.flag_adi if isinstance(ek.flag_adi, str) else None,
            penalty=T._int_ya_da_none(ek.penalty),
            penalty_time=T._float_ya_da_none(ek.penalty_time),
            tyres_out=T._int_ya_da_none(ek.tyres_out),
            ang_vel=_vektor(ek.ang_vel, 3),
            acc_g=_vektor(ek.acc_g, 3),
            wheel_slip=_vektor(ek.wheel_slip, 4),
        )

    def guncelle(self, durum: Any, ek: Any = None) -> List[Olay]:
        try:
            if not isinstance(durum, T.TakipDurumu):
                return []
            t = T._float_ya_da_none(durum.zaman)
            if t is None:
                return []
            if not durum.gecerli:
                self._durum_sifirla()
                return []
            return self._isle(durum, self._ek_temizle(ek), t)
        except Exception:
            LOG.exception("Olay dedektoru ic hata")
            return []

    def _isle(self, d: Any, ek: EkGirdi, t: float) -> List[Olay]:
        if self._t0 is None:
            self._t0 = t
        self.devre_disi = set()
        olaylar: List[Olay] = []
        pitte = bool(d.pitte_mi)
        self._pit_isle(d, t, pitte, olaylar)
        self._flag_isle(d, ek, t, olaylar)
        self._penalty_isle(d, ek, t, olaylar)
        if pitte:
            self._pit_ici_sifirla()
            return olaylar
        self._gecmis_ekle(d, t)
        self._gecis_isle(d, t, olaylar)
        self._yaklasma_isle(d, t, olaylar)
        self._off_track_isle(d, ek, t, olaylar)
        self._collision_isle(d, ek, t, olaylar)
        self._spin_isle(d, ek, t, olaylar)
        return olaylar

    def _pit_isle(self, d: Any, t: float, pitte: bool, olaylar: List[Olay]) -> None:
        onceki = self._onceki_pit
        self._onceki_pit = pitte
        if onceki is None or onceki == pitte:
            return
        tip = "pit_entry" if pitte else "pit_exit"
        self._uret(tip, "dusuk", d.car_id,
                   {"pist_yuzdesi": d.pist_yuzdesi, "tur": d.tur, "sira": d.sira},
                   "yuksek", t, None, olaylar)

    def _flag_isle(self, d: Any, ek: EkGirdi, t: float, olaylar: List[Olay]) -> None:
        if not self._etkin("flag"):
            return
        f = ek.flag
        if f is None:
            self._devre_disi_isaretle("flag")
            self._onceki_flag = None
            return
        onceki = self._onceki_flag
        self._onceki_flag = f
        if onceki is None or onceki == f:
            return
        siddet = "yuksek" if f in (3, 6) else ("orta" if f in (1, 2) else "dusuk")
        self._uret("flag", siddet, d.car_id, {
            "onceki": onceki, "yeni": f,
            "onceki_ad": FLAG_ADLARI.get(onceki, "BILINMIYOR"),
            "yeni_ad": ek.flag_adi or FLAG_ADLARI.get(f, "BILINMIYOR"),
            "not": "flag_esleme_dogrulanmadi",
        }, "dusuk", t, None, olaylar)

    def _penalty_isle(self, d: Any, ek: EkGirdi, t: float, olaylar: List[Olay]) -> None:
        if not self._etkin("penalty"):
            return
        p = ek.penalty
        if p is None:
            self._devre_disi_isaretle("penalty")
            self._onceki_penalty = None
            return
        onceki = self._onceki_penalty
        self._onceki_penalty = p
        if onceki is None or onceki == p:
            return
        self._uret("penalty", "yuksek" if p != 0 else "dusuk", d.car_id, {
            "onceki": onceki, "yeni": p,
            "ceza_suresi_ham": ek.penalty_time,
            "ceza_suresi_birimi": "dogrulanmadi",
        }, "orta", t, None, olaylar)

    def _gecis_isle(self, d: Any, t: float, olaylar: List[Olay]) -> None:
        for k in (d.on, d.arka):
            if not isinstance(k, T.KomsuDurumu):
                continue
            cid = T._int_ya_da_none(k.car_id)
            boy = T._float_ya_da_none(k.boyuna_m)
            if cid is None or boy is None:
                continue
            tip = self._gate.update(cid, t, boy)
            if tip:
                self._uret(tip, "orta", cid,
                           {"sira": d.sira, "boyuna_m": round(boy, 1)},
                           "yuksek" if k.guven == "yuksek" else "orta",
                           t, cid, olaylar)
        for cid2, tip2 in self._gate.prune(t, TARAF_ZAMAN_ASIMI_S):
            self._uret(tip2, "orta", cid2, {"sira": d.sira}, "orta", t, cid2, olaylar)

    def _yaklasma_isle(self, d: Any, t: float, olaylar: List[Olay]) -> None:
        kurallar = (("approaching_car", d.arka, "approaching_ttc_s"),
                    ("closing_to_car_ahead", d.on, "closing_ttc_s"))
        for tip, k, esik_ad in kurallar:
            if not self._etkin(tip):
                continue
            esik = float(self._a(esik_ad))
            rearm = esik * float(self._a("yaklasma_rearm_katsayi"))
            cid = None
            ttc = None
            if isinstance(k, T.KomsuDurumu):
                cid = T._int_ya_da_none(k.car_id)
                ttc = T._float_ya_da_none(k.ttc_s)
            if cid is None:
                self._aktif = {x for x in self._aktif if x[0] != tip}
                continue
            self._aktif = {x for x in self._aktif if x[0] != tip or x[1] == cid}
            mesafe = T._float_ya_da_none(k.mesafe_m)
            guven_ok = k.guven in ("orta", "yuksek")
            kosul = (ttc is not None and 0 <= ttc <= esik and guven_ok
                     and mesafe is not None
                     and mesafe <= float(self._a("yaklasma_max_mesafe_m")))
            if kosul:
                if (tip, cid) not in self._aktif:
                    ok = self._uret(tip, "yuksek" if ttc <= esik / 2 else "orta", cid, {
                        "ttc_s": round(ttc, 2),
                        "kapanma_kmh": T._float_ya_da_none(k.kapanma_kmh),
                        "mesafe_m": round(mesafe, 1),
                        "boyuna_m": T._float_ya_da_none(k.boyuna_m),
                    }, k.guven, t, cid, olaylar)
                    if ok:
                        self._aktif.add((tip, cid))
            elif ttc is None or ttc > rearm:
                self._aktif.discard((tip, cid))

    def _gecmis_ekle(self, d: Any, t: float) -> None:
        if self._gecmis and t < self._gecmis[-1][0]:
            self._gecmis.clear()
        self._gecmis.append((t, T._float_ya_da_none(d.hiz_kmh), T._float_ya_da_none(d.heading)))
        maks = max(float(self._a("collision_pencere_s")), float(self._a("spin_pencere_s"))) + 0.5
        while self._gecmis and t - self._gecmis[0][0] > maks:
            self._gecmis.popleft()

    def _yakin_komsu(self, d: Any, maks: float) -> Optional[Tuple[float, Any]]:
        en = None
        for k in (d.on, d.arka):
            if isinstance(k, T.KomsuDurumu):
                m = T._float_ya_da_none(k.mesafe_m)
                if m is not None and m <= maks and (en is None or m < en[0]):
                    en = (m, k)
        return en

    def _off_track_isle(self, d: Any, ek: EkGirdi, t: float, olaylar: List[Olay]) -> None:
        if not self._etkin("off_track"):
            return
        n = ek.tyres_out
        if n is None:
            self._devre_disi_isaretle("off_track")
            self._off_baslangic = None
            self._off_atildi = False
            return
        esik_n = int(self._a("off_track_tekerlek_esik"))
        if n >= esik_n:
            if self._off_baslangic is None or t < self._off_baslangic:
                self._off_baslangic = t
                return
            sure_ms = (t - self._off_baslangic) * 1000.0
            if not self._off_atildi and sure_ms >= float(self._a("off_track_esik_ms")):
                if self._uret("off_track", "orta", d.car_id,
                              {"pist_disi_tekerlek": n, "sure_ms": round(sure_ms, 0)},
                              "dusuk", t, None, olaylar):
                    self._off_atildi = True
        else:
            self._off_baslangic = None
            self._off_atildi = False

    def _collision_isle(self, d: Any, ek: EkGirdi, t: float, olaylar: List[Olay]) -> None:
        if not self._etkin("collision_suspect"):
            return
        hiz = T._float_ya_da_none(d.hiz_kmh)
        if hiz is None:
            self._devre_disi_isaretle("collision_suspect", "hiz_kmh yok")
            return
        pen = float(self._a("collision_pencere_s"))
        pencere = [(tt, h) for (tt, h, _) in self._gecmis
                   if h is not None and 0 <= t - tt <= pen]
        if len(pencere) < 2:
            return
        dusus = max(h for _, h in pencere) - hiz
        g: Optional[float] = None
        kaynak = "yok"
        if ek.acc_g is not None:
            g = math.hypot(ek.acc_g[0], ek.acc_g[2])
            kaynak = "acc_g"
        else:
            t_eski, h_eski = pencere[0]
            dt = t - t_eski
            if dt >= 0.05:
                g = (h_eski - hiz) / 3.6 / dt / G_MS2
                kaynak = "hiz_farki"
        if g is None:
            return
        komsu = self._yakin_komsu(d, float(self._a("collision_komsu_m")))
        if komsu is None:
            return
        g_esik = float(self._a("collision_g_esik"))
        if g >= g_esik and dusus >= float(self._a("collision_hiz_dusus_kmh")):
            self._uret("collision_suspect", "yuksek" if g >= 1.5 * g_esik else "orta",
                       d.car_id, {
                           "ivme_g": round(g, 2), "ivme_kaynagi": kaynak,
                           "hiz_dususu_kmh": round(dusus, 1),
                           "komsu_id": T._int_ya_da_none(komsu[1].car_id),
                           "komsu_mesafe_m": round(komsu[0], 1),
                       }, "dusuk", t, None, olaylar)

    def _spin_isle(self, d: Any, ek: EkGirdi, t: float, olaylar: List[Olay]) -> None:
        if not self._etkin("spin_suspect"):
            return
        if ek.ang_vel is None:
            self._devre_disi_isaretle("spin_suspect", "local_angular_vel yok")
            return
        yaw = abs(ek.ang_vel[1])
        if yaw < float(self._a("spin_yaw_hizi_esik")):
            return
        hd_simdi = T._float_ya_da_none(d.heading)
        hiz = T._float_ya_da_none(d.hiz_kmh)
        if hd_simdi is None or hiz is None:
            return
        pen = float(self._a("spin_pencere_s"))
        pencere = [(h, hd) for (tt, h, hd) in self._gecmis if 0 <= t - tt <= pen]
        sapmalar = [abs(_aci_fark(hd, hd_simdi)) for (_, hd) in pencere if hd is not None]
        hizlar = [h for (h, _) in pencere if h is not None]
        if not sapmalar or not hizlar:
            return
        sapma = math.degrees(max(sapmalar))
        dusus = max(hizlar) - hiz
        if sapma >= float(self._a("spin_heading_derece")) and dusus >= float(self._a("spin_hiz_dusus_kmh")):
            ayr = {"yaw_hizi": round(yaw, 2), "heading_sapma_derece": round(sapma, 1),
                   "hiz_dususu_kmh": round(dusus, 1)}
            if ek.wheel_slip is not None:
                ayr["maks_patinaj"] = round(max(ek.wheel_slip), 2)
            self._uret("spin_suspect", "orta", d.car_id, ayr, "dusuk", t, None, olaylar)


class OlayYazici:
    def __init__(self, yol: Any, max_olay: int = 2000) -> None:
        self.yol = Path(yol)
        self.max = max(1, int(max_olay))
        self._kayitlar: List[Dict[str, Any]] = []
        self._yukle()

    def _yedekle(self) -> None:
        try:
            os.replace(self.yol, self.yol.with_name(self.yol.name + ".bozuk"))
        except OSError:
            pass

    def _yukle(self) -> None:
        try:
            if not self.yol.exists():
                return
            with open(self.yol, "r", encoding="utf-8-sig") as f:
                ham = json.load(f)
            if not isinstance(ham, list):
                raise ValueError("events.json liste degil")
            self._kayitlar = [x for x in ham if isinstance(x, dict)][-self.max:]
        except (OSError, ValueError) as e:
            LOG.warning("events.json okunamadi/bozuk (%s); dosya yedeklenip bosla baslaniyor.", e)
            self._kayitlar = []
            self._yedekle()

    def ekle(self, olaylar: List[Olay]) -> bool:
        if not olaylar:
            return True
        for o in olaylar:
            if isinstance(o, Olay):
                self._kayitlar.append(o.to_dict())
        self._kayitlar = self._kayitlar[-self.max:]
        return self._yaz()

    def _yaz(self) -> bool:
        tmp = self.yol.with_name(self.yol.name + ".tmp")
        try:
            self.yol.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._kayitlar, f, ensure_ascii=False, indent=1)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.yol)
            return True
        except (OSError, TypeError, ValueError) as e:
            LOG.error("events.json yazilamadi: %s", e)
            try:
                tmp.unlink()
            except OSError:
                pass
            return False


def izle(sure_s: float) -> int:
    m = T._okuyucu_yukle()
    if m is None:
        return 2
    ayar = ayar_yukle()
    takipci = T.OyuncuTakipci(T.esik_yukle())
    ded = OlayDedektoru(ayar)
    yol = PROJE_KOKU / str(ayar["events_dosya"])
    yazici = OlayYazici(yol, int(ayar["max_olay"]))
    aralik = T._poll_araligi_s()
    t0 = time.monotonic()
    bitis = t0 + max(1.0, sure_s)
    son_yaz = 0.0
    toplam = 0
    ek_bildirildi = False
    yazma_uyarildi = False
    gorulen_devre_disi: Set[str] = set()
    print("Etkin olaylar:", ", ".join(ded.ayar["etkin_olaylar"]) or "(yok)")
    print("events.json  :", yol)
    try:
        while time.monotonic() < bitis:
            try:
                tum = T._tumunu_oku(m)
            except Exception as e:
                print("Okuma hatasi:", type(e).__name__, e)
                time.sleep(aralik)
                continue
            k = T._kaynaklar(tum)
            canli = T._ara(k, ("canli",), ("top",))
            if canli is False:
                if time.monotonic() - son_yaz >= 1.0:
                    print("ACC canli degil (canli=False); bekleniyor...")
                    son_yaz = time.monotonic()
                time.sleep(aralik)
                continue
            girdi, eksik = T.reader_to_girdi(tum)
            if eksik:
                print("EKSIK ALANLAR (tracker):", eksik)
                return 3
            durum = takipci.guncelle(girdi)
            ek, ek_eksik = reader_to_ek(tum)
            if ek_eksik and not ek_bildirildi:
                ek_bildirildi = True
                print("Reader'da bulunamayan ek alanlar:", ek_eksik, "-> ilgili olaylar devre disi")
            olaylar = ded.guncelle(durum, ek)
            gorulen_devre_disi |= ded.devre_disi
            simdi = time.monotonic()
            gecen = simdi - t0
            for o in olaylar:
                toplam += 1
                print(f"[{gecen:6.1f}s] OLAY {o.tip} siddet={o.siddet} car={o.car_id} "
                      f"guven={o.guven} {json.dumps(o.ayrinti, ensure_ascii=False)}")
            if olaylar and not yazici.ekle(olaylar) and not yazma_uyarildi:
                yazma_uyarildi = True
                print("UYARI: events.json yazilamadi; olaylar bellekte tutuluyor.")
            if simdi - son_yaz >= 1.0:
                print(T._durum_satiri(durum, gecen) + f" | olay={toplam}")
                son_yaz = simdi
            time.sleep(aralik)
    except KeyboardInterrupt:
        print("Kesildi.")
    print("[GECIS-SAYAC]", ded.gecis_istatistik())
    print(f"WATCH BITTI: {toplam} olay, devre disi gorulen: {sorted(gorulen_devre_disi) or '-'}")
    return 0


def _komsu(cid: Any, boy: float, yan: float = 0.0, ttc: Optional[float] = None,
           kap: Optional[float] = None, guven: str = "yuksek",
           mesafe: Optional[float] = None) -> Any:
    return T.KomsuDurumu(car_id=cid, boyuna_m=boy, yanal_m=yan,
                         mesafe_m=abs(boy) if mesafe is None else mesafe,
                         kapanma_kmh=kap, ttc_s=ttc, veri_yasi_ms=50.0, guven=guven)


def _durum(t: float, sira: int = 5, pitte: bool = False, on: Any = None, arka: Any = None,
           gecerli: bool = True, hiz: float = 150.0, heading: float = 0.0,
           cid: int = 1000) -> Any:
    return T.TakipDurumu(zaman=t, packet_id=int(t * 1000), gecerli=gecerli,
                         veri_yeterli=gecerli and not pitte,
                         neden="ok" if gecerli else "test", car_id=cid, pist_yuzdesi=0.5,
                         sira=sira, tur=1, hiz_kmh=hiz, heading=heading, pitte_mi=pitte,
                         on=on, arka=arka)


def _olay_ornek(i: int) -> Olay:
    return Olay(zaman_iso=_simdi_iso(), oturum_s=float(i), tip="flag", siddet="dusuk",
                car_id=1, ayrinti={"i": i}, guven="dusuk")


def selftest() -> int:
    c = T._Kontrol()
    print("== EVENT DETECTOR SELFTEST (sentetik veri) ==")

    def yeni(etkin: Optional[List[str]] = None, **ust: Any) -> OlayDedektoru:
        b: Dict[str, Any] = dict(ust)
        if etkin is not None:
            b["etkin_olaylar"] = list(etkin)
        return OlayDedektoru(b)

    def tipler(ol: List[Olay]) -> List[str]:
        return [o.tip for o in ol]

    def seri(ded: OlayDedektoru, cid: int, degerler: List[float], dt: float = 0.1,
             t0: float = 0.0, sira: int = 5) -> List[Olay]:
        ol: List[Olay] = []
        for i, b in enumerate(degerler):
            k = _komsu(cid, b)
            ol += ded.guncelle(_durum(t0 + i * dt, sira,
                                      on=k if b > 0 else None,
                                      arka=k if b <= 0 else None))
        return ol

    d = yeni()
    s = seri(d, 7, [6.0, 3.0] + [-3.0] * 12)
    c("1 temiz gecis (sira sabit): overtake_gained",
      tipler(s) == ["overtake_gained"] and s[0].car_id == 7, tipler(s))
    c("1 gecis sayaci olay_uretildi=1", "olay_uretildi=1" in d.gecis_istatistik(), d.gecis_istatistik())

    d = yeni()
    s = seri(d, 7, [6.0, 3.0, -3.0])
    c("1b debounce icinde gecis: olay yok", s == [], tipler(s))

    d = yeni()
    s = seri(d, 8, [-6.0, -3.0] + [3.0] * 12)
    c("1c overtake_lost", tipler(s) == ["overtake_lost"] and s[0].car_id == 8, tipler(s))

    d = yeni()
    s = []
    for i, sr in enumerate([5, 5, 4, 4, 4, 6]):
        s += d.guncelle(_durum(i * 2.0, sr))
    c("2 sira degisimi tek basina: olay yok", s == [])

    d = yeni()
    s = seri(d, 7, [6.0] + [-0.5] * 60 + [-3.0] * 12)
    c("2 belirsiz bolge pencereyi asti: olay yok", s == [], tipler(s))
    c("2 pencere sayaci artti", "engel_pencere=1" in d.gecis_istatistik(), d.gecis_istatistik())

    d = yeni()
    c("3 ilk olcum pitte: olay yok", d.guncelle(_durum(0.0, pitte=True)) == [])
    d = yeni()
    s = []
    s += d.guncelle(_durum(0.0, 5, on=_komsu(9, 6.0)))
    s += d.guncelle(_durum(0.1, 4, pitte=True))
    s += d.guncelle(_durum(10.0, 3, pitte=False, arka=_komsu(9, -4.0)))
    c("3 pit: yalnizca pit_entry/pit_exit", tipler(s) == ["pit_entry", "pit_exit"], tipler(s))

    d = yeni()
    s = d.guncelle(_durum(0.0, arka=_komsu(3, -20.0, ttc=2.0, kap=36.0)))
    c("4 approaching_car uretildi", tipler(s) == ["approaching_car"] and s[0].siddet == "orta", tipler(s))
    s = d.guncelle(_durum(0.1, arka=_komsu(3, -18.0, ttc=1.8, kap=36.0)))
    c("4 ayni yaklasma tekrar uretilmez", s == [])
    d.guncelle(_durum(0.2, arka=_komsu(3, -18.0, ttc=None, kap=0.0)))
    s = d.guncelle(_durum(0.3, arka=_komsu(3, -18.0, ttc=2.0, kap=36.0)))
    c("4 yeniden silahlanma ama cooldown: olay yok", s == [])
    s = d.guncelle(_durum(9.0, arka=_komsu(3, -18.0, ttc=2.0, kap=36.0)))
    c("4 cooldown sonrasi tekrar uretilir", tipler(s) == ["approaching_car"], tipler(s))
    d = yeni()
    s = d.guncelle(_durum(0.0, arka=_komsu(3, -20.0, ttc=5.0, kap=20.0)))
    s += d.guncelle(_durum(0.1, arka=_komsu(4, -20.0, ttc=1.0, kap=20.0, guven="dusuk")))
    s += d.guncelle(_durum(0.2, arka=_komsu(5, -80.0, ttc=1.0, kap=20.0)))
    c("4 esik ustu / dusuk guven / uzak arac: olay yok", s == [], tipler(s))

    d = yeni()
    s = d.guncelle(_durum(0.0, on=_komsu(4, 15.0, ttc=3.5, kap=20.0)))
    c("5 closing_to_car_ahead", tipler(s) == ["closing_to_car_ahead"] and s[0].car_id == 4, tipler(s))
    s = d.guncelle(_durum(0.1, on=_komsu(4, 14.0, ttc=3.0, kap=20.0)))
    c("5 tekrar yok", s == [])

    d = yeni()
    s = d.guncelle(_durum(0.0), EkGirdi(flag=0))
    c("6 ilk flag olcumu: olay yok", s == [])
    s = d.guncelle(_durum(1.0), EkGirdi(flag=2))
    c("6 flag degisimi: olay", tipler(s) == ["flag"] and s[0].siddet == "orta"
      and s[0].guven == "dusuk" and s[0].ayrinti.get("yeni_ad") == "YELLOW"
      and s[0].ayrinti.get("onceki_ad") == "NO_FLAG", tipler(s))
    c("6 flag ayni: olay yok", d.guncelle(_durum(2.0), EkGirdi(flag=2)) == [])
    s = d.guncelle(_durum(1.5, ), EkGirdi(flag=0))
    c("6 cooldown icinde degisim: olay yok", s == [])
    s = d.guncelle(_durum(3.0), EkGirdi(flag=2))
    c("6 cooldown sonrasi degisim: olay", tipler(s) == ["flag"], tipler(s))
    d = yeni()
    d.guncelle(_durum(0.0))
    c("6 ek alan yok: flag/penalty devre disi", {"flag", "penalty"} <= d.devre_disi, d.devre_disi)

    d = yeni()
    d.guncelle(_durum(0.0), EkGirdi(penalty=0))
    s = d.guncelle(_durum(1.0), EkGirdi(penalty=1, penalty_time=5.0))
    c("7 penalty degisimi: olay", tipler(s) == ["penalty"] and s[0].siddet == "yuksek"
      and s[0].ayrinti.get("ceza_suresi_ham") == 5.0
      and s[0].ayrinti.get("ceza_suresi_birimi") == "dogrulanmadi", tipler(s))

    d = yeni()
    d.guncelle(_durum(0.0), EkGirdi(flag=0))
    c("8 gecerli=False: olay yok", d.guncelle(_durum(1.0, gecerli=False), EkGirdi(flag=3)) == [])
    c("8 gecerli=False sonrasi sahte kenar yok", d.guncelle(_durum(2.0), EkGirdi(flag=3)) == [])

    d = yeni()
    s = []
    for i in range(30):
        s += d.guncelle(_durum(i * 0.1), EkGirdi(flag=0, penalty=0, tyres_out=4))
    c("9 off_track varsayilan kapali: olay yok", s == [], tipler(s))
    d = yeni(etkin=["off_track"])
    s = []
    for i in range(30):
        s += d.guncelle(_durum(i * 0.1), EkGirdi(tyres_out=4))
    c("9 off_track etkin: tek olay", tipler(s) == ["off_track"] and s[0].guven == "dusuk", tipler(s))
    d = yeni(etkin=["off_track"])
    s = []
    for i in range(6):
        s += d.guncelle(_durum(i * 0.1), EkGirdi(tyres_out=4))
    s += d.guncelle(_durum(0.7), EkGirdi(tyres_out=0))
    c("9 kisa sureli pist disi: olay yok", s == [], tipler(s))
    d = yeni(etkin=["off_track"])
    d.guncelle(_durum(0.0), EkGirdi(tyres_out=None))
    c("9 tyres_out yok: devre disi", "off_track" in d.devre_disi)

    kom = _komsu(9, -3.0)
    d = yeni(etkin=["collision_suspect"])
    s = d.guncelle(_durum(0.0, hiz=200.0), EkGirdi(acc_g=(0.0, 1.0, 0.0)))
    s += d.guncelle(_durum(0.1, hiz=200.0), EkGirdi(acc_g=(0.0, 1.0, 0.0)))
    c("10 collision oncesi: olay yok", s == [])
    s = d.guncelle(_durum(0.2, hiz=170.0, arka=kom), EkGirdi(acc_g=(0.5, 1.0, -4.0)))
    c("10 collision: acc_g + hiz dususu + yakin komsu",
      tipler(s) == ["collision_suspect"] and s[0].guven == "dusuk", tipler(s))
    d = yeni(etkin=["collision_suspect"])
    d.guncelle(_durum(0.0, hiz=200.0), EkGirdi(acc_g=(0.0, 1.0, 0.0)))
    d.guncelle(_durum(0.1, hiz=200.0), EkGirdi(acc_g=(0.0, 1.0, 0.0)))
    s = d.guncelle(_durum(0.2, hiz=170.0), EkGirdi(acc_g=(0.5, 1.0, -4.0)))
    c("10 komsu yok: olay yok", s == [])
    d = yeni(etkin=["collision_suspect"])
    d.guncelle(_durum(0.0, hiz=200.0), EkGirdi())
    d.guncelle(_durum(0.1, hiz=200.0), EkGirdi())
    s = d.guncelle(_durum(0.2, hiz=170.0, arka=kom), EkGirdi())
    c("10 acc_g yok: hiz farkindan ivme ile olay", tipler(s) == ["collision_suspect"]
      and s[0].ayrinti.get("ivme_kaynagi") == "hiz_farki", tipler(s))
    d = yeni(etkin=["collision_suspect"])
    s = []
    for i, h in enumerate((200.0, 190.0, 180.0)):
        s += d.guncelle(_durum(i * 0.25, hiz=h, arka=kom), EkGirdi(acc_g=(0.0, 1.0, -1.2)))
    c("10 normal frenleme: olay yok", s == [], tipler(s))

    d = yeni(etkin=["spin_suspect"])
    s = d.guncelle(_durum(0.0, hiz=150.0, heading=0.0), EkGirdi(ang_vel=(0.0, 0.1, 0.0)))
    s += d.guncelle(_durum(0.5, hiz=130.0, heading=0.6), EkGirdi(ang_vel=(0.0, 1.8, 0.0)))
    c("11 spin erken: olay yok", s == [], tipler(s))
    s = d.guncelle(_durum(1.0, hiz=100.0, heading=1.3), EkGirdi(ang_vel=(0.0, 2.2, 0.0)))
    c("11 spin: yaw + heading sapmasi + hiz dususu", tipler(s) == ["spin_suspect"], tipler(s))
    d = yeni(etkin=["spin_suspect"])
    s = []
    for i, hd in enumerate((0.0, 0.6, 1.3)):
        s += d.guncelle(_durum(i * 0.5, hiz=150.0, heading=hd), EkGirdi(ang_vel=(0.0, 0.4, 0.0)))
    c("11 dusuk yaw hizi: olay yok", s == [], tipler(s))
    d = yeni(etkin=["spin_suspect"])
    d.guncelle(_durum(0.0), EkGirdi())
    c("11 ang_vel yok: devre disi", "spin_suspect" in d.devre_disi)

    d = yeni()
    d.guncelle(_durum(100.0), EkGirdi(flag=0))
    s = d.guncelle(_durum(101.5), EkGirdi(flag=2))
    ok = len(s) == 1 and abs(s[0].oturum_s - 1.5) < 0.01 and s[0].zaman_iso.endswith("Z")
    if ok:
        try:
            datetime.fromisoformat(s[0].zaman_iso.replace("Z", "+00:00"))
        except ValueError:
            ok = False
    c("12 oturum_s ~1.5 ve UTC ISO 8601", ok)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "alt" / "events.json"
        y = OlayYazici(p, 3)
        r = y.ekle([_olay_ornek(i) for i in range(5)])
        veri = json.loads(p.read_text(encoding="utf-8"))
        anahtarlar = {"zaman_iso", "oturum_s", "tip", "siddet", "car_id", "ayrinti", "guven"}
        c("13 yazici: yazildi, son 3 olay tutuldu", r is True and len(veri) == 3
          and veri[-1]["ayrinti"]["i"] == 4, len(veri))
        c("13 yazici: kayit alanlari tam", all(set(x.keys()) == anahtarlar for x in veri))
        c("13 yazici: .tmp kalmadi", not p.with_name("events.json.tmp").exists())
        y2 = OlayYazici(p, 3)
        y2.ekle([_olay_ornek(9)])
        veri = json.loads(p.read_text(encoding="utf-8"))
        c("13 yazici: mevcut dosyaya eklenir", len(veri) == 3 and veri[-1]["ayrinti"]["i"] == 9)
        p2 = Path(td) / "bozuk.json"
        p2.write_text("{bozuk", encoding="utf-8")
        y3 = OlayYazici(p2, 10)
        y3.ekle([_olay_ornek(1)])
        c("13 bozuk JSON: yedeklendi ve yeniden baslandi",
          p2.with_name("bozuk.json.bozuk").exists() and len(json.loads(p2.read_text(encoding="utf-8"))) == 1)
        nan_olay = Olay(zaman_iso=_simdi_iso(), oturum_s=0.0, tip="flag", siddet="dusuk",
                        car_id=1, ayrinti={"x": float("nan")}, guven="dusuk")
        p3 = Path(td) / "nan.json"
        OlayYazici(p3, 5).ekle([nan_olay])
        c("13 NaN -> null (gecerli JSON)", json.loads(p3.read_text(encoding="utf-8"))[0]["ayrinti"]["x"] is None)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.json"
        p.write_text(json.dumps({"event_detector": {
            "etkin_olaylar": ["flag", "yok_tip", "off_track"],
            "cooldown_s": {"flag": 7, "penalty": -1},
            "approaching_ttc_s": 2.5, "closing_ttc_s": "abc", "max_olay": 50}}), encoding="utf-8")
        a = ayar_yukle(p)
        c("14 ayar: etkin_olaylar suzuldu", a["etkin_olaylar"] == ["flag", "off_track"], a["etkin_olaylar"])
        c("14 ayar: cooldown gecerli okunur, negatif reddedilir",
          a["cooldown_s"]["flag"] == 7.0 and a["cooldown_s"]["penalty"] == 1.0)
        c("14 ayar: sayisal alanlar", a["approaching_ttc_s"] == 2.5 and a["closing_ttc_s"] == 4.0
          and a["max_olay"] == 50 and isinstance(a["max_olay"], int))
        c("14 ayar: gecis varsayilanlari", a["gecis_histerezis_m"] == 1.5 and a["sira_pencere_s"] == 5.0
          and a["gecis_debounce_s"] == 0.8 and a["komsu_menzil_m"] == 35.0
          and a["gecis_cooldown_s"] == 10.0)
        c("14 ayar: dosya yok -> varsayilan", ayar_yukle(Path(td) / "yok.json") == varsayilan_ayar())
        p.write_text(json.dumps({"izleme": {}}), encoding="utf-8")
        c("14 ayar: bolum yok -> varsayilan", ayar_yukle(p) == varsayilan_ayar())

    tum = {
        "canli": True,
        "physics": {"number_of_tyres_out": 1, "local_angular_vel": [0.0, 0.2, 0.0],
                    "acc_g": [0.1, 1.0, 0.5], "wheel_slip": [0.1, 0.1, 0.2, 0.2]},
        "graphics": {"flag": 2, "flag_name": "YELLOW", "penalty": 0, "penalty_time": 0.0},
    }
    ek, eksik = reader_to_ek(tum)
    c("15 adaptor: alanlar dogru", ek.flag == 2 and ek.flag_adi == "YELLOW" and ek.penalty == 0
      and ek.tyres_out == 1 and ek.ang_vel == (0.0, 0.2, 0.0) and len(ek.acc_g) == 3
      and len(ek.wheel_slip) == 4 and eksik == [], (ek, eksik))
    ek, eksik = reader_to_ek({})
    c("15 adaptor: bos reader -> eksik bildirilir", ek.flag is None and len(eksik) >= 6, eksik)

    tk = T.OyuncuTakipci(dict(T._VARSAYILAN_ESIK))
    d = yeni()
    s = []
    for i, z in enumerate((-30, -25, -20, -15, -10)):
        durum = tk.guncelle(T._girdi(i * 0.5, diger={2: (0, z)}))
        s += d.guncelle(durum, EkGirdi(flag=0, penalty=0))
    c("16 gercek tracker cikti: tek approaching_car", tipler(s) == ["approaching_car"]
      and s[0].car_id == 2, tipler(s))

    cfg = dict(gecis_histerezis_m=1.5, sira_pencere_s=5.0, gecis_debounce_s=0.8,
               komsu_menzil_m=35, gecis_cooldown_s=10)

    def kosu(g: CrossingGate, cid: int, dizi: List[float], dt: float = 0.1) -> List[str]:
        cikti: List[str] = []
        for i, b in enumerate(dizi):
            r = g.update(cid, i * dt, b)
            if r:
                cikti.append(r)
        return cikti

    g = CrossingGate(cfg)
    c("17a gate temiz gecis gained", kosu(g, 1, [5, 3, 2, 1, 0, -1] + [-2] * 20) == ["overtake_gained"]
      and g.stats["olay_uretildi"] == 1, g.stats)
    g = CrossingGate(cfg)
    c("17b gate temiz gecis lost", kosu(g, 1, [-5, -3, -1, 0, 1] + [2] * 20) == ["overtake_lost"])
    g = CrossingGate(cfg)
    c("17c gate tek kare ziplama elenir", kosu(g, 1, [5, 4, 3, -3, 3, 4, 5, 5]) == []
      and g.stats["engel_debounce"] >= 1, g.stats)
    g = CrossingGate(cfg)
    ev = kosu(g, 1, [5, 3] + [-3] * 12 + [3] * 12 + [-3] * 12)
    c("17d gate cooldown", ev.count("overtake_gained") == 1 and g.stats["engel_cooldown"] >= 1, (ev, g.stats))
    g = CrossingGate(cfg)
    c("17e gate pencere asimi", kosu(g, 1, [3] + [-0.5] * 80 + [-3] * 12) == []
      and g.stats["engel_pencere"] >= 1, g.stats)
    g = CrossingGate(cfg)
    sonuc = kosu(g, 1, [5, 3, 50, -50, -3] * 3)
    g.update(2, 0.0, 5.0)
    g.prune(100.0, 5.0)
    c("17f gate menzil disi + prune", sonuc == [] and g.stats["engel_menzil"] >= 1 and 2 not in g._st, g.stats)

    if c.hata == 0:
        print(f"SELFTEST TAMAM ({c.say} kontrol)")
        return 0
    print(f"SELFTEST BASARISIZ ({c.hata}/{c.say} hata)")
    return 1


def badtest() -> int:
    c = T._Kontrol()
    print("== EVENT DETECTOR BADTEST (bozuk girdi) ==")
    nan, inf = float("nan"), float("inf")
    d = OlayDedektoru({"etkin_olaylar": list(TUM_OLAYLAR)})
    durumlar = [
        None, "x", 5,
        T.TakipDurumu(zaman=nan, gecerli=True),
        T.TakipDurumu(zaman=0.0, gecerli=False),
        T.TakipDurumu(zaman=1.0, gecerli=True, sira="abc", hiz_kmh="a", heading=nan,
                      on="x", arka=5, pitte_mi="evet"),
        T.TakipDurumu(zaman=2.0, gecerli=True,
                      on=T.KomsuDurumu(car_id=None, boyuna_m=nan, yanal_m=nan, mesafe_m=inf)),
        T.TakipDurumu(zaman=3.0, gecerli=True,
                      on=T.KomsuDurumu(car_id="a", boyuna_m="b", yanal_m=0, mesafe_m=1,
                                       ttc_s=nan, guven=None)),
        T.TakipDurumu(zaman=-5.0, gecerli=True),
    ]
    ekler = [None, "x", EkGirdi(flag="x", penalty=[1], penalty_time="q", tyres_out=nan,
                                ang_vel=("a",), acc_g=[1], wheel_slip="z", flag_adi=5),
             EkGirdi(flag=2, penalty=1, tyres_out=4, ang_vel=(0, 3, 0), acc_g=(9, 9, 9))]
    for i, dur in enumerate(durumlar):
        for j, ek in enumerate(ekler):
            try:
                r = d.guncelle(dur, ek)
                c(f"bad durum {i} / ek {j}: coker yok, liste doner", isinstance(r, list))
            except Exception as e:
                c(f"bad durum {i} / ek {j}: istisna FIRLATTI", False, repr(e))
    for i, ayar in enumerate([None, "abc", 5, {"etkin_olaylar": "x", "cooldown_s": None,
                                                "approaching_ttc_s": "a", "max_olay": -3},
                              {"cooldown_s": {"flag": nan, "yok": 1}, "events_dosya": 5}]):
        try:
            dd = OlayDedektoru(ayar)
            c(f"bad ayar {i}: varsayilanla calisir", dd.ayar["approaching_ttc_s"] > 0
              and dd.ayar["max_olay"] >= 1 and isinstance(dd.ayar["etkin_olaylar"], list))
        except Exception as e:
            c(f"bad ayar {i}: istisna FIRLATTI", False, repr(e))
    for i, x in enumerate([None, [], "abc", 5, {"physics": 5}, {"graphics": {"flag": "abc", "penalty": nan}}]):
        try:
            ek, eksik = reader_to_ek(x)
            c(f"bad adaptor {i}: coker yok", isinstance(ek, EkGirdi) and isinstance(eksik, list))
        except Exception as e:
            c(f"bad adaptor {i}: istisna FIRLATTI", False, repr(e))
    g = CrossingGate(None)
    c("bad gate: nan/inf girdi -> None", g.update(1, 0.0, nan) is None and g.update(1, nan, 3.0) is None
      and g.update(1, 0.0, inf) is None)
    with tempfile.TemporaryDirectory() as td:
        dosya = Path(td) / "dosya.txt"
        dosya.write_text("x", encoding="utf-8")
        try:
            y = OlayYazici(dosya / "alt" / "e.json", 5)
            r = y.ekle([_olay_ornek(1)])
            c("bad yazici: yazilamayan yol -> False, coker yok", r is False)
        except Exception as e:
            c("bad yazici: istisna FIRLATTI", False, repr(e))
        for i, metin in enumerate(["", "{", "null", '"x"', '[1, "a", {"tip": "flag"}]']):
            p = Path(td) / f"b{i}.json"
            p.write_text(metin, encoding="utf-8")
            try:
                y = OlayYazici(p, 10)
                r = y.ekle([_olay_ornek(i)])
                veri = json.loads(p.read_text(encoding="utf-8"))
                beklenen = 2 if i == 4 else 1
                c(f"bad json {i}: toparlandi", r is True and len(veri) == beklenen, len(veri))
            except Exception as e:
                c(f"bad json {i}: istisna FIRLATTI", False, repr(e))
        try:
            r = OlayYazici(Path(td) / "bos.json", 5).ekle([])
            c("bad yazici: bos liste -> True", r is True)
        except Exception as e:
            c("bad yazici bos liste: istisna FIRLATTI", False, repr(e))

    if c.hata == 0:
        print(f"BADTEST TAMAM ({c.say} kontrol)")
        return 0
    print(f"BADTEST BASARISIZ ({c.hata}/{c.say} hata)")
    return 1


def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="ACC olay dedektoru")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--selftest", action="store_true", help="ACC kapali, sentetik testler")
    g.add_argument("--badtest", action="store_true", help="ACC kapali, bozuk girdi testi")
    g.add_argument("--watch", type=float, metavar="N", help="ACC acik, N saniye canli olay tespiti")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.selftest:
        return selftest()
    if a.badtest:
        return badtest()
    return izle(a.watch)


if __name__ == "__main__":
    sys.exit(main())
