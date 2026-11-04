"""Zamanli oturumda replay: baslangic = simdiki oturum zamani - 20 sn. python replay_yaris.py"""
from __future__ import annotations

import time

import replay_oto as R
import replay_ss as S
from modules.acc.acc_broadcasting_client import track_data_istek_paketi
from modules.acc.acc_replay_controller import instant_replay_paketi, replay_gonder

R.LOG = "replay_yaris_log.txt"
S.KLASOR = "ekran_yaris"


def durum(cl) -> str:
    d = R.oturum(cl)
    return (f"replay={d.get('replay')} kamera={d.get('kamera')} "
            f"sess_ms={d.get('session_zamani_ms')} faz={d.get('faz_adi')} tip={d.get('session_tipi_adi')}")


def main() -> int:
    open(R.LOG, "w").close()
    R.log("BASLADI. ACC'de zamanli oturum (yaris/siralama) ac, pistte surmeye basla.")
    cl = R.baglan()
    if cl is None:
        R.log("BAGLANTI KURULAMADI")
        R.bip(3, 400)
        return 2
    try:
        if cl.salt_okunur is not False:
            R.log(f"KOMUT YETKISI YOK salt_okunur={cl.salt_okunur}")
            return 3
        conn = getattr(cl, "_conn_id", None)
        cl._gonder(track_data_istek_paketi(conn))
        t_son = time.monotonic() + 300
        n = 0
        while time.monotonic() < t_son:
            sess = R.oturum(cl).get("session_zamani_ms") or -1.0
            if n % 30 == 0:
                R.log("bekleniyor: " + durum(cl))
            if sess >= 40000:
                break
            n += 1
            time.sleep(1.0)
        sess = R.oturum(cl).get("session_zamani_ms") or -1.0
        gecerli = sess >= 40000
        R.log(f"oturum zamani gecerli mi: {gecerli} (sess_ms={sess})")
        R.bip(2, 700)
        oyuncu = int(R.oturum(cl).get('odak_arac_id') or 0)
        R.log(f'oyuncu araci (odak_arac_id): {oyuncu} | arac listesi: {[a.car_id for a in cl.cars_snapshot()][:5]}')
        if gecerli:
            plan = [("simdi-20sn (ms)", lambda s: s - 20000.0),
                    ("simdi-40sn (ms)", lambda s: s - 40000.0)]
        else:
            plan = [("sabit 42000", lambda s: 42000.0), ("sabit 42", lambda s: 42.0)]
        for i, (ad, f) in enumerate(plan, 1):
            now = R.oturum(cl).get("session_zamani_ms") or -1.0
            bas = max(0.0, f(now))
            ids = [a.car_id for a in cl.cars_snapshot()]
            odak = oyuncu
            try:
                hexs = instant_replay_paketi(conn, bas, R.SURE_MS, odak).hex()
                ok = replay_gonder(cl, bas, R.SURE_MS, odak)
            except Exception as e:
                hexs, ok = "-", f"HATA {e!r}"
            R.bip(i)
            R.log(f"GONDER #{i} {ad}: now_ms={now} bas={bas} odak={odak} sonuc={ok} hex={hexs}")
            time.sleep(4.0)
            R.log("  +4s: " + durum(cl))
            S.ekran(f"{i}_{ad.split()[0]}.jpg".replace("(", "").replace(")", ""))
            time.sleep(8.0)
        R.log("BITTI")
        R.bip(3, 1200)
        return 0
    finally:
        cl.stop()


if __name__ == "__main__":
    raise SystemExit(main())
