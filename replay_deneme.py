"""Gercek ACC ile InstantReplayRequest denemesi. Proje kokunden: python replay_deneme.py
Amac: komut yetkisi, pist verisi, odak araci ve replay paketini gercekte dogrulamak.
Yarista calistirma; replay ekranda gorunecek.
"""
from __future__ import annotations

import time

from modules.acc.acc_broadcasting_client import (BroadcastingClient, ayar_yukle,
                                                  track_data_istek_paketi)
from modules.acc.acc_replay_controller import instant_replay_paketi, replay_gonder


def _sayi(metin: str, varsayilan: float) -> float:
    metin = metin.strip()
    return varsayilan if not metin else float(metin.replace(",", "."))


def main() -> int:
    cl = BroadcastingClient(ayar_yukle())
    if not cl.start():
        print("BAGLANTI YOK:", cl.son_hata)
        return 2
    try:
        print("1) salt_okunur =", cl.salt_okunur)
        if cl.salt_okunur is not False:
            print("   Komut yetkisi YOK. settings.json command_password ACC'deki ile ayni olmali.")
            return 3

        conn = getattr(cl, "_conn_id", None)
        cl._gonder(track_data_istek_paketi(conn))
        time.sleep(2.0)
        pist = getattr(cl, "_pist", None)
        if pist is None:
            print("2) PIST VERISI GELMEDI (REQUEST_TRACK_DATA yaniti yok)")
        else:
            print("2) pist:", pist.uzunluk_m, "m | kamera_setleri:", pist.kamera_setleri,
                  "| hud:", pist.hud_sayfalari)

        t_son = time.monotonic() + 4.0
        while not cl.cars_snapshot() and time.monotonic() < t_son:
            time.sleep(0.2)
        araclar = cl.cars_snapshot()
        ids = [a.car_id for a in araclar]
        print("3) arac sayisi:", len(ids), "| ilk idler:", ids[:6])

        o = cl.oturum
        o = o() if callable(o) else o
        print("4) oturum:", vars(o) if hasattr(o, "__dict__") else o)

        print("\nReplay icin degerleri gir (Enter = varsayilan).")
        bas = _sayi(input("Baslangic, oturum zamani sn [0]: "), 0.0)
        sure = _sayi(input("Sure ms [10000]: "), 10000.0)
        odak = int(_sayi(input(f"Odak arac id [{ids[0] if ids else -1}]: "),
                         ids[0] if ids else -1))
        print(f"\nGonderilecek: baslangic={bas} sure_ms={sure} odak={odak}")
        print("Paket (hex):", instant_replay_paketi(conn, bas, sure, odak).hex())
        input("Enter ile gonder, iptal icin Ctrl+C... ")
        sonuc = replay_gonder(cl, bas, sure, odak)
        print("5) gonderim sonucu:", sonuc)
        time.sleep(3.0)
        print("   ACC'de replay basladi mi? Ekrana bak, sonucu bana yaz.")
        return 0
    finally:
        cl.stop()


if __name__ == "__main__":
    raise SystemExit(main())
