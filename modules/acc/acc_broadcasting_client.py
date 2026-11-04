# -*- coding: utf-8 -*-
"""
modules/acc/acc_broadcasting_client.py

ACC Personal Race Assistant - Broadcasting API istemcisi (UDP / binary, protokol v4).

NOT (ceza / bayrak): REALTIME_CAR_UPDATE paketinde arac basina ceza ve bayrak YOKTUR.
  - Ceza: yalnizca BROADCASTING_EVENT (PENALTY_COMM_MSG) ile, olay tabanli ve kismen gelir.
    CarUpdate.penalty son ceza mesajidir; ceza listesi/suresi degildir.
  - Bayrak: Broadcasting API sari/mavi bayrak vermez. Yalnizca oturum fazi (REALTIME_UPDATE)
    ve GREEN_FLAG / SESSION_OVER olaylari gelir. Bayrak icin Shared Memory graphics.flag kullanilir.

Yalnizca yerel (127.0.0.1) UDP; internet yok, tus gonderimi yok, kayit yok.
Protokol ayrintilari resmi ornek istemciden HAFIZAYLA yazilmistir; canli --watch ile dogrulanmalidir.
"""
from __future__ import annotations

import argparse
import copy
import ipaddress
import json
import logging
import math
import queue
import socket
import struct
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Deque, Dict, Iterator, List, Optional, Tuple

PROJE_KOKU = Path(__file__).resolve().parents[2]
LOG = logging.getLogger("acc_broadcasting_client")

PROTOKOL_SURUMU = 4
OUT_KAYIT, OUT_KAYIT_SIL, OUT_ENTRY_LIST, OUT_TRACK_DATA = 1, 9, 10, 11
IN_KAYIT_SONUCU, IN_OTURUM, IN_ARAC, IN_ENTRY_LIST, IN_PIST, IN_ENTRY_CAR, IN_OLAY = 1, 2, 3, 4, 5, 6, 7
_INT_MAX = 2147483647
MAX_PAKET = 65535

LOKASYON = {0: "NONE", 1: "TRACK", 2: "PITLANE", 3: "PIT_ENTRY", 4: "PIT_EXIT"}
FAZ = {0: "NONE", 1: "STARTING", 2: "PRE_FORMATION", 3: "FORMATION_LAP", 4: "PRE_SESSION",
       5: "SESSION", 6: "SESSION_OVER", 7: "POST_SESSION", 8: "RESULT_UI"}
OTURUM_TIPI = {0: "PRACTICE", 4: "QUALIFYING", 9: "SUPERPOLE", 10: "RACE", 11: "HOTLAP",
               12: "HOTSTINT", 13: "HOTLAP_SUPERPOLE", 14: "REPLAY"}
OLAY_TIPI = {0: "NONE", 1: "GREEN_FLAG", 2: "SESSION_OVER", 3: "PENALTY_COMM_MSG", 4: "ACCIDENT",
             5: "LAP_COMPLETED", 6: "BEST_SESSION_LAP", 7: "BEST_PERSONAL_LAP"}
# DOGRULANMADI (hafizadan): bilinmeyen id icin "model_<id>" doner; car_model_id her zaman dogru ham degerdir.
ARAC_MODELI = {
    0: "Porsche 991 GT3 R", 1: "Mercedes-AMG GT3", 2: "Ferrari 488 GT3", 3: "Audi R8 LMS",
    4: "Lamborghini Huracan GT3", 5: "McLaren 650S GT3", 6: "Nissan GT-R Nismo GT3 2018",
    7: "BMW M6 GT3", 8: "Bentley Continental GT3 2018", 9: "Porsche 991 II GT3 Cup",
    10: "Nissan GT-R Nismo GT3 2015", 11: "Bentley Continental GT3 2015",
    12: "Aston Martin V12 Vantage GT3", 13: "Reiter Engineering R-EX GT3", 14: "Emil Frey Jaguar G3",
    15: "Lexus RC F GT3", 16: "Lamborghini Huracan GT3 Evo", 17: "Honda NSX GT3",
    18: "Lamborghini Huracan ST", 19: "Audi R8 LMS Evo", 20: "AMR V8 Vantage",
    21: "Honda NSX GT3 Evo", 22: "McLaren 720S GT3", 23: "Porsche 991 II GT3 R",
    24: "Ferrari 488 GT3 Evo", 25: "Mercedes-AMG GT3 2020", 26: "Ferrari 488 Challenge Evo",
    27: "BMW M2 CS Racing", 28: "Porsche 992 GT3 Cup", 29: "Lamborghini Huracan ST Evo2",
    30: "BMW M4 GT3", 31: "Audi R8 LMS GT3 Evo II", 32: "Ferrari 296 GT3",
    33: "Lamborghini Huracan GT3 Evo2", 34: "Porsche 992 GT3 R", 35: "McLaren 720S GT3 Evo",
    36: "Ford Mustang GT3",
}

_VARSAYILAN: Dict[str, Any] = {
    "host": "127.0.0.1", "port": 9000, "reconnect_max": 3, "realtime_timeout_s": 5.0,
    "display_name": "ACC Personal Race Assistant", "connection_password": "",
    "command_password": "", "update_interval_ms": 250,
}


def _int_ya_da_none(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    return None


def _sayi_ya_da_none(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def ayar_birlestir(bolum: Any) -> Dict[str, Any]:
    a = dict(_VARSAYILAN)
    if not isinstance(bolum, dict):
        return a
    for k in ("host", "display_name", "connection_password", "command_password"):
        v = bolum.get(k)
        if isinstance(v, str):
            a[k] = v.strip() if k == "host" else v
    p = _int_ya_da_none(bolum.get("port"))
    if p is not None:
        a["port"] = p                       # aralik disi olabilir; connect() reddeder
    r = _int_ya_da_none(bolum.get("reconnect_max"))
    if r is not None:
        a["reconnect_max"] = min(10, max(1, r))
    u = _int_ya_da_none(bolum.get("update_interval_ms"))
    if u is not None:
        a["update_interval_ms"] = min(5000, max(50, u))
    t = _sayi_ya_da_none(bolum.get("realtime_timeout_s"))
    if t is not None:
        a["realtime_timeout_s"] = min(60.0, max(0.2, t))
    return a


def ayar_yukle(yol: Optional[Path] = None) -> Dict[str, Any]:
    yol = Path(yol) if yol else PROJE_KOKU / "config" / "settings.json"
    try:
        with open(yol, "r", encoding="utf-8-sig") as f:
            ham = json.load(f)
    except (OSError, ValueError) as e:
        LOG.warning("settings.json okunamadi (%s); broadcasting varsayilanlari kullaniliyor.", e)
        return dict(_VARSAYILAN)
    bolum = ham.get("broadcasting") if isinstance(ham, dict) else None
    if not isinstance(bolum, dict):
        LOG.warning("settings.json icinde 'broadcasting' bolumu yok; varsayilanlar kullaniliyor.")
        return dict(_VARSAYILAN)
    return ayar_birlestir(bolum)


# ----------------------------------------------------------------------------- protokol

class ProtocolError(ValueError):
    pass


class _Okuyucu:
    def __init__(self, data: Any, pos: int = 0) -> None:
        self.b = bytes(data)
        self.p = pos

    def _al(self, fmt: str) -> Any:
        n = struct.calcsize(fmt)
        if self.p + n > len(self.b):
            raise ProtocolError("paket kisa")
        v = struct.unpack_from(fmt, self.b, self.p)[0]
        self.p += n
        return v

    def u8(self) -> int: return self._al("<B")
    def u16(self) -> int: return self._al("<H")
    def i32(self) -> int: return self._al("<i")
    def f32(self) -> float: return self._al("<f")

    def string(self) -> str:
        n = self.u16()
        if self.p + n > len(self.b):
            raise ProtocolError("string kisa")
        raw = self.b[self.p:self.p + n]
        self.p += n
        return raw.decode("utf-8", errors="replace")

    def kalan(self) -> int:
        return len(self.b) - self.p


@dataclass
class KayitSonucu:
    connection_id: int
    basarili: bool
    salt_okunur: bool
    hata: str


@dataclass
class LapBilgi:
    sure_ms: Optional[int]
    car_id: int
    surucu_index: int
    splitler: List[Optional[int]]
    gecersiz: bool
    best_icin_gecerli: bool
    outlap: bool
    inlap: bool


@dataclass
class OturumGuncelleme:
    event_index: int
    session_index: int
    session_tipi: int
    session_tipi_adi: str
    faz: int
    faz_adi: str
    session_zamani_ms: float
    session_bitis_ms: float
    odak_arac_id: int
    kamera_seti: str
    kamera: str
    replay: bool
    gun_saati_ms: float
    hava_c: int
    pist_c: int
    yagmur: float
    islaklik: float
    en_iyi_tur: Optional[LapBilgi]
    t: float = 0.0


@dataclass
class SurucuBilgi:
    ad: str
    soyad: str
    kisa_ad: str
    kategori: int

    def tam_ad(self) -> str:
        s = f"{self.ad} {self.soyad}".strip()
        return s or self.kisa_ad


@dataclass
class GirisKaydi:
    car_id: int
    model_id: int
    takim: str
    yaris_no: int
    kupa_kategorisi: int
    aktif_surucu_index: int
    suruculer: List[SurucuBilgi]


@dataclass
class PistBilgisi:
    ad: str
    pist_id: int
    uzunluk_m: int
    kamera_setleri: Optional[Dict[str, List[str]]] = None
    hud_sayfalari: Optional[List[str]] = None
    ham: bytes = b""


@dataclass
class YayinOlayi:
    tip: int
    tip_adi: str
    mesaj: str
    sure_ms: int
    car_id: int
    t: float = 0.0


@dataclass
class CarUpdate:
    car_id: int
    driver_index: int = 0
    driver_count: int = 0
    gear: int = 0
    world_x: float = 0.0
    world_y: float = 0.0
    yaw: float = 0.0
    car_location: int = 0
    location_name: str = "NONE"
    speed_kmh: int = 0
    position: int = 0            # resmi P/Q/R sirasi (1 tabanli) - get_position bunu doner
    cup_position: int = 0
    track_position: int = 0
    spline: float = 0.0
    delta_ms: int = 0
    laps: int = 0
    best_lap: Optional[LapBilgi] = None
    last_lap: Optional[LapBilgi] = None
    current_lap: Optional[LapBilgi] = None
    is_in_pit: bool = False       # car_location == PITLANE
    is_in_pit_lane: bool = False  # PITLANE / PIT_ENTRY / PIT_EXIT
    # entry list eslesmesi (carId ile):
    driver_name: Optional[str] = None
    car_model: Optional[str] = None
    car_model_id: Optional[int] = None
    race_number: Optional[int] = None
    team_name: Optional[str] = None
    penalty: Optional[str] = None  # OLAY TABANLI: son PENALTY_COMM_MSG metni
    t: float = 0.0                 # alim zamani (time.monotonic)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _ps(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack("<H", len(b)) + b


def kayit_paketi(ad: str, sifre: str, aralik_ms: int, komut_sifresi: str) -> bytes:
    return (struct.pack("<BB", OUT_KAYIT, PROTOKOL_SURUMU) + _ps(ad) + _ps(sifre)
            + struct.pack("<i", int(aralik_ms)) + _ps(komut_sifresi))


def kayit_sil_paketi(conn_id: int) -> bytes:
    return struct.pack("<Bi", OUT_KAYIT_SIL, int(conn_id))


def entry_list_istek_paketi(conn_id: int) -> bytes:
    return struct.pack("<Bi", OUT_ENTRY_LIST, int(conn_id))


def track_data_istek_paketi(conn_id: int) -> bytes:
    return struct.pack("<Bi", OUT_TRACK_DATA, int(conn_id))


def _lap_oku(r: _Okuyucu) -> LapBilgi:
    ms = r.i32()
    car = r.u16()
    drv = r.u16()
    n = r.u8()
    splits: List[Optional[int]] = []
    for _ in range(n):
        v = r.i32()
        splits.append(None if v == _INT_MAX else v)
    inv = r.u8() > 0
    vb = r.u8() > 0
    out = r.u8() > 0
    inn = r.u8() > 0
    return LapBilgi(None if (ms == _INT_MAX or ms < 0) else ms, car, drv, splits, inv, vb, out, inn)


class Cozumleyici:
    """Paket ayristirici. car_layout: laps alaninin yeri ('A' = track_position'dan sonra,
    'B' = paket sonunda). Hafizadan yazildigi icin iki yerlesim denenir, skorla secilir."""

    def __init__(self) -> None:
        self._son_spline = {}
        self._spline_ret = {}

    def parse(self, data: Any) -> Tuple[int, Any]:
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ProtocolError("bytes degil")
        if len(data) > MAX_PAKET:
            raise ProtocolError("paket cok buyuk")
        r = _Okuyucu(data)
        tip = r.u8()
        if tip == IN_KAYIT_SONUCU:
            cid = r.i32()
            ok = r.u8() > 0
            ro = r.u8() == 0
            return tip, KayitSonucu(cid, ok, ro, r.string())
        if tip == IN_OTURUM:
            return tip, self._oturum(r)
        if tip == IN_ARAC:
            return tip, self._arac(r)
        if tip == IN_ENTRY_LIST:
            conn = r.i32()
            n = r.u16()
            return tip, (conn, [r.u16() for _ in range(n)])
        if tip == IN_PIST:
            r.i32()
            ad = r.string()
            pid = r.i32()
            metre = r.i32()
            sets = None
            huds = None
            try:
                if r.kalan() > 0:
                    sets = {}
                    for _ in range(r.u8()):
                        sn = r.string()
                        sets[sn] = [r.string() for _ in range(r.u8())]
                    huds = [r.string() for _ in range(r.u8())]
            except Exception:
                sets, huds = None, None
            return tip, PistBilgisi(ad, pid, metre, sets, huds, bytes(data))
        if tip == IN_ENTRY_CAR:
            return tip, self._giris(r)
        if tip == IN_OLAY:
            et = r.u8()
            msg = r.string()
            ms = r.i32()
            cid = r.i32()
            return tip, YayinOlayi(et, OLAY_TIPI.get(et, f"EVENT_{et}"), msg, ms, cid, time.monotonic())
        return tip, None

    @staticmethod
    def _oturum(r: _Okuyucu) -> OturumGuncelleme:
        ev, si, st, ph = r.u16(), r.u16(), r.u8(), r.u8()
        stime, send, odak = r.f32(), r.f32(), r.i32()
        cs, cam = r.string(), r.string()
        _hud = r.string()  # CurrentHudPage (DOGRULANMADI)
        replay = r.u8() > 0
        if replay:
            r.f32()
            r.f32()
        tod = r.f32()
        amb, trk = r.u8(), r.u8()
        clouds, rain, wet = r.u8() / 10.0, r.u8() / 10.0, r.u8() / 10.0
        best = None
        try:
            best = _lap_oku(r)
        except ProtocolError:
            pass
        return OturumGuncelleme(ev, si, st, OTURUM_TIPI.get(st, f"TYPE_{st}"), ph, FAZ.get(ph, f"PHASE_{ph}"),
                                stime, send, odak, cs, cam, replay, tod, amb, trk, rain, wet, best,
                                time.monotonic())

    @staticmethod
    def _giris(r: _Okuyucu) -> GirisKaydi:
        cid, model = r.u16(), r.u8()
        takim = r.string()
        no, cup, cur, _nat, n = r.i32(), r.u8(), r.u8(), r.u16(), r.u8()
        suruculer = []
        for _ in range(n):
            f, l, s = r.string(), r.string(), r.string()
            kat = r.u8()
            r.u16()
            suruculer.append(SurucuBilgi(f, l, s, kat))
        return GirisKaydi(cid, model, takim, no, cup, cur, suruculer)

    def _arac(self, r: _Okuyucu) -> CarUpdate:
        car_id, drv, dcnt = r.u16(), r.u16(), r.u8()
        gear = r.u8() - 2
        wx, wy, yaw = r.f32(), r.f32(), r.f32()
        loc, kmh = r.u8(), r.u16()
        pos, cup, tp = r.u16(), r.u16(), r.u16()
        spline, laps, delta = r.f32(), r.u16(), r.i32()
        best, last, cur = _lap_oku(r), _lap_oku(r), _lap_oku(r)
        if r.kalan() != 0:
            raise ProtocolError(f"car update bayt uyusmazligi (kalan={r.kalan()})")
        if not math.isfinite(spline) or not (0.0 <= spline <= 1.0) or (spline != 0.0 and spline < 1e-6):
            raise ProtocolError(f"spline gecersiz: {spline!r}")
        if abs(delta) > 600000 or laps > 500:
            raise ProtocolError(f"delta/laps makul degil: {delta}/{laps}")
        for l in (best, last, cur):
            if l.sure_ms is not None and not (0 < l.sure_ms <= 3600000):
                raise ProtocolError(f"lap suresi makul degil: {l.sure_ms}")
        onceki = self._son_spline.get(car_id)
        if onceki is not None:
            fark = (spline - onceki) % 1.0
            if not (fark < 0.2 or fark > 0.995):
                self._spline_ret[car_id] = self._spline_ret.get(car_id, 0) + 1
                if self._spline_ret[car_id] >= 10:
                    self._son_spline.pop(car_id, None)
                    self._spline_ret[car_id] = 0
                raise ProtocolError(f"spline atlama {onceki:.4f}->{spline:.4f}")
        self._son_spline[car_id] = spline
        self._spline_ret[car_id] = 0
        return CarUpdate(car_id=car_id, driver_index=drv, driver_count=dcnt, gear=gear, world_x=wx,
                         world_y=wy, yaw=yaw, car_location=loc, location_name=LOKASYON.get(loc, f"LOC_{loc}"),
                         speed_kmh=kmh, position=pos, cup_position=cup, track_position=tp, spline=spline,
                         delta_ms=delta, laps=laps, best_lap=best, last_lap=last, current_lap=cur,
                         is_in_pit=(loc == 2), is_in_pit_lane=(loc in (2, 3, 4)), t=time.monotonic())


def parse_paket(data: Any) -> Tuple[int, Any]:
    return Cozumleyici().parse(data)


# ----------------------------------------------------------------------------- istemci

class BroadcastingClient:
    def __init__(self, ayar: Optional[Dict[str, Any]] = None) -> None:
        self.ayar = ayar_birlestir(ayar)
        self.baglandi = False
        self.son_hata = ""
        self.salt_okunur: Optional[bool] = None
        self.istatistik = {"paket": 0, "bozuk": 0, "car_update": 0, "yeniden_kayit": 0}
        self._sock: Optional[socket.socket] = None
        self._adres: Optional[Tuple[str, int]] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._conn_id: Optional[int] = None
        self._reddedildi = False
        self._coz = Cozumleyici()
        self._cars: Dict[int, CarUpdate] = {}
        self._entries: Dict[int, GirisKaydi] = {}
        self._penalty: Dict[int, str] = {}
        self._oturum: Optional[OturumGuncelleme] = None
        self._pist: Optional[PistBilgisi] = None
        self._olaylar: Deque[YayinOlayi] = deque(maxlen=200)
        self._q: "queue.Queue[CarUpdate]" = queue.Queue(maxsize=2000)
        self._son_entry_istek = 0.0

    # --- baglanti
    def _hedef(self) -> Tuple[Optional[Tuple[str, int]], str]:
        host, port = self.ayar["host"], self.ayar["port"]
        if not isinstance(port, int) or isinstance(port, bool) or not (1 <= port <= 65535):
            return None, "gecersiz_port"
        if host == "localhost":
            host = "127.0.0.1"
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return None, "gecersiz_host"
        if ip.version != 4 or not ip.is_loopback:
            return None, "yerel_olmayan_host (yalnizca 127.0.0.0/8)"
        return (host, port), ""

    def _soket_ac(self) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        s.settimeout(0.25)
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                s.ioctl(socket.SIO_UDP_CONNRESET, False)
            except (OSError, ValueError):
                pass
        self._sock = s

    def _soket_kapat(self) -> None:
        s, self._sock = self._sock, None
        if s is not None:
            try:
                s.close()
            except OSError:
                pass

    def _gonder(self, pkt: bytes) -> bool:
        s, a = self._sock, self._adres
        if s is None or a is None:
            return False
        try:
            s.sendto(pkt, a)
            return True
        except OSError as e:
            self.son_hata = f"gonderim_hatasi: {e}"
            return False

    def _kayit_dene(self) -> bool:
        a = self.ayar
        if not self._gonder(kayit_paketi(a["display_name"], a["connection_password"],
                                         a["update_interval_ms"], a["command_password"])):
            return False
        bitis = time.monotonic() + float(a["realtime_timeout_s"])
        while time.monotonic() < bitis and not self._stop.is_set():
            try:
                data, _ = self._sock.recvfrom(MAX_PAKET)  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                time.sleep(0.05)
                continue
            try:
                tip, nesne = self._coz.parse(data)
            except ProtocolError:
                self.istatistik["bozuk"] += 1
                continue
            if tip == IN_KAYIT_SONUCU and isinstance(nesne, KayitSonucu):
                if nesne.basarili:
                    with self._lock:
                        self._conn_id = nesne.connection_id
                        self.baglandi = True
                        self.salt_okunur = nesne.salt_okunur
                    self.son_hata = ""
                    self._gonder(entry_list_istek_paketi(nesne.connection_id))
                    self._gonder(track_data_istek_paketi(nesne.connection_id))
                    LOG.info("Broadcasting kaydi basarili (id=%s, salt_okunur=%s)",
                             nesne.connection_id, nesne.salt_okunur)
                    return True
                self._reddedildi = True
                self.son_hata = f"kayit_reddedildi: {nesne.hata}"
                LOG.warning(self.son_hata)
                return False
        if not self.son_hata.startswith("kayit_reddedildi"):
            self.son_hata = "kayit_zaman_asimi (ACC kapali mi? broadcasting.json portu/parola dogru mu?)"
        return False

    def connect(self) -> bool:
        self._stop.clear()
        self._reddedildi = False
        hedef, hata = self._hedef()
        if hedef is None:
            self.son_hata = hata
            return False
        self._adres = hedef
        self._soket_kapat()
        try:
            self._soket_ac()
        except OSError as e:
            self.son_hata = f"soket_hatasi: {e}"
            return False
        for _ in range(int(self.ayar["reconnect_max"])):
            if self._kayit_dene():
                return True
            if self._reddedildi or self._stop.is_set():
                break
        with self._lock:
            self.baglandi = False
        self._soket_kapat()
        return False

    def calisiyor(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.calisiyor():
            return True
        if not self.baglandi and not self.connect():
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._dongu, name="acc-broadcasting", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            conn = self._conn_id
        if conn is not None and self._sock is not None:
            self._gonder(kayit_sil_paketi(conn))
        th = self._thread
        if th is not None and th is not threading.current_thread():
            th.join(2.0)
        self._thread = None
        with self._lock:
            self.baglandi = False
            self._conn_id = None
        self._soket_kapat()

    # --- alim dongusu
    def _dongu(self) -> None:
        son_veri = time.monotonic()
        timeout = float(self.ayar["realtime_timeout_s"])
        while not self._stop.is_set():
            data = None
            try:
                data, _ = self._sock.recvfrom(MAX_PAKET)  # type: ignore[union-attr]
            except socket.timeout:
                pass
            except (OSError, AttributeError):
                if self._sock is None:
                    break
                time.sleep(0.05)
            if data is not None:
                self.istatistik["paket"] += 1
                try:
                    tip, nesne = self._coz.parse(data)
                    self._isle(tip, nesne)
                except ProtocolError as e:
                    self.istatistik["bozuk"] += 1
                    LOG.debug("bozuk paket: %s", e)
                    continue
                except Exception:
                    self.istatistik["bozuk"] += 1
                    LOG.exception("paket isleme hatasi")
                    continue
                son_veri = time.monotonic()
                continue
            if time.monotonic() - son_veri > timeout:
                with self._lock:
                    self.baglandi = False
                ok = False
                for _ in range(int(self.ayar["reconnect_max"])):
                    if self._stop.is_set():
                        break
                    self.istatistik["yeniden_kayit"] += 1
                    if self._kayit_dene():
                        ok = True
                        break
                    if self._reddedildi:
                        break
                if not ok:
                    self.son_hata = self.son_hata or "yeniden_baglanti_basarisiz"
                    LOG.warning("Broadcasting baglantisi kayboldu: %s", self.son_hata)
                    break
                son_veri = time.monotonic()
        with self._lock:
            self.baglandi = False

    def _zenginlestir(self, cu: CarUpdate) -> None:
        e = self._entries.get(cu.car_id)
        if e is not None:
            cu.team_name, cu.race_number, cu.car_model_id = e.takim, e.yaris_no, e.model_id
            cu.car_model = ARAC_MODELI.get(e.model_id, f"model_{e.model_id}")
            if e.suruculer:
                i = cu.driver_index if 0 <= cu.driver_index < len(e.suruculer) else 0
                cu.driver_name = e.suruculer[i].tam_ad()
        cu.penalty = self._penalty.get(cu.car_id)

    def _isle(self, tip: int, nesne: Any) -> None:
        if tip == IN_OTURUM and isinstance(nesne, OturumGuncelleme):
            with self._lock:
                self._oturum = nesne
        elif tip == IN_ARAC and isinstance(nesne, CarUpdate):
            with self._lock:
                bilinmiyor = nesne.car_id not in self._entries
                self._zenginlestir(nesne)
                self._cars[nesne.car_id] = nesne
                conn = self._conn_id
            self.istatistik["car_update"] += 1
            if bilinmiyor and conn is not None and time.monotonic() - self._son_entry_istek > 5.0:
                self._son_entry_istek = time.monotonic()
                self._gonder(entry_list_istek_paketi(conn))
            try:
                self._q.put_nowait(nesne)
            except queue.Full:
                try:
                    self._q.get_nowait()
                    self._q.put_nowait(nesne)
                except (queue.Empty, queue.Full):
                    pass
        elif tip == IN_ENTRY_LIST:
            ids = set(nesne[1])
            with self._lock:
                self._entries = {k: v for k, v in self._entries.items() if k in ids}
        elif tip == IN_ENTRY_CAR and isinstance(nesne, GirisKaydi):
            with self._lock:
                self._entries[nesne.car_id] = nesne
        elif tip == IN_PIST and isinstance(nesne, PistBilgisi):
            with self._lock:
                self._pist = nesne
        elif tip == IN_OLAY and isinstance(nesne, YayinOlayi):
            with self._lock:
                self._olaylar.append(nesne)
                if nesne.tip == 3 and nesne.car_id >= 0:
                    self._penalty[nesne.car_id] = nesne.mesaj

    # --- genel API
    def iter_updates(self, timeout_s: Optional[float] = None) -> Iterator[CarUpdate]:
        """CarUpdate'leri verir; timeout_s boyunca veri gelmezse veya istemci durursa biter.
        Baglanti/baslatma yoksa bos biter. (read_updates ile ayni kuyrugu tuketir.)"""
        t = _sayi_ya_da_none(timeout_s)
        t = float(self.ayar["realtime_timeout_s"]) if t is None or t <= 0 else t
        bitis = time.monotonic() + t
        while True:
            try:
                cu = self._q.get(timeout=0.2)
            except queue.Empty:
                if not self.calisiyor() or time.monotonic() >= bitis:
                    return
                continue
            bitis = time.monotonic() + t
            yield cu

    def read_updates(self) -> List[CarUpdate]:
        out: List[CarUpdate] = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                return out

    def _taze(self, cu: CarUpdate) -> bool:
        return time.monotonic() - cu.t <= float(self.ayar["realtime_timeout_s"])

    def get_car(self, car_id: Any) -> Optional[CarUpdate]:
        cid = _int_ya_da_none(car_id)
        with self._lock:
            cu = self._cars.get(cid) if cid is not None else None
            if cu is None:
                return None
            self._zenginlestir(cu)
            return copy.copy(cu)

    def get_position(self, car_id: Any) -> Optional[int]:
        """Broadcasting API'den gelen resmi sira (1 tabanli); veri yok/bayat ise None."""
        cu = self.get_car(car_id)
        if cu is None or cu.position <= 0 or not self._taze(cu):
            return None
        return cu.position

    def cars_snapshot(self) -> List[CarUpdate]:
        with self._lock:
            return [copy.copy(c) for c in self._cars.values() if self._taze(c)]

    def find_by_race_number(self, yaris_no: int) -> Optional[int]:
        with self._lock:
            for cid, e in self._entries.items():
                if e.yaris_no == yaris_no:
                    return cid
        return None

    def oturum(self) -> Optional[OturumGuncelleme]:
        with self._lock:
            return copy.copy(self._oturum) if self._oturum else None

    def pop_events(self) -> List[YayinOlayi]:
        with self._lock:
            o = list(self._olaylar)
            self._olaylar.clear()
            return o

    def track_neighbors(self, car_id: Any) -> Dict[str, Optional[Tuple[int, Optional[float]]]]:
        """Pistteki araclari spline'a gore dairesel siralar; (komsu_id, mesafe_m|None) doner."""
        bos: Dict[str, Optional[Tuple[int, Optional[float]]]] = {"ahead": None, "behind": None}
        cid = _int_ya_da_none(car_id)
        cars = sorted((c for c in self.cars_snapshot() if c.car_location == 1), key=lambda c: c.spline)
        idx = next((i for i, c in enumerate(cars) if c.car_id == cid), None)
        if idx is None or len(cars) < 2:
            return bos
        with self._lock:
            metre = float(self._pist.uzunluk_m) if self._pist and self._pist.uzunluk_m > 0 else None
        me, on, arka = cars[idx], cars[(idx + 1) % len(cars)], cars[(idx - 1) % len(cars)]
        return {
            "ahead": (on.car_id, ((on.spline - me.spline) % 1.0) * metre if metre else None),
            "behind": (arka.car_id, ((me.spline - arka.spline) % 1.0) * metre if metre else None),
        }


# ----------------------------------------------------------------------------- canli izleme

def izle(sure_s: float) -> int:
    ayar = ayar_yukle()
    cl = BroadcastingClient(ayar)
    print(f"Hedef: {ayar['host']}:{ayar['port']} (UDP) | parola: {'var' if ayar['connection_password'] else 'bos'}")
    if not cl.start():
        print("BAGLANTI YOK:", cl.son_hata)
        return 2
    print("Baglandi. salt_okunur =", cl.salt_okunur)
    t0 = time.monotonic()
    bitis = t0 + max(1.0, sure_s)
    son = 0.0
    try:
        while time.monotonic() < bitis and cl.calisiyor():
            time.sleep(0.1)
            simdi = time.monotonic()
            for e in cl.pop_events():
                print(f"[{simdi - t0:6.1f}s] OLAY {e.tip_adi} car={e.car_id} '{e.mesaj}'")
            if simdi - son < 1.0:
                continue
            son = simdi
            o = cl.oturum()
            odak = o.odak_arac_id if o else -1
            me = cl.get_car(odak)
            satir = f"[{simdi - t0:6.1f}s] arac={len(cl.cars_snapshot())}"
            if o:
                satir += f" | {o.session_tipi_adi}/{o.faz_adi}"
            if me:
                nb = cl.track_neighbors(odak)
                satir += (f" | odak={odak} #{me.race_number} sira={me.position} spline={me.spline:.3f} "
                          f"{me.location_name} on={nb['ahead']} arka={nb['behind']}")
            print(satir)
    except KeyboardInterrupt:
        print("Kesildi.")
    finally:
        cl.stop()
    p = cl._pist
    if p is None:
        print("PIST: bilgi gelmedi (ACC pist verisini gondermedi ya da cozulemedi)")
    else:
        print("PIST:", p.uzunluk_m, "m | kamera_setleri:", p.kamera_setleri, "| hud:", p.hud_sayfalari, "| ham:", len(p.ham), "bayt")
        if p.kamera_setleri is None:
            print("PIST HAM (ilk 400 bayt):", p.ham[:400].hex())
    print("ISTATISTIK:", cl.istatistik, "| son_hata:", cl.son_hata or "-")
    if cl.istatistik["car_update"] == 0 and cl.istatistik["bozuk"] > 0:
        print("UYARI: car update hic ayristirilamadi; paket yerlesimi dogrulanmali.")
    return 0


# ----------------------------------------------------------------------------- testler

class _Kontrol:
    def __init__(self) -> None:
        self.say = 0
        self.hata = 0

    def __call__(self, ad: str, kosul: Any, detay: Any = None) -> None:
        self.say += 1
        if kosul:
            print("  OK  ", ad)
        else:
            self.hata += 1
            print("  HATA", ad, "->", detay)


def _pl(ms: int = 123456, cid: int = 1, did: int = 0, splits: Tuple[int, ...] = (40000, 41000, 42456),
        inv: bool = False, vb: bool = True) -> bytes:
    return (struct.pack("<iHHB", ms, cid, did, len(splits)) + b"".join(struct.pack("<i", x) for x in splits)
            + struct.pack("<BBBB", inv, vb, False, False))


def _p_kayit_sonucu(conn: int, ok: bool, ro: bool, hata: str = "") -> bytes:
    return struct.pack("<BiBB", 1, conn, 1 if ok else 0, 0 if ro else 1) + _ps(hata)


def _p_car(car_id: int, pos: int, spline: float, loc: int = 1, laps: int = 3,
           trackpos: int = 1, drv: int = 0, kmh: int = 150) -> bytes:
    head = struct.pack("<BHHBBfffBHHHH", 3, car_id, drv, 1, 5, 10.0, 20.0, 0.5, loc, kmh, pos, pos, trackpos)
    return head + struct.pack("<fHi", spline, laps, 250) + _pl(cid=car_id) + _pl(cid=car_id) + _pl(cid=car_id)


def _p_entry_car(car_id: int, model: int, team: str, no: int, suruculer: List[Tuple[str, str, str]]) -> bytes:
    b = struct.pack("<BHB", 6, car_id, model) + _ps(team) + struct.pack("<iBBHB", no, 0, 0, 0, len(suruculer))
    for f, l, s in suruculer:
        b += _ps(f) + _ps(l) + _ps(s) + struct.pack("<BH", 0, 0)
    return b


def _p_entry_list(ids: List[int]) -> bytes:
    return struct.pack("<BiH", 4, 7, len(ids)) + b"".join(struct.pack("<H", i) for i in ids)


def _p_oturum(odak: int = 2, faz: int = 5) -> bytes:
    return (struct.pack("<BHHBBffi", 2, 1, 0, 10, faz, 60000.0, 1800000.0, odak) + _ps("Drivable") + _ps("Chase")
            + struct.pack("<B", 0) + struct.pack("<fBBBBB", 50000.0, 22, 30, 0, 0, 0) + _pl())


def _p_pist(ad: str = "Monza", pid: int = 5, metre: int = 5000, sets: Optional[Dict[str, List[str]]] = None, huds: Optional[List[str]] = None) -> bytes:
    sets, huds = sets or {}, huds or []
    b = struct.pack("<Bi", 5, 7) + _ps(ad) + struct.pack("<iiB", pid, metre, len(sets))
    for sn, cams in sets.items():
        b += _ps(sn) + struct.pack("<B", len(cams)) + b"".join(_ps(x) for x in cams)
    return b + struct.pack("<B", len(huds)) + b"".join(_ps(x) for x in huds)


def _p_olay(tip: int, mesaj: str, ms: int, car: int) -> bytes:
    return struct.pack("<BB", 7, tip) + _ps(mesaj) + struct.pack("<ii", ms, car)


class _SahteACC(threading.Thread):
    """Sentetik ACC: kayit alir, entry list/track/guncelleme yayinlar. mod: normal|kirli|sessiz"""

    def __init__(self, sifre: str = "asd", mod: str = "normal") -> None:
        super().__init__(daemon=True)
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(("127.0.0.1", 0))
        self.s.settimeout(0.1)
        if hasattr(socket, "SIO_UDP_CONNRESET"):
            try:
                self.s.ioctl(socket.SIO_UDP_CONNRESET, False)
            except (OSError, ValueError):
                pass
        self.port = self.s.getsockname()[1]
        self.sifre, self.mod = sifre, mod
        self.kayit_sayisi = 0
        self.unregister = False
        self.istemci: Optional[Tuple[str, int]] = None
        self._dur = threading.Event()

    def kapat(self) -> None:
        self._dur.set()
        self.join(2.0)
        self.s.close()

    def _yolla(self, pkt: bytes) -> None:
        if self.istemci:
            try:
                self.s.sendto(pkt, self.istemci)
            except OSError:
                pass

    def _isle(self, data: bytes, adr: Tuple[str, int]) -> None:
        if data[0] == 1:
            r = _Okuyucu(data)
            r.u8(), r.u8(), r.string()
            pw = r.string()
            self.kayit_sayisi += 1
            if self.mod == "sessiz" and self.kayit_sayisi > 1:
                return
            self.istemci = adr
            if pw != self.sifre:
                self._yolla(_p_kayit_sonucu(-1, False, True, "Wrong password"))
                self.istemci = None
                return
            self._yolla(_p_kayit_sonucu(7, True, True))
            if self.mod == "sessiz":
                return
            self._yolla(_p_entry_list([1, 2, 3]))
            self._yolla(_p_entry_car(1, 2, "Team A", 11, [("Ali", "Veli", "AVE")]))
            self._yolla(_p_entry_car(2, 30, "Team B", 22, [("Ayse", "Fatma", "AFA"), ("Can", "Er", "CER")]))
            self._yolla(_p_entry_car(3, 1, "Team C", 33, [("Zeki", "Aksu", "ZAK")]))
            self._yolla(_p_pist())
        elif data[0] == 9:
            self.unregister = True

    def run(self) -> None:
        n = 0
        bitis = time.monotonic() + 25
        while not self._dur.is_set() and time.monotonic() < bitis:
            try:
                data, adr = self.s.recvfrom(MAX_PAKET)
            except (socket.timeout, OSError):
                data, adr = None, None
            if data:
                self._isle(data, adr)  # type: ignore[arg-type]
            if self.istemci and self.mod in ("normal", "kirli"):
                n += 1
                self._yolla(_p_oturum(odak=2))
                for cid, pos, sp in ((1, 1, 0.50), (2, 2, 0.30), (3, 3, 0.10)):
                    self._yolla(_p_car(cid, pos, sp + 0.0001 * n, drv=1 if cid == 2 else 0))
                if n == 3:
                    self._yolla(_p_olay(3, "Drive through", 120000, 2))
                if self.mod == "kirli":
                    self._yolla(b"\xff" * 20)
                    self._yolla(b"\x03\x01")
                    self._yolla(b"\x02")


def _bekle(kosul: Any, sure: float = 3.0) -> bool:
    bitis = time.monotonic() + sure
    while time.monotonic() < bitis:
        if kosul():
            return True
        time.sleep(0.05)
    return bool(kosul())


def selftest() -> int:
    c = _Kontrol()
    print("== BROADCASTING SELFTEST (sentetik veri) ==")
    tip, k = parse_paket(_p_kayit_sonucu(7, True, True))
    c("1 kayit sonucu basarili/salt okunur", tip == 1 and k.basarili and k.salt_okunur and k.connection_id == 7, k)
    tip, k = parse_paket(_p_kayit_sonucu(-1, False, True, "Wrong password"))
    c("1 kayit sonucu reddedildi", not k.basarili and k.hata == "Wrong password", k)
    tip, k = parse_paket(struct.pack("<BiBB", 1, 3, 1, 1) + _ps(""))
    c("1 komut yetkili (readonly=False)", k.basarili and not k.salt_okunur, k)

    tip, o = parse_paket(_p_oturum(odak=4, faz=5))
    c("2 oturum guncelleme", tip == 2 and o.odak_arac_id == 4 and o.faz_adi == "SESSION"
      and o.session_tipi_adi == "RACE" and o.kamera == "Chase", o)

    coz2 = Cozumleyici()
    sets_t = {"Drivable": ["Chase", "Onboard0"], "Pits": ["Pit1"]}
    tip, p = coz2.parse(_p_pist("Spa", 3, 7004, sets_t, ["Basic HUD", "Help"]))
    c("5 pist: kamera setleri ve HUD", tip == 5 and p.uzunluk_m == 7004 and p.kamera_setleri == sets_t
      and p.hud_sayfalari == ["Basic HUD", "Help"] and isinstance(p.ham, bytes) and len(p.ham) > 0, p)
    tip, p = coz2.parse(_p_pist())
    c("5 pist: bos kamera listesi", p.kamera_setleri == {} and p.hud_sayfalari == [] and p.uzunluk_m == 5000, p)
    tip, p = coz2.parse(_p_pist("Spa", 3, 7004, sets_t, ["H"])[:-2])
    c("5 pist: kesik veri -> None, cokmez", p.kamera_setleri is None and p.hud_sayfalari is None and p.uzunluk_m == 7004, p)

    coz = Cozumleyici()
    tip, cu = coz.parse(_p_car(5, 9, 0.4321, laps=3, kmh=187, trackpos=4))
    c("3 car update: alanlar", tip == 3 and cu.car_id == 5 and cu.position == 9
      and abs(cu.spline - 0.4321) < 1e-4 and cu.laps == 3 and cu.speed_kmh == 187 and cu.delta_ms == 250
      and cu.last_lap and cu.last_lap.sure_ms == 123456 and cu.gear == 3, cu)
    _, cu = parse_paket(_p_car(5, 9, 0.2, loc=2))
    c("3 pit: is_in_pit/is_in_pit_lane", cu.is_in_pit and cu.is_in_pit_lane and cu.location_name == "PITLANE")
    _, cu = parse_paket(_p_car(5, 9, 0.2, loc=3))
    c("3 pit girisi: pit lane ama is_in_pit False", (not cu.is_in_pit) and cu.is_in_pit_lane)

    _, e = parse_paket(_p_entry_car(2, 30, "Team B", 22, [("Ayse", "Fatma", "AFA"), ("Can", "Er", "CER")]))
    c("4 entry car", e.car_id == 2 and e.yaris_no == 22 and len(e.suruculer) == 2
      and e.suruculer[1].tam_ad() == "Can Er", e)
    _, el = parse_paket(_p_entry_list([1, 2, 3]))
    c("4 entry list", el == (7, [1, 2, 3]), el)
    _, p = parse_paket(_p_pist())
    c("4 pist bilgisi", p.ad == "Monza" and p.uzunluk_m == 5000, p)
    _, ev = parse_paket(_p_olay(3, "Drive through", 1000, 2))
    c("4 olay", ev.tip_adi == "PENALTY_COMM_MSG" and ev.car_id == 2 and ev.mesaj == "Drive through", ev)
    c("4 bilinmeyen tip -> (tip, None)", parse_paket(b"\x63abc") == (0x63, None))

    pk = _p_car(1, 1, 0.5)
    hatali = []
    for kes in range(1, len(pk)):
        try:
            Cozumleyici().parse(pk[:kes])
        except ProtocolError:
            pass
        except Exception as ex:
            hatali.append((kes, repr(ex)))
    c("5 kesik paketler yalniz ProtocolError", not hatali, hatali[:3])
    try:
        Cozumleyici().parse(pk[:-1])
        c("5 son bayti eksik paket reddedilir", False)
    except ProtocolError:
        c("5 son bayti eksik paket reddedilir", True)

    kp = kayit_paketi("X", "asd", 250, "")
    c("6 kayit paketi: tip/surum/parola", kp[0] == 1 and kp[1] == 4 and b"asd" in kp, kp)
    c("6 kayit sil paketi", kayit_sil_paketi(7) == struct.pack("<Bi", 9, 7))

    # istemci: sunucu yok
    sessiz = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sessiz.bind(("127.0.0.1", 0))
    cl = BroadcastingClient({"port": sessiz.getsockname()[1], "reconnect_max": 2, "realtime_timeout_s": 0.4})
    c("7 yanit yok: connect False", cl.connect() is False and "zaman_asimi" in cl.son_hata, cl.son_hata)
    c("7 yanit yok: get_position None, iter/read bos", cl.get_position(1) is None
      and list(cl.iter_updates(0.3)) == [] and cl.read_updates() == [])
    cl.stop()
    sessiz.close()
    c("7 yerel olmayan host reddedilir", BroadcastingClient({"host": "8.8.8.8"}).connect() is False)

    # istemci: uctan uca
    srv = _SahteACC()
    srv.start()
    cl = BroadcastingClient({"port": srv.port, "reconnect_max": 2, "realtime_timeout_s": 1.0,
                             "connection_password": "asd"})
    c("8 e2e: start", cl.start(), cl.son_hata)
    got: List[CarUpdate] = []
    _bekle(lambda: (got.extend(cl.read_updates()) or True) and len({u.car_id for u in got}) >= 3)
    c("8 e2e: 3 arac guncellemesi", len({u.car_id for u in got}) == 3, len(got))
    c("8 e2e: get_position", cl.get_position(1) == 1 and cl.get_position(2) == 2 and cl.get_position(99) is None)
    c1, c2 = cl.get_car(1), cl.get_car(2)
    c("8 e2e: entry list eslesmesi", c1.driver_name == "Ali Veli" and c1.car_model == ARAC_MODELI[2]
      and c1.race_number == 11 and c2.driver_name == "Can Er" and c2.team_name == "Team B", (c1, c2))
    c("8 e2e: ceza olay tabanli", _bekle(lambda: cl.get_car(2).penalty == "Drive through"), cl.get_car(2).penalty)
    nb = cl.track_neighbors(2)
    c("8 e2e: spline komsulari", nb["ahead"] and nb["ahead"][0] == 1 and nb["behind"] and nb["behind"][0] == 3
      and abs(nb["ahead"][1] - 1000.0) < 5.0, nb)
    c("8 e2e: race number -> carId", cl.find_by_race_number(33) == 3)
    cl.stop()
    c("8 e2e: UNREGISTER gonderildi", _bekle(lambda: srv.unregister, 1.5))
    cl.stop()
    c("8 e2e: stop iki kez cokmez", True)
    srv.kapat()

    # yanlis parola
    srv = _SahteACC(sifre="dogru")
    srv.start()
    cl = BroadcastingClient({"port": srv.port, "reconnect_max": 3, "realtime_timeout_s": 1.0,
                             "connection_password": "yanlis"})
    c("9 yanlis parola: connect False", cl.connect() is False and "reddedildi" in cl.son_hata, cl.son_hata)
    c("9 yanlis parola: tekrar denenmedi", srv.kayit_sayisi == 1, srv.kayit_sayisi)
    srv.kapat()

    a = ayar_birlestir({"port": "9001", "reconnect_max": 99, "realtime_timeout_s": -1, "host": " localhost ",
                        "update_interval_ms": 1, "connection_password": "asd"})
    c("10 ayar: temizleme", a["port"] == 9001 and a["reconnect_max"] == 10 and a["realtime_timeout_s"] == 0.2
      and a["host"] == "localhost" and a["update_interval_ms"] == 50 and a["connection_password"] == "asd", a)
    c("10 ayar: bozuk bolum -> varsayilan", ayar_birlestir(None) == _VARSAYILAN and ayar_birlestir("x") == _VARSAYILAN)

    if c.hata == 0:
        print(f"SELFTEST TAMAM ({c.say} kontrol)")
        return 0
    print(f"SELFTEST BASARISIZ ({c.hata}/{c.say} hata)")
    return 1


def badtest() -> int:
    import random
    c = _Kontrol()
    print("== BROADCASTING BADTEST (bozuk girdi) ==")
    rng = random.Random(1234)
    beklenmeyen = []
    coz = Cozumleyici()
    for i in range(3000):
        veri = bytes(rng.getrandbits(8) for _ in range(rng.randint(0, 120)))
        if veri and i % 3 == 0:
            veri = bytes([rng.choice([1, 2, 3, 4, 5, 6, 7])]) + veri[1:]
        try:
            coz.parse(veri)
        except ProtocolError:
            pass
        except Exception as e:
            beklenmeyen.append(repr(e))
    c("1 rastgele baytlar: yalniz ProtocolError", not beklenmeyen, beklenmeyen[:3])
    kotu = []
    for t in range(256):
        for yuk in (b"", b"\x00", b"\xff" * 7):
            try:
                coz.parse(bytes([t]) + yuk)
            except ProtocolError:
                pass
            except Exception as e:
                kotu.append((t, repr(e)))
    c("2 tum tipler x bos/kisa govde", not kotu, kotu[:3])
    for ad, pk in (("dev string", struct.pack("<BiBB", 1, 1, 1, 0) + struct.pack("<H", 60000)),
                   ("bos", b""), ("tek bayt", b"\x03")):
        try:
            coz.parse(pk)
            c(f"3 {ad}: ProtocolError", False)
        except ProtocolError:
            c(f"3 {ad}: ProtocolError", True)
        except Exception as e:
            c(f"3 {ad}: ProtocolError", False, repr(e))
    for ad, veri in (("str", "abc"), ("None", None), ("int", 5)):
        try:
            coz.parse(veri)  # type: ignore[arg-type]
            c(f"3 bytes olmayan girdi {ad}", False)
        except ProtocolError:
            c(f"3 bytes olmayan girdi {ad}", True)

    for port in (0, -1, 70000, 65536):
        try:
            cl = BroadcastingClient({"port": port, "realtime_timeout_s": 0.3})
            c(f"4 gecersiz port {port}: connect False", cl.connect() is False and cl.son_hata == "gecersiz_port", cl.son_hata)
            c(f"4 gecersiz port {port}: get_position None", cl.get_position(1) is None)
        except Exception as e:
            c(f"4 gecersiz port {port}: istisna", False, repr(e))
    c("4 port 'abc' -> varsayilan 9000", BroadcastingClient({"port": "abc"}).ayar["port"] == 9000)
    try:
        BroadcastingClient({"host": "yok.invalid"}).connect()
        c("4 gecersiz host: coker yok", True)
    except Exception as e:
        c("4 gecersiz host: coker yok", False, repr(e))
    try:
        cl = BroadcastingClient()
        cl.stop()
        cl.stop()
        c("4 baslamadan stop: coker yok", True)
    except Exception as e:
        c("4 baslamadan stop: coker yok", False, repr(e))

    srv = _SahteACC(mod="kirli")
    srv.start()
    cl = BroadcastingClient({"port": srv.port, "reconnect_max": 2, "realtime_timeout_s": 1.0, "connection_password": "asd"})
    ok = cl.start()
    c("5 kirli akis: start", ok, cl.son_hata)
    c("5 kirli akis: gecerli paketler islendi", _bekle(lambda: cl.get_position(1) == 1))
    c("5 kirli akis: bozuk paket sayildi, thread yasiyor", cl.istatistik["bozuk"] > 0 and cl.calisiyor(), cl.istatistik)
    cl.stop()
    srv.kapat()

    srv = _SahteACC(mod="sessiz")
    srv.start()
    cl = BroadcastingClient({"port": srv.port, "reconnect_max": 2, "realtime_timeout_s": 0.5, "connection_password": "asd"})
    c("6 kopuk baglanti: ilk kayit", cl.start(), cl.son_hata)
    c("6 kopuk baglanti: thread sonlandi", _bekle(lambda: not cl.calisiyor(), 6.0), cl.istatistik)
    c("6 kopuk baglanti: baglandi False, yeniden kayit denendi, get_position None",
      (not cl.baglandi) and cl.istatistik["yeniden_kayit"] >= 1 and cl.get_position(1) is None
      and list(cl.iter_updates(0.3)) == [], (cl.istatistik, cl.son_hata))
    cl.stop()
    srv.kapat()

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
    ap = argparse.ArgumentParser(description="ACC Broadcasting API istemcisi")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--selftest", action="store_true", help="ACC kapali, sentetik paket + sahte sunucu")
    g.add_argument("--badtest", action="store_true", help="ACC kapali, bozuk girdi/kopuk baglanti")
    g.add_argument("--watch", type=float, metavar="N", help="ACC acik, N saniye canli izleme")
    a = ap.parse_args(argv)
    handlers: List[logging.Handler] = [logging.StreamHandler()]
    try:
        (PROJE_KOKU / "logs").mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(PROJE_KOKU / "logs" / "acc.log", encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.selftest:
        return selftest()
    if a.badtest:
        return badtest()
    return izle(a.watch)


if __name__ == "__main__":
    sys.exit(main())
