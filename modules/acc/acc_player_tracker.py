# -*- coding: utf-8 -*-
"""
modules/acc/acc_player_tracker.py

ACC Personal Race Assistant - Oyuncu ve komsu arac takipcisi.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LOG = logging.getLogger("acc_player_tracker")
PROJE_KOKU = Path(__file__).resolve().parents[2]

ARAC_UZUNLUK_M = 4.7
ADAY_YANAL_TABAN_M = 8.0
ADAY_YANAL_KATSAYI = 0.3
ADAY_DIKEY_MAX_M = 8.0
HIST_MESAFE_M = 5.0
HIST_TARAF_M = 2.0
EMA_ALFA = 0.4
MIN_DT_S = 0.01
MAX_DT_S = 1.0
MAX_GORECELI_HIZ_MS = 120.0
HAREKET_MIN_M = 2.0
HAREKET_MIN_HIZ_KMH = 20.0
HAREKET_GECERLILIK_S = 1.5
OYUNCU_ISINLANMA_M = 50.0
YON_UYUMSUZ_DERECE = 45.0
VERI_ESKI_MS = 1000.0

_VARSAYILAN_ESIK: Dict[str, float] = {
    "ilgi_mesafesi_m": 60.0,
    "min_kapanma_kmh": 3.0,
    "yan_yana_boyuna_m": 4.5,
    "komsu_m": 4.0,
}


def _float_ya_da_none(x: Any) -> Optional[float]:
    if isinstance(x, bool):
        return None
    try:
        v = float(x)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) else None


def _int_ya_da_none(x: Any) -> Optional[int]:
    if isinstance(x, bool):
        return None
    try:
        if isinstance(x, float) and not math.isfinite(x):
            return None
        return int(x)
    except (TypeError, ValueError, OverflowError):
        return None


def _koordinat_oku(c: Any) -> Optional[Tuple[float, float, float]]:
    try:
        x, y, z = float(c[0]), float(c[1]), float(c[2])
    except (TypeError, ValueError, IndexError, KeyError, OverflowError):
        return None
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
        return None
    if x == 0.0 and y == 0.0 and z == 0.0:
        return None
    return (x, y, z)


def esik_yukle(yol: Optional[Path] = None) -> Dict[str, float]:
    esik = dict(_VARSAYILAN_ESIK)
    yol = Path(yol) if yol else PROJE_KOKU / "config" / "thresholds.json"
    try:
        with open(yol, "r", encoding="utf-8-sig") as f:
            ham = json.load(f)
    except (OSError, ValueError) as e:
        LOG.warning("thresholds.json okunamadi (%s); varsayilan esikler kullaniliyor.", e)
        return esik
    if not isinstance(ham, dict):
        return esik
    eslesme = (
        ("izleme", "ilgi_mesafesi_m"),
        ("relative_speed", "min_kapanma_kmh"),
        ("lateral_offset", "yan_yana_boyuna_m"),
        ("lateral_offset", "komsu_m"),
    )
    for bolum, anahtar in eslesme:
        b = ham.get(bolum)
        if isinstance(b, dict):
            v = _float_ya_da_none(b.get(anahtar))
            if v is not None and v > 0:
                esik[anahtar] = v
    return esik


@dataclass
class TrackerGirdi:
    zaman: float = 0.0
    packet_id: Optional[int] = None
    player_car_id: Optional[int] = None
    car_ids: Any = field(default_factory=list)
    koordinatlar: Any = field(default_factory=list)
    active_cars: Optional[int] = None
    pist_yuzdesi: Optional[float] = None
    sira: Optional[int] = None
    tur: Optional[int] = None
    hiz_kmh: Optional[float] = None
    heading: Optional[float] = None
    pitte_mi: bool = False


@dataclass
class KomsuDurumu:
    car_id: int
    boyuna_m: float
    yanal_m: float
    mesafe_m: float
    spline_farki: Optional[float] = None
    kapanma_kmh: Optional[float] = None
    ttc_s: Optional[float] = None
    veri_yasi_ms: Optional[float] = None
    guven: str = "dusuk"


@dataclass
class TakipDurumu:
    zaman: float = 0.0
    packet_id: Optional[int] = None
    gecerli: bool = False
    veri_yeterli: bool = False
    neden: str = ""
    car_id: Optional[int] = None
    pist_yuzdesi: Optional[float] = None
    sira: Optional[int] = None
    tur: Optional[int] = None
    hiz_kmh: Optional[float] = None
    heading: Optional[float] = None
    pitte_mi: bool = False
    yon_kaynagi: str = "yok"
    yon_farki_derece: Optional[float] = None
    on: Optional[KomsuDurumu] = None
    arka: Optional[KomsuDurumu] = None
    yan_yana: bool = False
    yan_yana_taraf: str = "yok"
    uyarilar: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class _Aday:
    cid: int
    boy: float
    yan: float
    mesafe: float
    xz: Tuple[float, float]


@dataclass
class _Gecmis:
    xz: Tuple[float, float]
    oyuncu_xz: Tuple[float, float]
    t: float
    mesafe: float
    kapanma_ms: Optional[float] = None
    n: int = 0


class OyuncuTakipci:
    def __init__(self, esik: Optional[Dict[str, float]] = None) -> None:
        self.esik = dict(esik) if esik else esik_yukle()
        self._on_id: Optional[int] = None
        self._arka_id: Optional[int] = None
        self._gecmis: Dict[int, _Gecmis] = {}
        self._ref_xz: Optional[Tuple[float, float]] = None
        self._ref_t: Optional[float] = None
        self._hareket_yon: Optional[Tuple[float, float]] = None
        self._hareket_t: Optional[float] = None

    def guncelle(self, girdi: Any) -> TakipDurumu:
        try:
            if not isinstance(girdi, TrackerGirdi):
                d = TakipDurumu(zaman=time.monotonic())
                return self._gecersiz(d, "girdi_tipi_hatali")
            return self._guncelle(girdi)
        except Exception as e:
            LOG.exception("tracker ic hata")
            d = TakipDurumu(zaman=time.monotonic())
            return self._gecersiz(d, "ic_hata:" + type(e).__name__)

    def _komsu_sifirla(self) -> None:
        self._on_id = None
        self._arka_id = None
        self._gecmis.clear()

    def _gecersiz(self, d: TakipDurumu, neden: str) -> TakipDurumu:
        self._komsu_sifirla()
        d.gecerli = False
        d.veri_yeterli = False
        d.neden = neden
        return d

    def _guncelle(self, g: TrackerGirdi) -> TakipDurumu:
        t = _float_ya_da_none(g.zaman)
        if t is None:
            t = time.monotonic()
        d = TakipDurumu(zaman=t, packet_id=_int_ya_da_none(g.packet_id))

        pid = _int_ya_da_none(g.player_car_id)
        ids = g.car_ids if isinstance(g.car_ids, (list, tuple)) else []
        koord = g.koordinatlar if isinstance(g.koordinatlar, (list, tuple)) else []
        n = min(len(ids), len(koord))
        ac = _int_ya_da_none(g.active_cars)
        if ac is not None and ac >= 0:
            n = min(n, ac)

        if pid is None:
            return self._gecersiz(d, "player_car_id_yok")
        idx = None
        for i in range(n):
            if _int_ya_da_none(ids[i]) == pid:
                idx = i
                break
        if idx is None:
            return self._gecersiz(d, "oyuncu_listede_yok")
        pc = _koordinat_oku(koord[idx])
        if pc is None:
            return self._gecersiz(d, "oyuncu_koordinati_gecersiz")

        d.car_id = pid
        yz = _float_ya_da_none(g.pist_yuzdesi)
        d.pist_yuzdesi = yz if (yz is not None and 0.0 <= yz <= 1.0) else None
        d.sira = _int_ya_da_none(g.sira)
        d.tur = _int_ya_da_none(g.tur)
        d.hiz_kmh = _float_ya_da_none(g.hiz_kmh)
        d.heading = _float_ya_da_none(g.heading)
        d.pitte_mi = bool(g.pitte_mi)

        p_x, p_y, p_z = pc
        self._hareket_guncelle(t, (p_x, p_z), d.hiz_kmh)

        if d.pitte_mi:
            self._komsu_sifirla()
            d.gecerli = True
            d.veri_yeterli = False
            d.neden = "oyuncu_pitte"
            return d

        fwd, kaynak = self._yon_sec(t, d.heading, d)
        d.yon_kaynagi = kaynak
        if fwd is None:
            self._komsu_sifirla()
            d.gecerli = True
            d.veri_yeterli = False
            d.neden = "yon_bilinmiyor"
            return d
        fx, fz = fwd

        ilgi = self.esik["ilgi_mesafesi_m"]
        adaylar: List[_Aday] = []
        for i in range(n):
            if i == idx:
                continue
            cid = _int_ya_da_none(ids[i])
            if cid is None or cid == pid:
                continue
            c = _koordinat_oku(koord[i])
            if c is None:
                continue
            dx, dy, dz = c[0] - p_x, c[1] - p_y, c[2] - p_z
            mesafe = math.hypot(dx, dz)
            if mesafe > ilgi or abs(dy) > ADAY_DIKEY_MAX_M:
                continue
            boy = dx * fx + dz * fz
            yan = dx * fz - dz * fx
            if abs(yan) > ADAY_YANAL_TABAN_M + ADAY_YANAL_KATSAYI * abs(boy):
                continue
            adaylar.append(_Aday(cid, boy, yan, mesafe, (c[0], c[2])))

        on_list = [a for a in adaylar if self._onde_mi(a)]
        arka_list = [a for a in adaylar if not self._onde_mi(a)]
        on_a = self._sec(on_list, self._on_id)
        arka_a = self._sec(arka_list, self._arka_id)
        self._on_id = on_a.cid if on_a else None
        self._arka_id = arka_a.cid if arka_a else None

        oyuncu_xz = (p_x, p_z)
        d.on = self._komsu_olustur(t, on_a, oyuncu_xz) if on_a else None
        d.arka = self._komsu_olustur(t, arka_a, oyuncu_xz) if arka_a else None
        tut = {self._on_id, self._arka_id}
        self._gecmis = {k: v for k, v in self._gecmis.items() if k in tut}

        d.yan_yana, d.yan_yana_taraf = self._yan_yana_bul(d.on, d.arka)
        d.gecerli = True
        d.veri_yeterli = True
        d.neden = "ok"
        return d

    def _hareket_guncelle(self, t: float, pxz: Tuple[float, float],
                          hiz: Optional[float]) -> None:
        if self._ref_xz is None or self._ref_t is None:
            self._ref_xz, self._ref_t = pxz, t
            return
        if t - self._ref_t > 2.0:
            self._ref_xz, self._ref_t = pxz, t
            return
        dx, dz = pxz[0] - self._ref_xz[0], pxz[1] - self._ref_xz[1]
        dist = math.hypot(dx, dz)
        if dist > OYUNCU_ISINLANMA_M:
            self._ref_xz, self._ref_t = pxz, t
            self._hareket_yon = None
            return
        if dist >= HAREKET_MIN_M:
            if hiz is None or hiz >= HAREKET_MIN_HIZ_KMH:
                self._hareket_yon = (dx / dist, dz / dist)
                self._hareket_t = t
            self._ref_xz, self._ref_t = pxz, t

    def _yon_sec(self, t: float, heading: Optional[float],
                 d: TakipDurumu) -> Tuple[Optional[Tuple[float, float]], str]:
        h_yon = None
        if heading is not None:
            if abs(heading) > 6.5:
                d.uyarilar.append("HEADING_BIRIM_SUPHELI")
            else:
                h_yon = (-math.sin(heading), math.cos(heading))
        m_yon = None
        if (self._hareket_yon is not None and self._hareket_t is not None
                and t - self._hareket_t <= HAREKET_GECERLILIK_S):
            m_yon = self._hareket_yon
        if h_yon and m_yon:
            dot = max(-1.0, min(1.0, h_yon[0] * m_yon[0] + h_yon[1] * m_yon[1]))
            fark = math.degrees(math.acos(dot))
            d.yon_farki_derece = fark
            if fark > YON_UYUMSUZ_DERECE:
                d.uyarilar.append("HEADING_HAREKETLE_UYUMSUZ")
                return m_yon, "hareket"
            return h_yon, "heading"
        if h_yon:
            return h_yon, "heading"
        if m_yon:
            return m_yon, "hareket"
        return None, "yok"

    def _onde_mi(self, a: _Aday) -> bool:
        if a.cid == self._on_id:
            return a.boy > -HIST_TARAF_M
        if a.cid == self._arka_id:
            return a.boy >= HIST_TARAF_M
        return a.boy >= 0.0

    @staticmethod
    def _sec_en_yakin(liste: List[_Aday]) -> Optional[_Aday]:
        return min(liste, key=lambda a: abs(a.boy)) if liste else None

    def _sec(self, liste: List[_Aday], onceki_id: Optional[int]) -> Optional[_Aday]:
        en_iyi = self._sec_en_yakin(liste)
        if en_iyi is None or onceki_id is None:
            return en_iyi
        onceki = next((a for a in liste if a.cid == onceki_id), None)
        if onceki is not None and onceki is not en_iyi:
            if abs(onceki.boy) - abs(en_iyi.boy) < HIST_MESAFE_M:
                return onceki
        return en_iyi

    def _komsu_olustur(self, t: float, a: _Aday,
                       oyuncu_xz: Tuple[float, float]) -> KomsuDurumu:
        g = self._gecmis.get(a.cid)
        if g is None:
            g = _Gecmis(xz=a.xz, oyuncu_xz=oyuncu_xz, t=t, mesafe=a.mesafe)
            self._gecmis[a.cid] = g
        elif g.xz != a.xz or g.oyuncu_xz != oyuncu_xz:
            dt = t - g.t
            if dt > MAX_DT_S:
                g.kapanma_ms, g.n = None, 0
                g.xz, g.oyuncu_xz, g.t, g.mesafe = a.xz, oyuncu_xz, t, a.mesafe
            elif dt >= MIN_DT_S:
                ham = (g.mesafe - a.mesafe) / dt
                if abs(ham) > MAX_GORECELI_HIZ_MS:
                    g.kapanma_ms, g.n = None, 0
                else:
                    g.kapanma_ms = (ham if g.kapanma_ms is None
                                    else EMA_ALFA * ham + (1 - EMA_ALFA) * g.kapanma_ms)
                    g.n += 1
                g.xz, g.oyuncu_xz, g.t, g.mesafe = a.xz, oyuncu_xz, t, a.mesafe

        yas_ms = max(0.0, (t - g.t) * 1000.0)
        kap_kmh: Optional[float] = None
        ttc: Optional[float] = None
        if g.kapanma_ms is not None and g.n >= 1 and yas_ms <= VERI_ESKI_MS:
            kap_kmh = g.kapanma_ms * 3.6
            if kap_kmh >= self.esik["min_kapanma_kmh"]:
                bosluk = max(a.mesafe - ARAC_UZUNLUK_M, 0.0)
                ttc = bosluk / g.kapanma_ms
        if g.n >= 3 and yas_ms <= 300.0:
            guven = "yuksek"
        elif g.n >= 1 and yas_ms <= VERI_ESKI_MS:
            guven = "orta"
        else:
            guven = "dusuk"
        return KomsuDurumu(car_id=a.cid, boyuna_m=a.boy, yanal_m=a.yan,
                           mesafe_m=a.mesafe, spline_farki=None,
                           kapanma_kmh=kap_kmh, ttc_s=ttc,
                           veri_yasi_ms=yas_ms, guven=guven)

    def _yan_yana_bul(self, on: Optional[KomsuDurumu],
                      arka: Optional[KomsuDurumu]) -> Tuple[bool, str]:
        en_iyi = None
        for k in (on, arka):
            if k is None:
                continue
            if (abs(k.boyuna_m) <= self.esik["yan_yana_boyuna_m"]
                    and abs(k.yanal_m) <= self.esik["komsu_m"]):
                if en_iyi is None or abs(k.boyuna_m) < abs(en_iyi.boyuna_m):
                    en_iyi = k
        if en_iyi is None:
            return False, "yok"
        if en_iyi.yanal_m > 0:
            return True, "sag"
        if en_iyi.yanal_m < 0:
            return True, "sol"
        return True, "orta"


_YOK = object()


def _anahtar(k: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def _sozluk(obj: Any) -> Dict[Any, Any]:
    if isinstance(obj, dict):
        return obj
    try:
        if hasattr(obj, "_asdict"):
            return dict(obj._asdict())
        if is_dataclass(obj) and not isinstance(obj, type):
            return {f: getattr(obj, f) for f in obj.__dataclass_fields__}
        if hasattr(obj, "__dict__"):
            return dict(vars(obj))
    except Exception:
        return {}
    return {}


def _kaynaklar(tum: Any) -> Dict[str, Dict[Any, Any]]:
    ust = _sozluk(tum)
    sonuc: Dict[str, Dict[Any, Any]] = {"top": ust}
    for k, v in ust.items():
        a = _anahtar(k)
        if a in ("physics", "graphics", "static", "session"):
            s = _sozluk(v)
            if s:
                sonuc[a] = s
    return sonuc


def _ara(kaynaklar: Dict[str, Dict[Any, Any]], adaylar: Tuple[str, ...],
         tercih: Tuple[str, ...] = ("graphics", "physics", "static", "session", "top")) -> Any:
    for ad in tercih:
        s = kaynaklar.get(ad)
        if not s:
            continue
        anah = {_anahtar(k): v for k, v in s.items()}
        for a in adaylar:
            if a in anah:
                return anah[a]
    return _YOK


def reader_to_girdi(tum: Any, zaman: Optional[float] = None) -> Tuple[TrackerGirdi, List[str]]:
    eksik: List[str] = []
    try:
        k = _kaynaklar(tum)

        def al(ad: str, adaylar: Tuple[str, ...], zorunlu: bool = False,
               tercih: Tuple[str, ...] = ("graphics", "physics", "static", "session", "top")) -> Any:
            v = _ara(k, adaylar, tercih)
            if v is _YOK:
                if zorunlu:
                    eksik.append(ad)
                return None
            return v

        pid = al("player_car_id", ("playercarid",), True)
        cid = al("car_id", ("carid", "carids"), True)
        koord = al("car_coordinates", ("carcoordinates", "carcoords"), True)
        ac = al("active_cars", ("activecars",))
        yz = al("pist_yuzdesi", ("normalizedcarposition",))
        sira = al("sira", ("position", "carposition"))
        tur = al("tur", ("completedlaps", "completedlap"))
        hd = al("heading", ("heading",), tercih=("physics", "graphics", "top"))
        hiz = al("hiz_kmh", ("speedkmh", "speedkph"), tercih=("physics", "graphics", "top"))
        pl = al("pit_lane", ("isinpitlane",))
        pt = al("pit", ("isinpit",))
        pk = al("packet_id", ("packetid",))

        girdi = TrackerGirdi(
            zaman=zaman if zaman is not None else time.monotonic(),
            packet_id=_int_ya_da_none(pk),
            player_car_id=_int_ya_da_none(pid),
            car_ids=list(cid) if isinstance(cid, (list, tuple)) else [],
            koordinatlar=list(koord) if isinstance(koord, (list, tuple)) else [],
            active_cars=_int_ya_da_none(ac),
            pist_yuzdesi=_float_ya_da_none(yz),
            sira=_int_ya_da_none(sira),
            tur=_int_ya_da_none(tur),
            hiz_kmh=_float_ya_da_none(hiz),
            heading=_float_ya_da_none(hd),
            pitte_mi=bool(pl) or bool(pt),
        )
        if cid is not None and not isinstance(cid, (list, tuple)) and "car_id" not in eksik:
            eksik.append("car_id(liste_degil)")
        if koord is not None and not isinstance(koord, (list, tuple)) and "car_coordinates" not in eksik:
            eksik.append("car_coordinates(liste_degil)")
        return girdi, eksik
    except Exception as e:
        LOG.exception("adaptor hatasi")
        return TrackerGirdi(zaman=time.monotonic()), ["adaptor_hatasi:" + type(e).__name__]


def _okuyucu_yukle() -> Any:
    try:
        import acc_shared_memory_reader as m
        return m
    except ImportError:
        pass
    if str(PROJE_KOKU) not in sys.path:
        sys.path.insert(0, str(PROJE_KOKU))
    try:
        from modules.acc import acc_shared_memory_reader as m
        return m
    except ImportError as e:
        print("HATA: acc_shared_memory_reader iceri aktarilamadi:", e)
        return None


def _tumunu_oku(m: Any) -> Any:
    f = getattr(m, "read_all", None)
    if f is None:
        raise RuntimeError("reader'da read_all bulunamadi")
    try:
        return f()
    except TypeError:
        ayar = m.acc_ayar_yukle()
        return f(ayar)


def _poll_araligi_s() -> float:
    try:
        with open(PROJE_KOKU / "config" / "settings.json", "r", encoding="utf-8-sig") as f:
            a = json.load(f)
        ms = _float_ya_da_none(a.get("acc", {}).get("poll_interval_ms"))
        if ms is not None and 20 <= ms <= 1000:
            return ms / 1000.0
    except (OSError, ValueError, AttributeError):
        pass
    return 0.1


def _komsu_metni(k: Optional[KomsuDurumu]) -> str:
    if k is None:
        return "yok"
    kap = "?" if k.kapanma_kmh is None else f"{k.kapanma_kmh:+.0f}km/h"
    ttc = "-" if k.ttc_s is None else f"{k.ttc_s:.1f}s"
    return (f"id{k.car_id} boy{k.boyuna_m:+.1f}m yan{k.yanal_m:+.1f}m "
            f"kap{kap} ttc{ttc} [{k.guven}]")


def _durum_satiri(d: TakipDurumu, gecen: float) -> str:
    if not d.gecerli:
        return f"[{gecen:5.1f}s] GECERSIZ: {d.neden}"
    yon = d.yon_kaynagi
    if d.yon_farki_derece is not None:
        yon += f"(fark {d.yon_farki_derece:.0f}d)"
    hiz = "?" if d.hiz_kmh is None else f"{d.hiz_kmh:.0f}"
    return (f"[{gecen:5.1f}s] sira={d.sira} hiz={hiz} yon={yon} "
            f"| ON: {_komsu_metni(d.on)} | ARKA: {_komsu_metni(d.arka)} "
            f"| yan_yana={d.yan_yana_taraf} | {d.neden}")


def izle(sure_s: float) -> int:
    m = _okuyucu_yukle()
    if m is None:
        return 2
    takipci = OyuncuTakipci(esik_yukle())
    aralik = _poll_araligi_s()
    t0 = time.monotonic()
    bitis = t0 + max(1.0, sure_s)
    son_yaz = 0.0
    gorulen: set = set()
    while time.monotonic() < bitis:
        try:
            tum = _tumunu_oku(m)
        except Exception as e:
            print("Okuma hatasi:", type(e).__name__, e)
            time.sleep(aralik)
            continue
        k = _kaynaklar(tum)
        canli = _ara(k, ("canli",), ("top",))
        if canli is False:
            if time.monotonic() - son_yaz >= 1.0:
                print("ACC canli degil (canli=False); bekleniyor...")
                son_yaz = time.monotonic()
            time.sleep(aralik)
            continue
        girdi, eksik = reader_to_girdi(tum)
        if eksik:
            print("EKSIK ALANLAR:", eksik)
            print("Reader yapisini gormek icin: python -m modules.acc.acc_player_tracker --dump")
            return 3
        d = takipci.guncelle(girdi)
        for u in d.uyarilar:
            if u not in gorulen:
                gorulen.add(u)
                print("UYARI:", u)
        simdi = time.monotonic()
        if simdi - son_yaz >= 0.5:
            print(_durum_satiri(d, simdi - t0))
            son_yaz = simdi
        time.sleep(aralik)
    print("WATCH BITTI")
    return 0


def _kisa(v: Any) -> str:
    if isinstance(v, (list, tuple)):
        ilk = repr(v[0])[:50] if len(v) else ""
        return f"{type(v).__name__}[len={len(v)}] ilk={ilk}"
    return repr(v)[:80]


def dump() -> int:
    m = _okuyucu_yukle()
    if m is None:
        return 2
    try:
        tum = _tumunu_oku(m)
    except Exception as e:
        print("Okuma hatasi:", type(e).__name__, e)
        return 3
    for ad, s in _kaynaklar(tum).items():
        print(f"[{ad}]")
        for anah, v in s.items():
            print(f"  {anah}: {_kisa(v)}")
    return 0


class _Kontrol:
    def __init__(self) -> None:
        self.say = 0
        self.hata = 0

    def __call__(self, ad: str, kosul: bool, ayrinti: Any = "") -> None:
        self.say += 1
        if kosul:
            print(f"  [OK]   {ad}")
        else:
            self.hata += 1
            print(f"  [HATA] {ad} {ayrinti}")


def _yakin(a: Optional[float], b: float, tol: float = 0.05) -> bool:
    return a is not None and abs(a - b) <= tol


def _girdi(t: float, ox: float = 0.0, oz: float = 0.0, heading: float = 0.0,
           diger: Optional[Dict[int, tuple]] = None, hiz: float = 100.0,
           pid: int = 1000, pitte: bool = False, pist: float = 0.5,
           y: float = 450.0, active: Optional[int] = None) -> TrackerGirdi:
    ids = [pid]
    koord: List[Any] = [[ox, y, oz]]
    for cid, v in (diger or {}).items():
        ids.append(cid)
        koord.append([v[0], v[2] if len(v) > 2 else y, v[1]])
    return TrackerGirdi(zaman=t, packet_id=int(t * 1000), player_car_id=pid,
                        car_ids=ids, koordinatlar=koord,
                        active_cars=active if active is not None else len(ids),
                        pist_yuzdesi=pist, sira=3, tur=1, hiz_kmh=hiz,
                        heading=heading, pitte_mi=pitte)


def selftest() -> int:
    c = _Kontrol()
    yeni = lambda: OyuncuTakipci(dict(_VARSAYILAN_ESIK))  # noqa: E731
    print("== TRACKER SELFTEST (sentetik veri) ==")

    d = yeni().guncelle(_girdi(0, diger={1001: (0, 20)}))
    c("1 onde arac: on bulundu", d.on is not None and d.on.car_id == 1001, d.neden)
    c("1 boyuna=20 yanal=0", d.on is not None and _yakin(d.on.boyuna_m, 20) and _yakin(d.on.yanal_m, 0))
    c("1 arka yok", d.arka is None)

    d = yeni().guncelle(_girdi(0, diger={1002: (0, -15)}))
    c("2 arkada arac: arka bulundu", d.arka is not None and _yakin(d.arka.boyuna_m, -15))
    c("2 on yok", d.on is None)

    d = yeni().guncelle(_girdi(0, heading=-math.pi / 2, diger={1003: (0, -3)}))
    c("3 yan yana True", d.yan_yana is True, d.yan_yana_taraf)
    c("3 taraf=sag (kod kabulu)", d.yan_yana_taraf == "sag", d.yan_yana_taraf)

    t4 = yeni()
    d = None
    for i, z in enumerate((-30, -25, -20, -15, -10)):
        d = t4.guncelle(_girdi(i * 0.5, diger={2: (0, z)}))
        if i == 0:
            c("4 ilk ornekte kapanma yok", d.arka is not None and d.arka.kapanma_kmh is None)
    c("4 kapanma ~36 km/h", d.arka is not None and _yakin(d.arka.kapanma_kmh, 36.0, 0.5),
      d.arka.kapanma_kmh if d.arka else None)
    c("4 TTC ~0.53 s", d.arka is not None and _yakin(d.arka.ttc_s, 0.53, 0.05),
      d.arka.ttc_s if d.arka else None)
    c("4 guven=yuksek", d.arka is not None and d.arka.guven == "yuksek")

    d2 = t4.guncelle(_girdi(3.5, diger={2: (0, -10)}))
    c("14 eski veri: yas ~1500 ms", d2.arka is not None and _yakin(d2.arka.veri_yasi_ms, 1500, 1))
    c("14 eski veri: guven=dusuk, kapanma None",
      d2.arka is not None and d2.arka.guven == "dusuk" and d2.arka.kapanma_kmh is None)

    t5 = yeni()
    for i, z in enumerate((-10, -15, -20)):
        d = t5.guncelle(_girdi(i * 0.5, diger={3: (0, z)}))
    c("5 uzaklasan: kapanma ~-36", d.arka is not None and _yakin(d.arka.kapanma_kmh, -36.0, 0.5))
    c("5 uzaklasan: TTC None", d.arka is not None and d.arka.ttc_s is None)

    d = yeni().guncelle(_girdi(0))
    c("6 tek arac: gecerli, komsu yok",
      d.gecerli and d.veri_yeterli and d.on is None and d.arka is None)

    d = yeni().guncelle(_girdi(0, pid=1000, diger={5: (0, 10)}))
    bozuk = _girdi(0, diger={5: (0, 10)})
    bozuk.player_car_id = 999
    d = yeni().guncelle(bozuk)
    c("7 oyuncu listede yok -> gecerli False", d.gecerli is False and d.neden == "oyuncu_listede_yok")
    d = yeni().guncelle(TrackerGirdi(zaman=0.0))
    c("7 bos girdi -> gecerli False", d.gecerli is False)
    d = yeni().guncelle(_girdi(0, diger={6: (float("nan"), 5), 7: (0, 12)}))
    c("7 NaN komsu yok sayilir, gecerli komsu bulunur", d.on is not None and d.on.car_id == 7)

    d = yeni().guncelle(_girdi(0, diger={8: (0, 100), 9: (20, 5), 10: (0, 10, 470.0)}))
    c("8 menzil disi, yanal ve dikey filtre: komsu yok", d.on is None and d.arka is None,
      (d.on, d.arka))

    t9 = yeni()
    t9.guncelle(_girdi(0.0, ox=0, oz=0, heading=0.0, hiz=100))
    d = t9.guncelle(_girdi(0.1, ox=3, oz=0, heading=0.0, hiz=100, diger={5: (23, 0)}))
    c("9 heading uyumsuz: kaynak=hareket", d.yon_kaynagi == "hareket", d.yon_kaynagi)
    c("9 uyari var", "HEADING_HAREKETLE_UYUMSUZ" in d.uyarilar)
    c("9 hareket yonuyle onde arac bulundu", d.on is not None and d.on.car_id == 5)
    t9b = yeni()
    t9b.guncelle(_girdi(0.0, heading=-math.pi / 2, hiz=100))
    d = t9b.guncelle(_girdi(0.1, ox=3, heading=-math.pi / 2, hiz=100))
    c("9b heading uyumlu: kaynak=heading, uyari yok", d.yon_kaynagi == "heading" and not d.uyarilar,
      (d.yon_kaynagi, d.uyarilar))

    t10 = yeni()
    d = t10.guncelle(_girdi(0.0, diger={11: (0, 20)}))
    c("10 ilk on=11", d.on is not None and d.on.car_id == 11)
    d = t10.guncelle(_girdi(0.1, diger={11: (0, 20), 12: (0, 18)}))
    c("10 kucuk farkta eski komsu korunur", d.on is not None and d.on.car_id == 11)
    d = t10.guncelle(_girdi(0.2, diger={11: (0, 20), 12: (0, 12)}))
    c("10 buyuk farkta yeni komsuya gecilir", d.on is not None and d.on.car_id == 12)

    t11 = yeni()
    d = t11.guncelle(_girdi(0.0, diger={21: (3, 1)}))
    c("11 boyuna +1 -> on", d.on is not None and d.on.car_id == 21)
    d = t11.guncelle(_girdi(0.1, diger={21: (3, -1)}))
    c("11 boyuna -1 -> hala on (histerezis)", d.on is not None and d.arka is None)
    d = t11.guncelle(_girdi(0.2, diger={21: (3, -3)}))
    c("11 boyuna -3 -> arka", d.arka is not None and d.on is None and d.yan_yana)

    d = yeni().guncelle(_girdi(0, pitte=True, diger={30: (0, 20)}))
    c("12 pitte: komsu yok, veri_yeterli False",
      d.gecerli and not d.veri_yeterli and d.on is None and d.neden == "oyuncu_pitte")

    t13 = yeni()
    t13.guncelle(_girdi(0.00, diger={40: (0, 50)}))
    d = t13.guncelle(_girdi(0.05, diger={40: (0, 10)}))
    c("13 isinlanma: kapanma None", d.on is not None and d.on.kapanma_kmh is None)
    d = t13.guncelle(_girdi(0.55, diger={40: (0, 5)}))
    c("13 sonra toparlanir: ~36 km/h", d.on is not None and _yakin(d.on.kapanma_kmh, 36.0, 0.5),
      d.on.kapanma_kmh if d.on else None)

    tum = {
        "canli": True,
        "physics": {"speedKmh": 150.0, "heading": -0.11159000545740128, "packetId": 5},
        "graphics": {
            "playerCarId": 1007,
            "carId": [1008, 1009, 1007, 1010, 1001],
            "carCoordinates": [[1164.95, 434.14, 1893.14], [1696.29, 460.46, 1761.80],
                               [1543.84, 433.47, 447.44], [1142.47, 444.43, 392.40],
                               [1429.60, 444.76, 1537.71]],
            "normalizedCarPosition": 0.16241663694381714,
            "activeCars": 5, "isInPitLane": False, "packetId": 77,
        },
        "static": {},
    }
    g, eksik = reader_to_girdi(tum, 1.0)
    c("15 adaptor: eksik yok", eksik == [], eksik)
    c("15 adaptor: alanlar dogru",
      g.player_car_id == 1007 and len(g.car_ids) == 5 and g.packet_id == 77
      and _yakin(g.heading, -0.11159, 1e-4) and _yakin(g.hiz_kmh, 150.0))
    d = yeni().guncelle(g)
    c("15 gercek veri sekli: gecerli, komsu uzak -> yok",
      d.gecerli and d.car_id == 1007 and d.on is None and d.arka is None, d.neden)
    _, eksik = reader_to_girdi({})
    c("15 bos reader cikti: eksik alanlar bildirilir", len(eksik) >= 3, eksik)

    gi = _girdi(0, diger={50: (0, 5), 51: (0, 10)}, active=2)
    d = yeni().guncelle(gi)
    c("16 active_cars=2: 3. arac yok sayilir", d.on is not None and d.on.car_id == 50
      and d.arka is None)
    gi = _girdi(0, diger={51: (0, 10)}, active=1)
    d = yeni().guncelle(gi)
    c("16 active_cars=1: komsu yok", d.on is None)

    t17 = yeni()
    d1 = t17.guncelle(_girdi(0.0, pist=0.999, diger={60: (0, 20)}))
    d2 = t17.guncelle(_girdi(0.1, pist=0.001, diger={60: (0, 20)}))
    c("17 pist yuzdesi sarmasi: komsu sabit",
      d1.on is not None and d2.on is not None and d1.on.car_id == d2.on.car_id
      and _yakin(d2.pist_yuzdesi, 0.001, 1e-9))

    d = yeni().guncelle(_girdi(0, heading=90.0, diger={70: (0, 10)}))
    c("19 heading=90 (derece suphesi): uyari + yon bilinmiyor",
      "HEADING_BIRIM_SUPHELI" in d.uyarilar and not d.veri_yeterli
      and d.neden == "yon_bilinmiyor" and d.on is None, (d.uyarilar, d.neden))

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.json"
        p.write_text(json.dumps({"_aciklama": "x", "izleme": {"ilgi_mesafesi_m": 80},
                                 "relative_speed": {"min_kapanma_kmh": -5}}), encoding="utf-8")
        e = esik_yukle(p)
        c("18 esik: gecerli deger okunur", e["ilgi_mesafesi_m"] == 80.0)
        c("18 esik: negatif deger reddedilir", e["min_kapanma_kmh"] == 3.0)
        c("18 esik: dosya yok -> varsayilan", esik_yukle(Path(td) / "yok.json") == _VARSAYILAN_ESIK)

    if c.hata == 0:
        print(f"SELFTEST TAMAM ({c.say} kontrol)")
        return 0
    print(f"SELFTEST BASARISIZ ({c.hata}/{c.say} hata)")
    return 1


def badtest() -> int:
    c = _Kontrol()
    print("== TRACKER BADTEST (bozuk girdi) ==")
    nan, inf = float("nan"), float("inf")
    vakalar = [
        (None, False),
        ("x", False),
        (5, False),
        (TrackerGirdi(zaman=nan), False),
        (TrackerGirdi(zaman=0.0, player_car_id="abc", car_ids=None, koordinatlar=None), False),
        (TrackerGirdi(zaman=1.0, player_car_id=1, car_ids=[1], koordinatlar=[["a", "b", "c"]]), False),
        (TrackerGirdi(zaman=2.0, player_car_id=1, car_ids=[1, 2],
                      koordinatlar=[[inf, 1, 1], [1, 2, 3]]), False),
        (TrackerGirdi(zaman=3.0, player_car_id=1, car_ids={"a": 1}, koordinatlar={"a": [1, 2, 3]}), False),
        (TrackerGirdi(zaman=4.0, player_car_id=1, car_ids=[1], koordinatlar=[[1, 2]]), False),
        (TrackerGirdi(zaman=5.0, player_car_id=1, car_ids=[1, 2],
                      koordinatlar=[[1, 2, 3], [1e308, 1e308, 1e308]],
                      heading="abc", active_cars=-5), True),
        (TrackerGirdi(zaman=6.0, player_car_id=1, car_ids=[1], koordinatlar=[[0, 0, 0]]), False),
    ]
    tk = OyuncuTakipci(dict(_VARSAYILAN_ESIK))
    for i, (girdi, beklenen_gecerli) in enumerate(vakalar):
        try:
            d = tk.guncelle(girdi)
            ok = isinstance(d, TakipDurumu) and d.gecerli == beklenen_gecerli
            c(f"bad {i}: coker yok, gecerli={beklenen_gecerli}", ok, (d.gecerli, d.neden))
        except Exception as e:
            c(f"bad {i}: istisna FIRLATTI", False, repr(e))

    for i, x in enumerate([None, [], "abc", 5, {"physics": 5}, {"graphics": {"car_id": "abc"}}]):
        try:
            g, eksik = reader_to_girdi(x)
            d = OyuncuTakipci(dict(_VARSAYILAN_ESIK)).guncelle(g)
            c(f"bad adaptor {i}: coker yok, eksik bildirilir",
              isinstance(g, TrackerGirdi) and len(eksik) > 0 and d.gecerli is False, eksik)
        except Exception as e:
            c(f"bad adaptor {i}: istisna FIRLATTI", False, repr(e))

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
    ap = argparse.ArgumentParser(description="ACC oyuncu/komsu arac takipcisi")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--selftest", action="store_true", help="ACC kapali, sentetik testler")
    g.add_argument("--badtest", action="store_true", help="ACC kapali, bozuk girdi testi")
    g.add_argument("--watch", type=float, metavar="N", help="ACC acik, N saniye canli izle")
    g.add_argument("--dump", action="store_true", help="ACC acik, reader cikti yapisini goster")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.selftest:
        return selftest()
    if a.badtest:
        return badtest()
    if a.watch is not None:
        return izle(a.watch)
    return dump()


if __name__ == "__main__":
    sys.exit(main())