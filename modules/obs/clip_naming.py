# -*- coding: utf-8 -*-
"""clip_naming: Klip klasör/dosya adı üretimi. SAF fonksiyonlar, disk/ağ yok."""
import re
import sys

_YASAK = re.compile(r"[^A-Za-z0-9]+")


def _pozitif_int(deger, ad):
    """Pozitif tam sayı doğrular (bool kabul edilmez)."""
    if isinstance(deger, bool) or not isinstance(deger, int) or deger < 1:
        raise ValueError(f"{ad} pozitif tam sayı olmalı: {deger!r}")
    return deger


def kamera_temizle(kamera):
    """Kamera adını dosya adı için güvenli hale getirir (yol karakterleri temizlenir)."""
    if not isinstance(kamera, str):
        raise ValueError(f"kamera metin olmalı: {kamera!r}")
    temiz = _YASAK.sub("_", kamera.strip()).strip("_")
    if not temiz:
        raise ValueError(f"kamera adı boş/geçersiz: {kamera!r}")
    return temiz


def proje_klasor_adi(proje_no):
    """Örn. 3 -> 'Proje_3'."""
    return f"Proje_{_pozitif_int(proje_no, 'proje_no')}"


def klip_dosya_adi(proje_no, klip_no, kamera, uzanti="mp4"):
    """Örn. (3, 2, 'TV1') -> 'Proje_3_Klip_2_TV1.mp4'."""
    p = _pozitif_int(proje_no, "proje_no")
    k = _pozitif_int(klip_no, "klip_no")
    cam = kamera_temizle(kamera)
    if not isinstance(uzanti, str) or not uzanti.isalnum():
        raise ValueError(f"uzanti geçersiz: {uzanti!r}")
    return f"Proje_{p}_Klip_{k}_{cam}.{uzanti.lower()}"


def _selftest():
    sonuc = []

    def kontrol(ad, ok):
        sonuc.append(ok)
        print(("TAMAM  " if ok else "HATA   ") + ad)

    kontrol("klasor adi", proje_klasor_adi(3) == "Proje_3")
    kontrol("dosya adi", klip_dosya_adi(3, 2, "TV1") == "Proje_3_Klip_2_TV1.mp4")
    kontrol("kamera bosluk/tire", klip_dosya_adi(1, 1, " Hood-Cam ") == "Proje_1_Klip_1_Hood_Cam.mp4")
    kontrol("yol kacisi temizlenir", klip_dosya_adi(1, 1, "..\\x/y") == "Proje_1_Klip_1_x_y.mp4")
    kontrol("uzanti kucuk harf", klip_dosya_adi(1, 1, "Chase", "MP4").endswith(".mp4"))
    kontrol("saflik (ayni girdi ayni cikti)", klip_dosya_adi(5, 9, "Cockpit") == klip_dosya_adi(5, 9, "Cockpit"))
    print(f"SELFTEST: {sum(sonuc)}/{len(sonuc)}")
    return all(sonuc)


def _badtest():
    sonuc = []
    kotu = [
        lambda: klip_dosya_adi(0, 1, "TV1"),
        lambda: klip_dosya_adi(1, -1, "TV1"),
        lambda: klip_dosya_adi(True, 1, "TV1"),
        lambda: klip_dosya_adi("1", 1, "TV1"),
        lambda: klip_dosya_adi(1, 1, ""),
        lambda: klip_dosya_adi(1, 1, "///"),
        lambda: klip_dosya_adi(1, 1, None),
        lambda: klip_dosya_adi(1, 1, "TV1", "m/p4"),
        lambda: proje_klasor_adi(None),
    ]
    for i, f in enumerate(kotu, 1):
        try:
            f()
            ok = False
        except ValueError:
            ok = True
        sonuc.append(ok)
        print(("TAMAM  " if ok else "HATA   ") + f"kotu girdi {i} reddedildi")
    print(f"BADTEST: {sum(sonuc)}/{len(sonuc)}")
    return all(sonuc)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
    if "--badtest" in sys.argv:
        sys.exit(0 if _badtest() else 1)
    print("Kullanim: python modules\\obs\\clip_naming.py --selftest | --badtest")