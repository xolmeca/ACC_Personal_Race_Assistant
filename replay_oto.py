"""Kisa otomatik replay denemesi. Proje kokunden: python replay_oto.py
ACC'yi bu betik calisirken ac, oturuma gir, araci pistte tut. Sonuc: replay_oto_log.txt"""
from __future__ import annotations

import time

from modules.acc.acc_broadcasting_client import (BroadcastingClient, ayar_yukle,
                                                  track_data_istek_paketi)
from modules.acc.acc_replay_controller import instant_replay_paketi, replay_gonder

LOG = "replay_oto_log.txt"
BAGLANTI_BEKLE_SN = 1200.0
ARAC_BEKLE_SN = 10.0
YERLESME_SN = 5.0
PENCERE_SN = 12.0
SURE_MS = 10000.0
DENEMELER = [(42.0, "", ""), (42000.0, "", ""), (0.0, "", ""), (42.0, "Drivable", "Chase")]
IZLENEN = ("replay", "odak_arac_id", "kamera_seti", "kamera", "faz_adi")


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


def baglan():
    t_son = time.monotonic() + BAGLANTI_BEKLE_SN
    n = 0
    while time.monotonic() < t_son:
        n += 1
        cl = BroadcastingClient(ayar_yukle())
        if cl.start():
            log(f"BAGLANDI (deneme {n})")
            bip(1, 600)
            return cl
        if n == 1 or n % 6 == 0:
            log(f"baglanti yok ({cl.son_hata}); bekleniyor, ACC oturumuna gir...")
        try:
            cl.stop()
        except Exception:
            pass
        time.sleep(5.0)
    return None


def main() -> int:
    open(LOG, "w").close()
    log("BASLADI. ACC'yi ac, oturuma gir, araci pistte tut. Komut satirina donme.")
    cl = baglan()
    if cl is None:
        log("SONUC: BAGLANTI KURULAMADI")
        bip(3, 400)
        return 2
    try:
        if cl.salt_okunur is not False:
            log(f"KOMUT YETKISI YOK salt_okunur={cl.salt_okunur}")
            bip(3, 400)
            return 3
        conn = getattr(cl, "_conn_id", None)
        cl._gonder(track_data_istek_paketi(conn))
        time.sleep(2.0)
        t_son = time.monotonic() + ARAC_BEKLE_SN
        while not cl.cars_snapshot() and time.monotonic() < t_son:
            time.sleep(1.0)
        log(f"arac idleri: {[a.car_id for a in cl.cars_snapshot()]}")
        time.sleep(YERLESME_SN)
        sonuc = []
        for i, (bas, cs, kam) in enumerate(DENEMELER, 1):
            ids = [a.car_id for a in cl.cars_snapshot()]
            odak = ids[0] if ids else int(oturum(cl).get("odak_arac_id") or 0)
            son = {k: oturum(cl).get(k) for k in IZLENEN}
            try:
                hexs = instant_replay_paketi(conn, bas, SURE_MS, odak, cs, kam).hex()
                ok = replay_gonder(cl, bas, SURE_MS, odak, cs, kam)
            except Exception as e:
                hexs, ok = "-", f"HATA {e!r}"
            bip(i)
            log(f"GONDER #{i} bas={bas} set={cs!r} kam={kam!r} odak={odak} sonuc={ok} hex={hexs}")
            t0 = time.monotonic()
            degisti = False
            while time.monotonic() - t0 < PENCERE_SN:
                cur = {k: oturum(cl).get(k) for k in IZLENEN}
                if cur != son:
                    fark = {k: (son[k], cur[k]) for k in IZLENEN if cur[k] != son[k]}
                    log(f"  #{i} DEGISTI +{time.monotonic() - t0:.0f}s: {fark}")
                    degisti = True
                    son = cur
                time.sleep(0.5)
            sonuc.append((i, bas, cs, kam, degisti))
        log("-" * 30)
        for i, bas, cs, kam, d in sonuc:
            log(f"#{i} bas={bas} set={cs!r}: " + ("DURUM DEGISTI" if d else "degismedi"))
        log("BITTI")
        bip(3, 1200)
        return 0
    finally:
        cl.stop()


if __name__ == "__main__":
    raise SystemExit(main())
