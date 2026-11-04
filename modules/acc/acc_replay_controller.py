"""acc_replay_controller v1 - InstantReplayRequest paketi (saf fonksiyon) + gonderim.

DOGRULANMADI (gercek ACC ile test edilene kadar):
- alan sirasi/turleri (tip 51, conn int32, baslangic f32, sure f32, odak int32, 2 string)
- startSessionTime birimi: ms (zamanli yarista goruntuyle destekleniyor, 2026-11-05)
- yaris sonrasi replay davranisi
- komut sifresi olmadan (salt okunur kayit) komut reddedilir; burada kontrol YOK
Tus gonderimi yok. Yarista LLM yok.
"""
from __future__ import annotations

import struct
import sys

from modules.acc.acc_broadcasting_client import _ps

OUT_INSTANT_REPLAY = 51  # DOGRULANMADI


def instant_replay_paketi(conn_id: int, baslangic_ms: float, sure_ms: float,
                          odak_arac: int = -1, kamera_seti: str = "",
                          kamera: str = "") -> bytes:
    if sure_ms <= 0:
        raise ValueError("sure_ms > 0 olmali")
    if baslangic_ms < 0:
        raise ValueError("baslangic_ms >= 0 olmali")
    return (struct.pack("<Bi", OUT_INSTANT_REPLAY, int(conn_id))
            + struct.pack("<ffi", float(baslangic_ms), float(sure_ms), int(odak_arac))
            + _ps(kamera_seti) + _ps(kamera))


def replay_gonder(client, baslangic_ms: float, sure_ms: float, odak_arac: int = -1,
                  kamera_seti: str = "", kamera: str = "") -> bool:
    """Bagli istemci uzerinden gonderir. Baglanti yoksa False doner."""
    conn = getattr(client, "_conn_id", None)
    if conn is None or not getattr(client, "baglandi", False):
        return False
    pkt = instant_replay_paketi(conn, baslangic_ms, sure_ms, odak_arac, kamera_seti, kamera)
    return bool(client._gonder(pkt))


def _selftest() -> int:
    n = 0

    def c(ad: str, kosul: bool) -> None:
        nonlocal n
        n += 1
        print(("  OK   " if kosul else "  HATA ") + ad)
        if not kosul:
            raise SystemExit(1)

    p = instant_replay_paketi(7, 12.5, 15000.0, 3, "Drivable", "Chase")
    c("1 tip baytı 51", p[0] == OUT_INSTANT_REPLAY)
    c("2 conn_id", struct.unpack_from("<i", p, 1)[0] == 7)
    c("3 sayisal alanlar", struct.unpack_from("<ffi", p, 5) == (12.5, 15000.0, 3))
    c("4 uzunluk", len(p) == 17 + len(_ps("Drivable")) + len(_ps("Chase")))
    q = instant_replay_paketi(1, 0.0, 1000.0)
    c("5 varsayilan odak -1 ve bos stringler",
      struct.unpack_from("<i", q, 13)[0] == -1 and len(q) == 17 + len(_ps("")) * 2)
    for ad, args in (("6 sure<=0 hata", (1, 0.0, 0.0)), ("7 baslangic<0 hata", (1, -1.0, 1000.0))):
        try:
            instant_replay_paketi(*args)
            c(ad, False)
        except ValueError:
            c(ad, True)

    class Sahte:
        def __init__(self, conn, bagli):
            self._conn_id, self.baglandi, self.giden = conn, bagli, []

        def _gonder(self, pkt):
            self.giden.append(pkt)
            return True

    s = Sahte(7, True)
    c("8 gonder ok", replay_gonder(s, 5.0, 8000.0) and len(s.giden) == 1 and s.giden[0][0] == 51)
    k = Sahte(None, False)
    c("9 baglanti yok -> False", replay_gonder(k, 5.0, 8000.0) is False and not k.giden)
    print(f"SELFTEST TAMAM ({n} kontrol)")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("Kullanim: python -m modules.acc.acc_replay_controller --selftest")
