# -*- coding: utf-8 -*-
"""recording_controller: Yaris SONRASI klip kaydi akisi.
Kural 3: ACC canliyken (status 2) veya duraklatilmisken (status 3) kayit BASLATILMAZ.
status degeri disaridan verilir (okuma main.py'nin isi), boylece ACC kapaliyken de test edilir."""
import os
import shutil
import sys
import tempfile
import time

try:
    from modules.obs.clip_naming import klip_dosya_adi, proje_klasor_adi
    from modules.obs.obs_websocket_client import ObsHata, ObsIstemci, env_dosyasindan
except ImportError:
    from clip_naming import klip_dosya_adi, proje_klasor_adi
    from obs_websocket_client import ObsHata, ObsIstemci, env_dosyasindan

# acc_shared_memory_reader.py satir 29 ile ayni (kopya: bagimlilik olmasin diye)
DURUM_ADLARI = {0: "AC_OFF", 1: "AC_REPLAY", 2: "AC_LIVE", 3: "AC_PAUSE"}
IZINLI_DURUMLAR = (0, 1)


def kayit_izinli_mi(status):
    """SAF. (izinli_mi, sebep). Bilinmeyen/gecersiz status guvenlik icin ENGELLENIR."""
    if isinstance(status, bool) or not isinstance(status, int):
        return False, f"status bilinmiyor ({status!r}): guvenlik icin engellendi"
    if status in IZINLI_DURUMLAR:
        return True, ""
    ad = DURUM_ADLARI.get(status, "BILINMIYOR")
    return False, f"status={status} ({ad}): yaris sirasinda kayit yasak (Kural 3)"


def uzanti_bul(kaynak_yol):
    """SAF. OBS dosyasinin gercek uzantisi (sahte .mp4 adlandirmasi yapilmaz); bulunamazsa mp4."""
    ext = os.path.splitext(str(kaynak_yol))[1].lstrip(".")
    return ext.lower() if ext.isalnum() else "mp4"


def hedef_yol(klip_kok, proje_no, klip_no, kamera, uzanti):
    """SAF. <klip_kok>/Proje_N/Proje_N_Klip_M_Kamera.<uzanti>; gecersiz girdide ValueError."""
    return os.path.join(klip_kok, proje_klasor_adi(proje_no),
                        klip_dosya_adi(proje_no, klip_no, kamera, uzanti))


def ayar_oku(ayar):
    """SAF. settings sozlugunden 'obs' bolumunu okur; eksik anahtarlar icin varsayilan."""
    o = ayar.get("obs") if isinstance(ayar, dict) else None
    o = o if isinstance(o, dict) else {}
    return {"host": o.get("host", "localhost"),
            "port": o.get("port", 4455),
            "klip_klasoru": o.get("klip_klasoru", os.path.join("data", "clips"))}


class KayitKontrolcu:
    def __init__(self, obs, klip_kok, tasima_deneme=5, bekleme_sn=1.0, uyku=time.sleep, tasi=shutil.move):
        if obs is None:
            raise ValueError("obs istemcisi gerekli")
        if not isinstance(klip_kok, str) or not klip_kok.strip():
            raise ValueError("klip_kok gecersiz")
        if isinstance(tasima_deneme, bool) or not isinstance(tasima_deneme, int) or tasima_deneme < 1:
            raise ValueError("tasima_deneme >= 1 olmali")
        self._obs, self._kok = obs, klip_kok
        self._deneme, self._bekleme, self._uyku, self._tasi = tasima_deneme, bekleme_sn, uyku, tasi

    def kayit_baslat(self, status):
        """(ok, mesaj). Engelliyse OBS'e HIC istek gitmez."""
        ok, sebep = kayit_izinli_mi(status)
        if not ok:
            return False, sebep
        try:
            self._obs.kayit_baslat()
        except ObsHata as e:
            return False, f"OBS hatasi: {e}"
        return True, "kayit baslatildi"

    def kayit_durdur_ve_tasi(self, proje_no, klip_no, kamera):
        """(ok, hedef_yol | hata). Adi ONCE dogrular; boylece kayit yetim kalmaz."""
        try:
            hedef_yol(self._kok, proje_no, klip_no, kamera, "mp4")
        except ValueError as e:
            return False, f"gecersiz ad (kayit durdurulmadi): {e}"
        try:
            kaynak = self._obs.kayit_durdur()
        except ObsHata as e:
            return False, f"OBS hatasi: {e}"
        hedef = hedef_yol(self._kok, proje_no, klip_no, kamera, uzanti_bul(kaynak))
        return self._tasi_dene(kaynak, hedef)

    def _tasi_dene(self, kaynak, hedef):
        """I/O. Hedef varsa uzerine YAZMAZ. OBS dosyayi kapatana kadar yeniden dener."""
        if os.path.exists(hedef):
            return False, f"hedef zaten var, uzerine yazilmadi: {hedef}; kaynak: {kaynak}"
        son = ""
        for i in range(self._deneme):
            try:
                if not os.path.isfile(kaynak):
                    son = "kaynak dosya yok"
                else:
                    os.makedirs(os.path.dirname(hedef), exist_ok=True)
                    self._tasi(kaynak, hedef)
                    return True, hedef
            except OSError as e:
                son = str(e)
            if i < self._deneme - 1:
                self._uyku(self._bekleme)
        return False, f"tasinamadi ({son}); kaynak: {kaynak}"


class _SahteObs:
    def __init__(self, yol="", hata_baslat=False, hata_durdur=False):
        self.yol, self.hata_baslat, self.hata_durdur = yol, hata_baslat, hata_durdur
        self.baslat, self.durdur = 0, 0

    def kayit_baslat(self):
        self.baslat += 1
        if self.hata_baslat:
            raise ObsHata("sahte baslat hatasi")

    def kayit_durdur(self):
        self.durdur += 1
        if self.hata_durdur:
            raise ObsHata("sahte durdur hatasi")
        return self.yol


def _yaz(yol, icerik=b"x"):
    os.makedirs(os.path.dirname(yol), exist_ok=True)
    with open(yol, "wb") as f:
        f.write(icerik)


def _selftest():
    sonuc = []

    def k(ad, ok):
        sonuc.append(bool(ok))
        print(("TAMAM  " if ok else "HATA   ") + ad)

    k("status 0 izinli", kayit_izinli_mi(0)[0] is True)
    k("status 1 izinli", kayit_izinli_mi(1)[0] is True)
    k("status 2 AC_LIVE engelli", kayit_izinli_mi(2)[0] is False)
    k("status 3 AC_PAUSE engelli", kayit_izinli_mi(3)[0] is False)
    k("status 7 bilinmeyen engelli", kayit_izinli_mi(7)[0] is False)
    k("status None engelli", kayit_izinli_mi(None)[0] is False)
    k("status bool engelli", kayit_izinli_mi(True)[0] is False)
    k("uzanti mkv korunur", uzanti_bul("C:\\v\\a.MKV") == "mkv")
    k("uzanti yoksa mp4", uzanti_bul("C:\\v\\a") == "mp4")
    k("ayar varsayilan", ayar_oku({})["port"] == 4455 and ayar_oku(None)["host"] == "localhost")
    k("ayar override", ayar_oku({"obs": {"port": 4466}})["port"] == 4466)
    k("hedef_yol saf", hedef_yol("k", 2, 1, "TV1", "mp4") == os.path.join("k", "Proje_2", "Proje_2_Klip_1_TV1.mp4"))

    with tempfile.TemporaryDirectory() as t:
        kok, kay = os.path.join(t, "clips"), os.path.join(t, "obs_out")
        src = os.path.join(kay, "rec.mp4")
        _yaz(src)
        obs = _SahteObs(yol=src)
        c = KayitKontrolcu(obs, kok, uyku=lambda s: None)
        ok, _ = c.kayit_baslat(2)
        k("AC_LIVE'da baslat reddedildi, OBS'e istek gitmedi", ok is False and obs.baslat == 0)
        ok, _ = c.kayit_baslat(3)
        k("AC_PAUSE'da baslat reddedildi, OBS'e istek gitmedi", ok is False and obs.baslat == 0)
        ok, _ = c.kayit_baslat(0)
        k("AC_OFF'ta baslat OBS'e gitti", ok is True and obs.baslat == 1)
        ok, bilgi = c.kayit_durdur_ve_tasi(2, 1, "TV1")
        bek = os.path.join(kok, "Proje_2", "Proje_2_Klip_1_TV1.mp4")
        k("dosya yeniden adlandirilip tasindi", ok and bilgi == bek and os.path.isfile(bek) and not os.path.exists(src))

        src2 = os.path.join(kay, "rec2.mkv")
        _yaz(src2)
        c2 = KayitKontrolcu(_SahteObs(yol=src2), kok, uyku=lambda s: None)
        ok, bilgi = c2.kayit_durdur_ve_tasi(2, 2, "Hood")
        k("mkv uzantisi korunur", ok and bilgi.endswith("Proje_2_Klip_2_Hood.mkv"))

    print(f"SELFTEST: {sum(sonuc)}/{len(sonuc)}")
    return all(sonuc)


def _badtest():
    sonuc = []

    def k(ad, ok):
        sonuc.append(bool(ok))
        print(("TAMAM  " if ok else "HATA   ") + ad)

    def reddet(ad, f):
        try:
            f()
            ok = False
        except ValueError:
            ok = True
        k(ad, ok)

    k("status metin '2' engelli", kayit_izinli_mi("2")[0] is False)
    reddet("obs None", lambda: KayitKontrolcu(None, "k"))
    reddet("klip_kok bos", lambda: KayitKontrolcu(_SahteObs(), ""))
    reddet("tasima_deneme 0", lambda: KayitKontrolcu(_SahteObs(), "k", tasima_deneme=0))

    with tempfile.TemporaryDirectory() as t:
        kok, kay = os.path.join(t, "clips"), os.path.join(t, "obs_out")
        sus = lambda s: None

        src = os.path.join(kay, "a.mp4")
        _yaz(src)
        mevcut = os.path.join(kok, "Proje_1", "Proje_1_Klip_1_TV1.mp4")
        _yaz(mevcut, b"ESKI")
        ok, _ = KayitKontrolcu(_SahteObs(yol=src), kok, uyku=sus).kayit_durdur_ve_tasi(1, 1, "TV1")
        with open(mevcut, "rb") as f:
            eski = f.read()
        k("hedef varsa uzerine yazilmaz, kaynak korunur", ok is False and eski == b"ESKI" and os.path.isfile(src))

        ok, _ = KayitKontrolcu(_SahteObs(yol=os.path.join(kay, "yok.mp4")), kok, uyku=sus).kayit_durdur_ve_tasi(1, 5, "TV1")
        k("kaynak dosya yok -> hata", ok is False)

        obs = _SahteObs(yol=src)
        ok, _ = KayitKontrolcu(obs, kok, uyku=sus).kayit_durdur_ve_tasi(0, 1, "TV1")
        k("gecersiz proje_no: hata ve kayit durdurulmadi", ok is False and obs.durdur == 0)
        ok, _ = KayitKontrolcu(obs, kok, uyku=sus).kayit_durdur_ve_tasi(1, 1, "///")
        k("gecersiz kamera: hata ve kayit durdurulmadi", ok is False and obs.durdur == 0)

        ok, _ = KayitKontrolcu(_SahteObs(hata_durdur=True), kok, uyku=sus).kayit_durdur_ve_tasi(1, 2, "TV1")
        k("OBS durdur hatasi -> (False, ...)", ok is False)
        ok, _ = KayitKontrolcu(_SahteObs(hata_baslat=True), kok, uyku=sus).kayit_baslat(0)
        k("OBS baslat hatasi -> (False, ...)", ok is False)

        sayac = {"n": 0}

        def kilitli(a, b):
            sayac["n"] += 1
            raise PermissionError("dosya kilitli")
        ok, _ = KayitKontrolcu(_SahteObs(yol=src), kok, tasima_deneme=3, uyku=sus, tasi=kilitli).kayit_durdur_ve_tasi(1, 3, "TV1")
        k("kilitli dosya: tam 3 deneme sonra hata", ok is False and sayac["n"] == 3)

        src4 = os.path.join(kay, "b.mp4")
        _yaz(src4)
        ok, bilgi = KayitKontrolcu(_SahteObs(yol=src4), kok, uyku=sus).kayit_durdur_ve_tasi(1, 4, "..\\..\\x")
        k("yol kacisi: dosya klip klasoru disina cikmaz", ok and os.path.dirname(bilgi) == os.path.join(kok, "Proje_1"))

    print(f"BADTEST: {sum(sonuc)}/{len(sonuc)}")
    return all(sonuc)


def _canli(argv):
    """GERCEK OBS: ~3 sn kayit + tasima. Yaris disinda, ACC kapaliyken. Gecici klasore tasir, sonra siler."""
    kok = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        status = int(argv[argv.index("--status") + 1])
    except (ValueError, IndexError):
        print("Kullanim: python -m modules.obs.recording_controller --canli --status 0")
        return False
    izin, sebep = kayit_izinli_mi(status)
    if not izin:
        print("ENGELLENDI:", sebep)
        return False
    obs = ObsIstemci(sifre=env_dosyasindan(os.path.join(kok, ".env"), "OBS_WS_PASSWORD") or "")
    gecici = tempfile.mkdtemp(prefix="acc_canli_")
    log = []

    def sayacli_tasi(a, b):
        try:
            shutil.move(a, b)
            log.append("OK")
        except OSError as e:
            log.append(f"HATA: {e}")
            raise

    try:
        obs.baglan()
        if obs.kayit_aktif_mi():
            print("OBS zaten kayit yapiyor; test iptal edildi")
            return False
        kc = KayitKontrolcu(obs, gecici, tasima_deneme=10, bekleme_sn=1.0, tasi=sayacli_tasi)
        ok, msg = kc.kayit_baslat(status)
        print("baslat:", ok, msg)
        if not ok:
            return False
        time.sleep(1.0)
        print("kayit aktif mi (baslattiktan sonra):", obs.kayit_aktif_mi())
        time.sleep(2.0)
        t0 = time.time()
        ok, bilgi = kc.kayit_durdur_ve_tasi(9999, 1, "TEST")
        print("durdur+tasi:", ok, bilgi)
        print(f"sure: {time.time() - t0:.1f} sn | tasima denemeleri: {log}")
        if not ok:
            return False
        boyut = os.path.getsize(bilgi)
        print("dosya boyutu (bayt):", boyut, "| uzanti:", os.path.splitext(bilgi)[1])
        return boyut > 0
    except ObsHata as e:
        print("OBS HATASI:", e)
        return False
    finally:
        try:
            if obs.kayit_aktif_mi():
                print("UYARI: kayit acik kalmisti, durduruldu:", obs.kayit_durdur())
        except Exception:
            pass
        obs.kapat()
        shutil.rmtree(gecici, ignore_errors=True)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
    if "--badtest" in sys.argv:
        sys.exit(0 if _badtest() else 1)
    if "--canli" in sys.argv:
        sys.exit(0 if _canli(sys.argv) else 1)
    print("Kullanim: python -m modules.obs.recording_controller --selftest | --badtest | --canli --status 0")