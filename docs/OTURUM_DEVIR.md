# ACC Personal Race Assistant — Oturum Devir Teslim Notu

## 1. Proje Ozeti
ACC (Assetto Corsa Competizione) icin kisisel yaris asistani. LFM'deki 30 dk yarislarda calisir. Tamamen yerel: ACC Shared Memory, Broadcasting API, OBS WebSocket, Ollama. Internet yok, tus gonderimi yok, kayit yok. Sadece kullanicinin araci ve komsu araclari izlenir. Olaylar `events.json`'a yazilir; yaris sonrasi OBS ile klip uretilir; CrewChief benzeri kisa Turkce uyarilar verilir.

## 2. Ortam
- Python 3.13.7, venv aktif
- Proje yolu: `C:\Users\User\Documents\ACC_Personal_Race_Assistant`
- Windows 11
- Kurulu: requests, python-dotenv, pydub, websocket-client
- VS Code + Continue + Ollama (Qwen 14B) yerel AI olarak kullaniliyor (token tasarrufu icin buyuk dosya okuma/ozetleme gorevlerinde)

## 3. Tamamlanan ve Test Edilen Moduller

| Modul | Durum | Not |
|-------|-------|-----|
| `modules/lfm/lfm_track_history.py` | TAMAM | Testler gecti |
| `modules/lfm/lfm_lobby_cache.py` | TAMAM | Testler gecti |
| `modules/lfm/lfm_profile_cache.py` | TAMAM | Testler gecti |
| `modules/acc/acc_shared_memory_reader.py` | TAMAM | Gercek ACC verisiyle dogrulandi |
| `modules/acc/acc_player_tracker.py` | TAMAM | Canli veride dogrulandi; heading duzeltmesi yapildi |
| `modules/acc/acc_broadcasting_client.py` | TAMAM | Sentetik testler gecti (32 kontrol); canli `--watch 120` henuz yapilmadi |
| `modules/acc/acc_event_detector.py` | TAMAM | Yazildi, `--selftest`/`--badtest` iceriyor; henuz calistirilip dogrulanmadi |

## 4. Konfigurasyon Dosyalari
- `config/settings.json` — lfm + field_map + acc + broadcasting bolumleri
- `config/thresholds.json` — izleme, relative_speed, lateral_offset, event_detector bolumleri
- `config/cameras.json`
- `docs/CREDITS.md` — acik kaynak referanslari
- `.gitignore` — venv, __pycache__, .env, logs, data/events.json, *.bak* vb.

## 5. Bu Oturumda Yapilan Kritik Duzeltmeler

### 5.1 `acc_broadcasting_client.py` — `Cozumleyici` sinifi
**Sorun:** Eski A/B layout denemesi (`car_layout`, `layout_kilitli`) vardi; Claude'un `Plan.txt`'teki sabit yerlesim duzeltmesi uygulanmamisti. Canli `--watch 120` sirasinda spline hep 0.000 cikiyordu.

**Yapilanlar:**
1. `__init__`'teki `self.car_layout = "A"` ve `self.layout_kilitli = False` satirlari silindi; yerine `self._son_spline = {}` ve `self._spline_ret = {}` eklendi.
2. `_arac` fonksiyonu tamamen degistirildi: sabit yerlesim, siki dogrulama (spline 0..1, delta/laps makul, lap suresi makul, spline atlama tespiti, ust uste 10 ret sonrasi spline referansi sifirlama).
3. `izle()` fonksiyonundaki `layout` print'i temizlendi.
4. Selftest'teki "yerlesim otomatik secildi" satiri silindi.

### 5.2 Alan Sirasi Hatasi (Kritik)
**Sorun:** Hem `_arac` hem `_p_car` yanlis sira kullaniyordu: `spline, delta, laps`. ACC Broadcasting protokolunde dogru sira: **`spline (f32) -> laps (u16) -> delta (i32)`**.

**Dogrulama kaynaklari:**
- https://github.com/toonknapen/accbroadcastingsdk/blob/master/network/buffer.go (satir 118)
- https://docs.rs/acbc/0.1.0/x86_64-apple-darwin/acbc/struct.RealtimeCarUpdate.html

**Yapilan duzeltmeler:**
- Satir 405 (`_arac`): `spline, delta, laps = r.f32(), r.i32(), r.u16()` -> `spline, laps, delta = r.f32(), r.u16(), r.i32()`
- Satir 852 (`_p_car`): `struct.pack("<fiH", spline, 250, laps)` -> `struct.pack("<fHi", spline, laps, 250)`

**Sonuc:** `--selftest` **TAMAM (32 kontrol)**.

## 6. Yedekler
- `acc_broadcasting_client.py.yedek` (ilk otomatik betik oncesi)
- `acc_broadcasting_client.py.yedek2` (ikinci deneme)
- `acc_broadcasting_client.py.yedek3` (ucuncu deneme)
- `acc_broadcasting_client.py.yedek4` (dorduncu deneme)
- `acc_broadcasting_client.py.yedek5` (son basarili duzeltme oncesi)

## 7. Siradaki Adimlar (Claude'un Planina Gore)

1. **`acc_broadcasting_client.py` canli `--watch 120`** — ACC acikken calistir. Basari olcutu: spline `0 < x < 1` ve zamanla artiyor, ret sayisi dusuk, bayt uyusmazligi yok.
2. **`acc_event_detector.py --selftest` ve `--badtest`** — Sentetik, hizli, canli veri gerektirmez.
3. **`acc_event_detector.py` canli `--watch 120`** — Gercek olaylarin `events.json`'a yazildigini dogrula.
4. **OBS entegrasyonu** — `obs-websocket` ile `events.json`'daki olaylara gore klip uretimi (henuz kod yok).
5. **Ollama/Qwen 14B entegrasyonu** — Turkce sesli uyari uretimi (henuz kod yok).
6. **CrewChief benzeri uyari katmani** — `events.json`'daki olaylari kisa Turkce uyarilara cevirme (henuz kod yok).
7. **Ana dongu** — Tum modulleri birlestiren `main.py` (henuz kod yok).

## 8. Alisma Protokolu (Claude ile)
- Her modul icin once 5 maddelik plan; kod sadece onay sonrasi.
- Mesajlar kisa; uzun aciklama yok.
- Kod yazarken tek blok; ozet yok.
- Her yanitin basinda "Su an su dosyadayiz: X".
- Eski sohbeti hatirlamadigini soyleyip durma.
- Buyuk dosya okuma/kaynak tarama gerekirse VS Code'daki yerel AI'i (Qwen 14B) kullan; token harcama.

## 9. Bilinen Riskler ve Notlar
- `acc_broadcasting_client.py`'nin canli dogrulamasi henuz yapilmadi; spline 0.000 sorunu duzeltildi ama gercek ACC verisiyle test edilmedi.
- `thresholds.json` icinde `event_detector` bolumu yoksa kod varsayilanlari kullanir; canli testte ihtiyac cikarsa eklenir.
- Cooldown ve `events.json` formati gercek yaris verisiyle test edilmeden OBS/Ollama'ya gecilmemeli; aksi halde hatanin kaynagi (olay mi, entegrasyon mu) ayirt edilemez.
- `acc_event_detector.py`'deki `CrossingGate` sinifi, komsu aracin `boyuna_m` isaret degisimini tespit ediyor; `acc_player_tracker.py`'nin `on`/`arka` komsularini dogru urettigini varsayiyor.

## 10. Yeni Oturumda Ilk Mesaj
Yeni bir AI oturumuna sunu yapistir:

> "ACC Personal Race Assistant projesinde kaldigimiz yerden devam ediyoruz. Bu dosya, onceki oturumun devir teslim notudur. Once bu notu oku ve projenin durumunu anladigini kisaca teyit et. Sonra siradaki adimi soyle: `acc_broadcasting_client.py` canli `--watch 120` dogrulamasi. Kod yazma; sadece siradaki adimi ve varsa riskleri soyle."