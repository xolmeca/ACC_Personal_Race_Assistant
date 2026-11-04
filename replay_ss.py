"""Replay + ekran goruntusu denemesi. python replay_ss.py
ACC oturumunda araci pistte tut. Sonuc: replay_ss_log.txt + ekran_goruntuleri\\ klasoru."""
from __future__ import annotations

import os
import time

import replay_oto as R
from modules.acc.acc_broadcasting_client import track_data_istek_paketi
from modules.acc.acc_replay_controller import instant_replay_paketi, replay_gonder

R.LOG = "replay_ss_log.txt"
KLASOR = "ekran_goruntuleri"
DENEMELER = [(42.0, "", ""), (42000.0, "", ""),
             (30000.0, "Drivable", "Chase"), (60000.0, "Drivable", "Chase")]


def ekran(ad: str) -> None:
    try:
        from PIL import ImageGrab
        os.makedirs(KLASOR, exist_ok=True)
        im = ImageGrab.grab()
        im.thumbnail((1280, 720))
        yol = os.path.join(KLASOR, ad)
        im.convert("RGB").save(yol, quality=70)
        R.log(f"  ekran kaydedildi: {yol}")
    except Exception as e:
        R.log(f"  EKRAN ALINAMADI: {e!r}")


def main() -> int:
    open(R.LOG, "w").close()
    R.log("BASLADI. ACC oturumuna gir, araci pistte tut.")
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
        time.sleep(8.0)
        ids = [a.car_id for a in cl.cars_snapshot()]
        d = R.oturum(cl)
        R.log(f"arac idleri: {ids} | oturum: sess_ms={d.get('session_zamani_ms')} "
              f"kamera={d.get('kamera')} replay={d.get('replay')} faz={d.get('faz_adi')}")
        ekran("0_taban.jpg")
        for i, (bas, cs, kam) in enumerate(DENEMELER, 1):
            ids = [a.car_id for a in cl.cars_snapshot()]
            odak = ids[0] if ids else int(R.oturum(cl).get("odak_arac_id") or 0)
            try:
                hexs = instant_replay_paketi(conn, bas, R.SURE_MS, odak, cs, kam).hex()
                ok = replay_gonder(cl, bas, R.SURE_MS, odak, cs, kam)
            except Exception as e:
                hexs, ok = "-", f"HATA {e!r}"
            R.bip(i)
            R.log(f"GONDER #{i} bas={bas} set={cs!r} kam={kam!r} odak={odak} sonuc={ok} hex={hexs}")
            time.sleep(4.0)
            d = R.oturum(cl)
            R.log(f"  +4s: replay={d.get('replay')} kamera={d.get('kamera')} "
                  f"sess_ms={d.get('session_zamani_ms')} faz={d.get('faz_adi')}")
            ekran(f"{i}_bas{int(bas)}.jpg")
            time.sleep(8.0)
        R.log("BITTI")
        R.bip(3, 1200)
        return 0
    finally:
        cl.stop()


if __name__ == "__main__":
    raise SystemExit(main())
