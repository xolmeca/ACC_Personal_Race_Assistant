"""Komut kabul testi: kamera/HUD degisikligi ACC'de gorunuyor mu? python komut_testi.py
ACC oturumunda araci pistte tut. Sonuc: komut_testi_log.txt"""
from __future__ import annotations

import struct
import time

from modules.acc.acc_broadcasting_client import BroadcastingClient, ayar_yukle, _ps

LOG = "komut_testi_log.txt"


def log(m: str) -> None:
    s = time.strftime("%H:%M:%S ") + m
    print(s, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")


def bip(n: int = 1, hz: int = 900) -> None:
    try:
        import winsound
        for _ in range(n):
            winsound.Beep(hz, 180)
            time.sleep(0.12)
    except Exception:
        pass


def oturum(cl) -> dict:
    o = cl.oturum
    o = o() if callable(o) else o
    return dict(vars(o)) if hasattr(o, "__dict__") else {}


def odak_paketi(conn, car, cs, kam) -> bytes:  # DOGRULANMADI: tip 50
    p = struct.pack("<Bi", 50, int(conn))
    p += (b"\x01" + struct.pack("<H", int(car))) if car is not None else b"\x00"
    p += (b"\x01" + _ps(cs) + _ps(kam)) if (cs and kam) else b"\x00"
    return p


def hud_paketi(conn, sayfa) -> bytes:  # DOGRULANMADI: tip 49
    return struct.pack("<Bi", 49, int(conn)) + _ps(sayfa)


def main() -> int:
    open(LOG, "w").close()
    log("BASLADI. ACC oturumuna gir, araci pistte tut.")
    t_son = time.monotonic() + 600
    cl = None
    while time.monotonic() < t_son:
        c = BroadcastingClient(ayar_yukle())
        if c.start():
            cl = c
            break
        try:
            c.stop()
        except Exception:
            pass
        time.sleep(5.0)
    if cl is None:
        log("BAGLANTI KURULAMADI")
        bip(3, 400)
        return 2
    try:
        log(f"BAGLANDI salt_okunur={cl.salt_okunur}")
        bip(1, 600)
        conn = getattr(cl, "_conn_id", None)
        time.sleep(4.0)
        d = oturum(cl)
        car = int(d.get("odak_arac_id") or 0)
        log(f"taban: kamera_seti={d.get('kamera_seti')} kamera={d.get('kamera')} odak={car}")
        adimlar = [
            ("kamera Drivable/Chase", odak_paketi(conn, car, "Drivable", "Chase"), "Chase"),
            ("kamera Drivable/Cockpit", odak_paketi(conn, car, "Drivable", "Cockpit"), "Cockpit"),
            ("HUD Help (ekranda gorunur)", hud_paketi(conn, "Help"), None),
            ("HUD Basic HUD", hud_paketi(conn, "Basic HUD"), None),
            ("kamera Drivable/Bonnet", odak_paketi(conn, car, "Drivable", "Bonnet"), "Bonnet"),
        ]
        kabul = 0
        for i, (ad, pkt, beklenen) in enumerate(adimlar, 1):
            ok = cl._gonder(pkt)
            bip(i)
            log(f"ADIM {i}: {ad} gonderildi={ok} hex={pkt.hex()}")
            t0 = time.monotonic()
            gorulen = oturum(cl).get("kamera")
            while time.monotonic() - t0 < 6.0:
                gorulen = oturum(cl).get("kamera")
                if beklenen and gorulen == beklenen:
                    break
                time.sleep(0.5)
            if beklenen:
                ok2 = gorulen == beklenen
                kabul += int(ok2)
                log(f"  beklenen={beklenen} gorulen={gorulen} -> " + ("KABUL" if ok2 else "DEGISMEDI"))
            else:
                log("  HUD degisimi log'dan okunamaz; ekrana bak")
            time.sleep(2.0)
        log("-" * 30)
        log(f"KAMERA KOMUTLARI KABUL: {kabul}/3")
        log("SONUC: komutlar ACC'de ETKILI" if kabul else "SONUC: komut hic etki etmedi")
        bip(3, 1200)
        return 0
    finally:
        cl.stop()


if __name__ == "__main__":
    raise SystemExit(main())
