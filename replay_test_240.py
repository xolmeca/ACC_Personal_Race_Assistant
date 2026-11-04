"""240 sn otomatik replay testi. Proje kokunden: python replay_test_240.py
Girdi yok. ACC'de oturum acik olsun. Yarista calistirma."""
from __future__ import annotations

import time

from modules.acc.acc_broadcasting_client import (BroadcastingClient, ayar_yukle,
                                                  track_data_istek_paketi)
from modules.acc.acc_replay_controller import instant_replay_paketi, replay_gonder

TOPLAM_SN = 240.0
PENCERE_SN = 40.0
SURE_MS = 10000.0
DENEMELER = [(20.0, 0.0), (80.0, 5.0), (140.0, 30.0), (200.0, 0.0)]
IZLENEN = ("replay", "odak_arac_id", "kamera_seti", "kamera", "faz_adi")


def _oturum(cl) -> dict:
    o = cl.oturum
    o = o() if callable(o) else o
    return dict(vars(o)) if hasattr(o, "__dict__") else {}


def main() -> int:
    cl = BroadcastingClient(ayar_yukle())
    if not cl.start():
        print("BAGLANTI YOK:", cl.son_hata)
        return 2
    try:
        if cl.salt_okunur is not False:
            print("KOMUT YETKISI YOK (salt_okunur =", cl.salt_okunur, ")")
            return 3
        conn = getattr(cl, "_conn_id", None)
        cl._gonder(track_data_istek_paketi(conn))
        time.sleep(2.0)
        t_son = time.monotonic() + 4.0
        while not cl.cars_snapshot() and time.monotonic() < t_son:
            time.sleep(0.2)
        ids = [a.car_id for a in cl.cars_snapshot()]
        odak = ids[0] if ids else -1
        print("arac idleri:", ids, "| odak:", odak)

        d = _oturum(cl)
        son = {k: d.get(k) for k in IZLENEN}
        print("TABAN:", son)
        if all(v is None for v in son.values()):
            print("UYARI: oturum alanlari okunamadi, karar guvenilmez")

        gonderilen, degisim = [], []
        i, nabiz = 0, 0.0
        t0 = time.monotonic()
        while True:
            gecen = time.monotonic() - t0
            if gecen >= TOPLAM_SN:
                break
            if i < len(DENEMELER) and gecen >= DENEMELER[i][0]:
                bas = DENEMELER[i][1]
                try:
                    hexs = instant_replay_paketi(conn, bas, SURE_MS, odak).hex()
                    ok = replay_gonder(cl, bas, SURE_MS, odak)
                except Exception as e:
                    hexs, ok = "-", f"HATA {e!r}"
                print(f"[{gecen:5.0f}s] GONDER #{i+1} bas={bas} sonuc={ok} "
                      f"hata={getattr(cl, 'son_hata', None)} hex={hexs}")
                gonderilen.append(gecen)
                i += 1
            d = _oturum(cl)
            cur = {k: d.get(k) for k in IZLENEN}
            if cur != son:
                fark = {k: (son[k], cur[k]) for k in IZLENEN if cur[k] != son[k]}
                print(f"[{gecen:5.0f}s] DEGISTI: {fark}")
                degisim.append(gecen)
                son = cur
            if gecen >= nabiz:
                print(f"[{gecen:5.0f}s] nabiz: sess_ms={d.get('session_zamani_ms')} "
                      f"kamera={d.get('kamera')} replay={d.get('replay')}")
                nabiz += 20.0
            time.sleep(0.5)

        ilgili = [t for t in degisim
                  if any(g <= t < g + PENCERE_SN for g in gonderilen)]
        print("-" * 40)
        if ilgili:
            print("KARAR: paket sonrasi ACC durumu degisti -> replay MUHTEMELEN basladi")
        else:
            print("KARAR: BASLAMADI -> paket sonrasi izlenen hicbir alan degismedi")
        print("Not: replay bayragi deneme oncesi de True idi, karar zayif olabilir.")
        return 0
    finally:
        cl.stop()


if __name__ == "__main__":
    raise SystemExit(main())
