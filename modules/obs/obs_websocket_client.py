# -*- coding: utf-8 -*-
"""obs_websocket_client: OBS WebSocket v5 istemcisi (yalnizca yerel, localhost).
Saf yardimcilar (kimlik, istek/yanit) ile I/O (soket) ayridir; soket fabrikasi enjekte edilebilir.
Bu modul yaris kontrolu YAPMAZ; AC_LIVE engeli recording_controller'dadir."""
import base64
import hashlib
import json
import sys

OP_HELLO, OP_IDENTIFY, OP_IDENTIFIED, OP_EVENT, OP_REQUEST, OP_RESPONSE = 0, 1, 2, 5, 6, 7
_MAX_MESAJ = 200


class ObsHata(Exception):
    """OBS baglanti/protokol/istek hatasi."""


def kimlik_dizesi(sifre, salt, challenge):
    """SAF. v5 kimlik: b64(sha256(sifre+salt)) -> b64(sha256(secret+challenge))."""
    for ad, d in (("sifre", sifre), ("salt", salt), ("challenge", challenge)):
        if not isinstance(d, str):
            raise ValueError(f"{ad} metin olmali")
    secret = base64.b64encode(hashlib.sha256((sifre + salt).encode("utf-8")).digest()).decode("ascii")
    return base64.b64encode(hashlib.sha256((secret + challenge).encode("utf-8")).digest()).decode("ascii")


def istek_kur(istek_tipi, istek_id, veri=None):
    """SAF. Request (op 6) JSON metni uretir."""
    if not isinstance(istek_tipi, str) or not istek_tipi.strip():
        raise ValueError("istek_tipi bos olamaz")
    if not isinstance(istek_id, str) or not istek_id:
        raise ValueError("istek_id bos olamaz")
    d = {"requestType": istek_tipi, "requestId": istek_id}
    if veri:
        d["requestData"] = veri
    return json.dumps({"op": OP_REQUEST, "d": d})


def yanit_ayikla(mesaj):
    """SAF. RequestResponse d-sozlugunden (ok, responseData, hata_metni) dondurur."""
    d = mesaj.get("d") if isinstance(mesaj, dict) else None
    if not isinstance(d, dict):
        return False, {}, "yanitta d yok"
    durum = d.get("requestStatus")
    if not isinstance(durum, dict):
        return False, {}, "requestStatus yok"
    if durum.get("result") is True:
        rd = d.get("responseData")
        return True, (rd if isinstance(rd, dict) else {}), ""
    return False, {}, f"kod={durum.get('code')} {durum.get('comment', '')}".strip()


def env_oku(metin, anahtar):
    """SAF. .env metninden ANAHTAR=deger okur; yoksa None."""
    if not isinstance(metin, str):
        return None
    for satir in metin.splitlines():
        s = satir.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip() == anahtar:
            return v.strip().strip('"').strip("'")
    return None


def env_dosyasindan(yol, anahtar):
    """I/O. .env dosyasindan anahtari okur; dosya yoksa/okunamazsa None."""
    try:
        with open(yol, "r", encoding="utf-8") as f:
            return env_oku(f.read(), anahtar)
    except OSError:
        return None


def _varsayilan_fabrika(url, zaman_asimi):
    import websocket  # websocket-client
    return websocket.create_connection(url, timeout=zaman_asimi, subprotocols=["obswebsocket.json"])


class ObsIstemci:
    def __init__(self, host="localhost", port=4455, sifre="", zaman_asimi=5, fabrika=None):
        if not isinstance(host, str) or not host.strip():
            raise ValueError("host gecersiz")
        if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
            raise ValueError("port gecersiz")
        self.url = f"ws://{host}:{port}"
        self._sifre = sifre or ""
        self._zaman_asimi = zaman_asimi
        self._fabrika = fabrika or _varsayilan_fabrika
        self._ws = None
        self._sayac = 0

    def _al(self):
        try:
            ham = self._ws.recv()
            m = json.loads(ham)
        except (ValueError, TypeError) as e:
            raise ObsHata(f"gecersiz JSON: {e}")
        except Exception as e:
            raise ObsHata(f"alma hatasi: {e}")
        if not isinstance(m, dict):
            raise ObsHata("mesaj sozluk degil")
        return m

    def baglan(self):
        try:
            self._ws = self._fabrika(self.url, self._zaman_asimi)
        except Exception as e:
            self._ws = None
            raise ObsHata(f"baglanamadi ({self.url}): {e}")
        try:
            hello = self._al()
            if hello.get("op") != OP_HELLO or not isinstance(hello.get("d"), dict):
                raise ObsHata("ilk mesaj Hello degil")
            hd = hello["d"]
            kimlik = {"rpcVersion": hd.get("rpcVersion", 1)}
            auth = hd.get("authentication")
            if isinstance(auth, dict):
                if not self._sifre:
                    raise ObsHata("OBS sifre istiyor ama OBS_WS_PASSWORD bos")
                kimlik["authentication"] = kimlik_dizesi(
                    self._sifre, str(auth.get("salt", "")), str(auth.get("challenge", "")))
            self._ws.send(json.dumps({"op": OP_IDENTIFY, "d": kimlik}))
            yanit = self._al()
            if yanit.get("op") != OP_IDENTIFIED:
                raise ObsHata("Identified alinamadi (sifre yanlis olabilir)")
        except ObsHata:
            self.kapat()
            raise

    def kapat(self):
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:
            pass
        self._ws = None

    def istek(self, istek_tipi, veri=None):
        """Istek gonderir, responseData sozlugunu dondurur; hata olursa ObsHata."""
        if self._ws is None:
            raise ObsHata("baglanti yok")
        self._sayac += 1
        rid = f"acc-{self._sayac}"
        try:
            self._ws.send(istek_kur(istek_tipi, rid, veri))
        except ValueError:
            raise
        except Exception as e:
            raise ObsHata(f"gonderme hatasi: {e}")
        for _ in range(_MAX_MESAJ):
            m = self._al()
            if m.get("op") == OP_RESPONSE and isinstance(m.get("d"), dict) and m["d"].get("requestId") == rid:
                ok, veri_, hata = yanit_ayikla(m)
                if not ok:
                    raise ObsHata(f"{istek_tipi} basarisiz: {hata}")
                return veri_
        raise ObsHata(f"{istek_tipi} icin yanit gelmedi")

    def kayit_baslat(self):
        self.istek("StartRecord")

    def kayit_durdur(self):
        """StopRecord; kaydedilen dosyanin yolunu (outputPath) dondurur."""
        yol = self.istek("StopRecord").get("outputPath")
        if not isinstance(yol, str) or not yol:
            raise ObsHata("StopRecord yanitinda outputPath yok")
        return yol

    def kayit_aktif_mi(self):
        return bool(self.istek("GetRecordStatus").get("outputActive", False))


class _Sahte:
    """Test icin sahte soket."""
    def __init__(self, gelen):
        self.gelen, self.giden, self.kapali = list(gelen), [], False

    def send(self, m):
        self.giden.append(json.loads(m))

    def recv(self):
        if not self.gelen:
            raise ConnectionError("bos")
        x = self.gelen.pop(0)
        if isinstance(x, Exception):
            raise x
        return x if isinstance(x, str) else json.dumps(x)

    def close(self):
        self.kapali = True


def _hello(auth=True):
    d = {"obsWebSocketVersion": "5.5.2", "rpcVersion": 1}
    if auth:
        d["authentication"] = {"challenge": "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY=",
                               "salt": "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI="}
    return {"op": 0, "d": d}


def _yanit(rid, tip, ok=True, veri=None, kod=100):
    d = {"requestType": tip, "requestId": rid, "requestStatus": {"result": ok, "code": kod}}
    if veri is not None:
        d["responseData"] = veri
    return {"op": 7, "d": d}


def _istemci(gelen, sifre="supersecretpassword"):
    s = _Sahte(gelen)
    return ObsIstemci(sifre=sifre, fabrika=lambda url, t: s), s


def _selftest():
    sonuc = []

    def k(ad, ok):
        sonuc.append(bool(ok))
        print(("TAMAM  " if ok else "HATA   ") + ad)

    salt, ch = _hello()["d"]["authentication"]["salt"], _hello()["d"]["authentication"]["challenge"]
    sec = base64.b64encode(hashlib.sha256(("supersecretpassword" + salt).encode()).digest()).decode()
    beklenen = base64.b64encode(hashlib.sha256((sec + ch).encode()).digest()).decode()
    k("kimlik_dizesi bagimsiz hesapla ayni", kimlik_dizesi("supersecretpassword", salt, ch) == beklenen)
    k("kimlik 44 karakter base64", len(beklenen) == 44)
    j = json.loads(istek_kur("StartRecord", "acc-1"))
    k("istek_kur op 6 + alanlar", j["op"] == 6 and j["d"]["requestType"] == "StartRecord" and j["d"]["requestId"] == "acc-1")
    k("yanit_ayikla ok", yanit_ayikla(_yanit("a", "X", True, {"outputPath": "p"})) == (True, {"outputPath": "p"}, ""))
    k("yanit_ayikla hata", yanit_ayikla(_yanit("a", "X", False, kod=500))[0] is False)
    k("env_oku", env_oku("# c\nOBS_WS_PASSWORD='abc'\nX=1", "OBS_WS_PASSWORD") == "abc")
    k("env_oku yok", env_oku("X=1", "OBS_WS_PASSWORD") is None)

    c, s = _istemci([_hello(True), {"op": 2, "d": {"negotiatedRpcVersion": 1}}])
    c.baglan()
    k("Identify op 1 + dogru authentication", s.giden[0]["op"] == 1 and s.giden[0]["d"]["authentication"] == beklenen)

    c, s = _istemci([_hello(False), {"op": 2, "d": {}}], sifre="")
    c.baglan()
    k("sifresiz OBS: authentication alani yok", "authentication" not in s.giden[0]["d"])

    c, s = _istemci([_hello(False), {"op": 2, "d": {}}, _yanit("acc-1", "StartRecord")], sifre="")
    c.baglan(); c.kayit_baslat()
    k("kayit_baslat istegi gonderildi", s.giden[1]["d"]["requestType"] == "StartRecord")

    c, s = _istemci([_hello(False), {"op": 2, "d": {}}, {"op": 5, "d": {"eventType": "X"}},
                     _yanit("acc-1", "StopRecord", True, {"outputPath": "C:/v/a.mkv"})], sifre="")
    c.baglan()
    k("kayit_durdur outputPath (olay atlanir)", c.kayit_durdur() == "C:/v/a.mkv")

    c, s = _istemci([_hello(False), {"op": 2, "d": {}}, _yanit("acc-1", "GetRecordStatus", True, {"outputActive": True})], sifre="")
    c.baglan()
    k("kayit_aktif_mi True", c.kayit_aktif_mi() is True)
    c.kapat()
    k("kapat soketi kapatir", s.kapali)
    print(f"SELFTEST: {sum(sonuc)}/{len(sonuc)}")
    return all(sonuc)


def _badtest():
    sonuc = []

    def reddet(ad, f, hata=ObsHata):
        try:
            f()
            ok = False
        except hata:
            ok = True
        sonuc.append(ok)
        print(("TAMAM  " if ok else "HATA   ") + ad)

    reddet("sifre gerekli ama bos", lambda: _istemci([_hello(True)], sifre="")[0].baglan())
    reddet("ilk mesaj Hello degil", lambda: _istemci([{"op": 9, "d": {}}])[0].baglan())
    reddet("Identified yerine hata/kapanis", lambda: _istemci([_hello(True), ConnectionError("kapandi")])[0].baglan())
    reddet("Identified op yanlis", lambda: _istemci([_hello(True), {"op": 5, "d": {}}])[0].baglan())
    reddet("gecersiz JSON", lambda: _istemci(["{bozuk"])[0].baglan())
    reddet("mesaj sozluk degil", lambda: _istemci(["[1,2]"])[0].baglan())

    def f_istek_basarisiz():
        c, _ = _istemci([_hello(False), {"op": 2, "d": {}}, _yanit("acc-1", "StartRecord", False, kod=500)], sifre="")
        c.baglan(); c.kayit_baslat()
    reddet("requestStatus result=false", f_istek_basarisiz)

    def f_yol_yok():
        c, _ = _istemci([_hello(False), {"op": 2, "d": {}}, _yanit("acc-1", "StopRecord", True, {})], sifre="")
        c.baglan(); c.kayit_durdur()
    reddet("StopRecord outputPath yok", f_yol_yok)

    def f_yanit_gelmez():
        c, _ = _istemci([_hello(False), {"op": 2, "d": {}}, _yanit("baska-id", "X")], sifre="")
        c.baglan(); c.istek("GetRecordStatus")
    reddet("requestId uyusmaz / yanit gelmez", f_yanit_gelmez)

    reddet("baglanti yokken istek", lambda: ObsIstemci().istek("GetRecordStatus"))

    def f_fabrika():
        def kotu(url, t):
            raise OSError("OBS kapali")
        ObsIstemci(fabrika=kotu).baglan()
    reddet("OBS kapali (baglanti reddi)", f_fabrika)
    reddet("kimlik_dizesi sayi", lambda: kimlik_dizesi(1, "a", "b"), ValueError)
    reddet("bos istek tipi", lambda: istek_kur("", "x"), ValueError)
    reddet("gecersiz port", lambda: ObsIstemci(port=0), ValueError)
    reddet("gecersiz host", lambda: ObsIstemci(host=""), ValueError)
    print(f"BADTEST: {sum(sonuc)}/{len(sonuc)}")
    return all(sonuc)


def _canli():
    """Gercek OBS'e baglanir, yalnizca GetRecordStatus sorar (kayit BASLATMAZ)."""
    import os
    kok = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    sifre = env_dosyasindan(os.path.join(kok, ".env"), "OBS_WS_PASSWORD") or ""
    c = ObsIstemci(sifre=sifre)
    try:
        c.baglan()
        print("BAGLANDI. Kayit aktif mi:", c.kayit_aktif_mi())
        return True
    except ObsHata as e:
        print("OBS HATASI:", e)
        return False
    finally:
        c.kapat()


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if _selftest() else 1)
    if "--badtest" in sys.argv:
        sys.exit(0 if _badtest() else 1)
    if "--canli" in sys.argv:
        sys.exit(0 if _canli() else 1)
    print("Kullanim: python modules\\obs\\obs_websocket_client.py --selftest | --badtest | --canli")