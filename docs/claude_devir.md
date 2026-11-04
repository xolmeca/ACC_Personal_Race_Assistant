# ACC Personal Race Assistant – Oturum Devir Notu



## 1. Proje özeti

- ACC Personal Race Assistant: LFM 30 dk yarışları için, tamamen yerel çalışan yarış asistanı.

- İnternet yok (LFM verisi önceden önbelleğe alınır), oyuna tuş gönderimi yok.

- Kapsam: sadece kullanıcı + komşu araçlar (ön/arka).

- Akış: olay algılama -> events.json -> OBS (kurgu/sahne) + Ollama/Qwen (TTS/yorum) -> CrewChief benzeri uyarılar.

- GitHub: xolmeca/ACC_Personal_Race_Assistant



## 2. Ortam

- Python 3.13.7, venv, Windows 11, komutları kullanıcı PowerShell'den kendisi çalıştırır.

- Proje yolu: <DOLDUR>

- Kurulu paketler: <DOLDUR: pip freeze çıktısı>

- Yerel AI: VS Code + Continue + Qwen 14B (büyük dosya okuma / kaynak tarama için).



## 3. Modüller

| Modül | Durum |

|---|---|

| lfm_track_history | Tamam, test geçti |

| lfm_lobby_cache | Tamam, test geçti |

| lfm_profile_cache | Tamam, test geçti |

| acc_shared_memory_reader | Tamam, gerçek ACC verisiyle doğrulandı |

| acc_player_tracker | Tamam, heading düzeltmesi canlıda doğrulandı |

| acc_broadcasting_client | Sentetik selftest 32 kontrol GEÇTİ; düzeltilmiş sürümle canlı --watch HENÜZ YOK |

| acc_event_detector | Yazıldı; --selftest/--badtest var; ÇALIŞTIRILMADI |



Önemli ders: SPageFileGraphic.position realtime DEĞİL. Overtake için CrossingGate (boyuna_m) kullanılır.



## 4. Konfigürasyon

- settings.json: "broadcasting" bölümü (port 9000, connection_password, command_password). Değerler dosyada.

- thresholds.json: event_detector bölümü yoksa kod varsayılanları kullanılır.

- cameras.json, CREDITS.md, .gitignore: <DOLDUR: içerik/durum>



## 5. Bu oturumdaki kritik düzeltmeler

\*\*Teşhis:\*\* Canlı --watch'ta spline hep 0.000, ön/arka mesafeler anlamsızdı (7.78e-42, 5552.0). Ham bayt analizi: car update paketi 89 bayt; spline, track_position'dan hemen sonra f32 olarak geliyor.



\*\*Düzeltmeler (acc_broadcasting_client.py):\*\*

- Eski A/B layout (car_layout, layout_kilitli, aday skorlama döngüsü) kaldırıldı.

- `_son_spline` / `_spline_ret` eklendi (Cozumleyici.__init__).

- `_arac`: sabit yerleşim + sıkı doğrulama (paket tam tüketilmeli, 0<=spline<=1, denormal yok, delta/laps/lap süresi makul, spline atlama kontrolü; 10 ardışık retten sonra referans sıfırlanır; hatada ProtocolError, paket atılır, durum bozulmaz).

- izle() print ve selftest layout satırı temizlendi.



\*\*Alan sırası hatası:\*\* Yanlış "spline, delta, laps" yerine doğru sıra:

`TrackPosition u16 -> Spline f32 -> Laps u16 -> Delta i32 -> 3x LapInfo (best, last, current)`

- LapInfo: laptime i32, car u16, driver u16, split_sayisi u8, splitler i32 x n, bayraklar 4 x u8.

- Kaynaklar: toonknapen/accbroadcastingsdk buffer.go (satır 118) ve docs.rs/acbc RealtimeCarUpdate.

- Düzeltilen yerler: `_arac` (satır \~405) `r.f32(), r.u16(), r.i32()`; `_p_car` (satır \~852) `struct.pack("<fHi", spline, laps, 250)`.

- Not: ilk paketlerde laps=0 ve delta=0 olduğu için hata canlıda geç fark edildi.

- Selftest: TAMAM (32 kontrol).



## 6. Yedekler

acc_broadcasting_client.py.yedek ... .yedek5 (hangisinin hangi aşamaya ait olduğu: <DOLDUR>)



## 7. Sıradaki adımlar

1\. Broadcasting canlı `--watch 120`. Başarı: spline 0<x<1 ve artıyor, tur sonunda 1->0, laps tur bitince +1, delta 0'da takılı değil, bayt uyuşmazlığı 0, ret oranı düşük, saçma ön/arka mesafe yok. Ret nedenleri araç bazında dökülsün (istatistik şu an sadece konsola yazılıyor, log'a değil).

2\. event_detector `--selftest` ve `--badtest`.

3\. event_detector canlı `--watch 120`.

4\. OBS entegrasyonu.

5\. Ollama/Qwen TTS.

6\. CrewChief benzeri uyarı katmanı.

7\. main.py ana döngü.



## 8. Çalışma protokolü

- Her yanıtın başında: "Şu an şu dosyadayız: X".

- Her modül için önce 5 maddelik plan, kod onaydan sonra.

- Mesajlar kısa; tek, küçük komut/kod bloğu; çıktı beklenir.

- Kodu görmeden fonksiyonu tahminle yazma; önce istenen satır/fonksiyon yapıştırılır.

- Büyük dosya okuma / kaynak-jar tarama için VS Code + Qwen 14B kullan, sohbet tokenını harcama.

- Kaynak/protokol bilgisini açık kaynaktan doğrula (bu oturumda Claude'un iki alan-sırası hatası böyle yakalandı).



## 9. Doğrulanacak / bekleyen küçük işler
Tamamlandı: ACC bayrak değerleri resmi dokümandan (V1.8.12) doğrulandı: 0 NO, 1 BLUE, 2 YELLOW, 3 BLACK, 4 WHITE, 5 CHECKERED, 6 PENALTY, 7 GREEN, 8 ORANGE. acc_event_detector.py ve acc_shared_memory_reader.py'ye işlendi; selftest/badtest geçti.

Bekleyenler:
- Sakin yarışta (10+ dk, kaza yok) sahte olay kontrolü; [GECIS-SAYAC] satırı ve olay dökümü.
- pit_exit olayı canlı test edilmedi.
- thresholds.json'a event_detector bölümü eklemek (şimdilik kod varsayılanları).
- Oyuncu için broadcasting spline ile shared memory normalizedCarPosition çapraz kontrolü (isteğe bağlı).
- Broadcasting pist verisi mesajı (trackMeters) çözülüyor mu: <DOLDUR>.
- İstatistik şu an konsola yazılıyor, log'a değil.
- prune ile gelen overtake olayları gecikmeli çıkar; OBS klibi için olaya geçişin gerçek zamanı (flip zamanı) taşınmalı.
- Repo public mi kontrol et; notlardaki yerel yolları (C:\Users\User\...) gözden geçir. Şifre notlarda yok.

## 10. Sıradaki adımlar
Karar: ana hat ACC Personal Race Assistant. Eski ACC-Auto-Director sadece mantık referansı, kod kaynağı değil. Race Assistant tuş göndermez; replay kamera yönetimi ayrı program olarak kalır.

1. **OBS entegrasyonu (şu an burada).** Planlanan modül: modules/obs/obs_client.py. Karar verilen plan:
   1. Bağlantı: obs-websocket v5, settings.json'a `obs` bölümü (host, port, şifre; şifre repoya girmez). OBS kapalıysa veya bağlantı koparsa program çökmez, uyarır, olaylar events.json'a yazılmaya devam eder.
   2. Kayıt kontrolü: başlat, durdur, durum oku. Oturum canlı olunca başlar, bitince durur. Kayıt zaten aktifse dokunmaz.
   3. Zaman eşleşmesi: kayıt başlarken duvar saati saklanır; her olaya duvar saati ve OBS kayıt süresi eklenir.
   4. Klip listesi: olay tipi, öncesi/sonrası saniye, çakışan aralıkların birleşmesi thresholds.json'da; ilk aşamada sadece clips.json üretilir. Gerçek kesme (ffmpeg) ayrı, sonraki adım.
   5. Test: sahte OBS istemcisiyle --selftest; --badtest (yanlış şifre, kopma, kayıt zaten aktif, bozuk zaman kodu); sonra canlı 30 sn kayıt.
   - Durum: OBS WebSocket v5 dokümanı VS Code + Qwen 14B ile taranacak (StartRecord, StopRecord, GetRecordStatus alanları, kayıt durumu olayı, obsws-python kullanımı; isimler doğrulanmadı). OBS sürümü ve "WebSocket Sunucu Ayarları" menüsü: <DOLDUR>.
2. Ollama/Qwen TTS.
3. CrewChief benzeri uyarı katmanı. Yaklaşma uyarılarında zaman farkı = mesafe / ölçülen göreli hız (sabit hız varsayımı yok).
4. main.py ana döngü.
5. Gerekirse: tracker'dan 3-4 yakın aracı almak (şu an gerekli değil).

GUNCELLEME (2026-11-04, Sahip ciktiyi yapistirdi): obs_websocket_client --selftest 13/13, --badtest 15/15 TAMAM; clip_naming --selftest 6/6 TAMAM (Python 3.13.7). Gercek OBS ile --canli HENUZ CALISTIRILMADI (sentetik test). SIRADAKI: recording_controller plani.
GUNCELLEME 2 (2026-11-04, Sahip ciktiyi yapistirdi): modules/obs/recording_controller.py yazildi ve testli: --selftest 17/17, --badtest 12/12 TAMAM; obs_websocket_client 13/13 ve 15/15, clip_naming 6/6 TAMAM (Python 3.13.7). status 2 ve 3'te OBS'e istek gitmedigi testle dogrulandi. Gercek OBS ile HICBIR test henuz yapilmadi (--canli bekliyor). settings.json'a OBS anahtari EKLENMEDI (icerigi gorulmedi, DOGRULANMADI); kod varsayilan kullaniyor: obs.host localhost, obs.port 4455, obs.klip_klasoru data/clips. ACIK: OBS kayit formati (mkv ise dosya .mkv tasinir, sahte .mp4 adi verilmez). SIRADAKI: settings.json'a ekleme (once Get-Content config\settings.json), requirements.txt (websocket-client 1.9.2), OBS --canli testi (yaris disinda), sonra Ollama/Qwen uyari metni, risk_engine/message_engine/tts_engine, main.py.

## DEVIR NOTU 2026-11-04 (OBS modulu oturumu)

ONAYLANAN: OBS plani ve websocket-client (Apache-2.0, venv'de 1.9.2 kurulu). recording_controller plani onaylandi. Kayit kurali: yalnizca status 0 (AC_OFF) ve 1 (AC_REPLAY) iken kayit serbest; 2 (AC_LIVE), 3 (AC_PAUSE) ve bilinmeyen/None deger engelli.

DOGRULANAN (Sahip ham cikti yapistirdi, Python 3.13.7): clip_naming 6/6 + 9/9; obs_websocket_client 13/13 + 15/15; recording_controller 17/17 + 12/12. Commit c877fdf. Gercek OBS ile HICBIR test yapilmadi.
acc_shared_memory_reader.py: AC_LIVE = 2 (satir 28), DURUM_ADLARI {0 AC_OFF,1 AC_REPLAY,2 AC_LIVE,3 AC_PAUSE} (satir 29), graphics sozlugu "status"/"status_name" (satir 306-307), graphics_gecerli_mi(g) satir ~380. recording_controller bu sabitleri KOPYALADI (reader'i import etmez); reader degisirse elle guncelle.
RESMI KAYNAKLA DOGRULANAN (obs-websocket 5.x): kimlik = b64(sha256(b64(sha256(sifre+salt))+challenge)); op Hello 0, Identify 1, Identified 2, Event 5, Request 6, RequestResponse 7; StopRecord->outputPath; GetRecordStatus->outputActive.
DOGRULANMADI: requestStatus.result/code/comment alan adlari gercek OBS'e karsi; --canli (kayit baslatmaz) yaris disinda calistirilacak; StopRecord sonrasi dosya kilidi davranisi (tasima 5 deneme, 1 sn arayla).
OBS AYARI (Sahip): kayit bicimi mkv, kodlayici NVENC H.264. Kod uzantiyi OBS dosyasindan alir (.mkv). Kanun .mp4 diyor: Sahip karari bekliyor (A: mkv kalsin + kanun guncellensin, B: OBS Hybrid MP4).
ACIK: settings.json'a OBS anahtari EKLENMEDI (icerigi gorulmedi); kod varsayilan kullaniyor (obs.host localhost, obs.port 4455, obs.klip_klasoru data/clips). requirements.txt yok (websocket-client 1.9.2 eklenmeli). acc_event_detector engel_debounce=2 sorunu. LFM gercek JSON ornegi yok. Yurutucu (DeepSeek) gorevlerinde dosya yollari TAM verilmeli.
SIRADAKI: settings.json'a ekleme -> requirements.txt -> OBS --canli -> Kanun bolum 5 guncelle -> Ollama/Qwen uyari metni, risk_engine/message_engine/tts_engine, main.py.
GUNCELLEME 3 (2026-11-04): Sahip karari A: OBS kayit uzantisi (mkv) korunur, Kanun ".mp4" ifadesi "<uzanti>" olarak guncellendi. settings.json'a yalnizca "obs" bolumu eklendi (host localhost, port 4455, klip_klasoru data/clips); eski anahtarlar ayni (dogrulandi: ESKI ANAHTARLAR AYNI: True). requirements.txt olusturuldu: yalnizca websocket-client==1.9.2 (diger ucuncu parti bagimliliklar DOGRULANMADI, eklenmedi). TEST YONTEMI: testler proje kokunden "python -m modules.<klasor>.<modul> --selftest" ile calistirilir; dogrudan "python modules\...py" yolu reader, lfm_lobby_cache, lfm_profile_cache icin ModuleNotFoundError verir (kod hatasi degil, cagirma sekli). Gercek sayilar (04.11.2026): acc_broadcasting_client 32+25, acc_event_detector 60+55, acc_player_tracker 44+17, obs/* 6+9, 13+15, 17+12. SIRADAKI: OBS --canli (yaris disinda; OBS acik, WebSocket sunucusu acik, .env'de OBS_WS_PASSWORD), sonra Ollama/Qwen uyari metni plani, risk_engine/message_engine/tts_engine, main.py.
GUNCELLEME 4 (2026-11-04): OBS --canli GERCEK OBS ile calisti: "BAGLANDI. Kayit aktif mi: False" (port 4455 acik, sifre .env'de, kimlik dogrulama + GetRecordStatus + requestStatus alan adlari dogrulandi). OBS'te WebSocket sunucusu once kapaliydi (WinError 10061), kutu etkinlestirilince cozuldu. HALA DOGRULANMADI: gercek StartRecord/StopRecord, outputPath yaniti, StopRecord sonrasi dosya kilidi/tasima. OBS kayit bicimi mkv. SIRADAKI: (1) gercek kayit testi icin recording_controller'a --canli plani (yaris disinda, ACC kapali, kisa 3 sn kayit, gecici Proje numarasiyla), (2) Ollama/Qwen Turkce uyari metni plani, (3) risk_engine/message_engine/tts_engine, (4) main.py.
GUNCELLEME 5 (2026-11-04): OBS MODULU TAMAM, GERCEK OBS ILE DOGRULANDI. recording_controller --canli --status 0: StartRecord, kayit aktif=True, StopRecord, outputPath, tasima (D:/obs_kayit -> C: gecici, sureleri 2.1 sn), dosya 9511545 bayt .mkv. BULGU: StopRecord sonrasi ilk tasima denemesi WinError 32 (dosya OBS'te kilitli) verdi, 2. deneme OK; yeniden deneme mantigi (varsayilan 5 deneme, 1 sn) gercekten gerekli. Canli test komutu: python -m modules.obs.recording_controller --canli --status 0 (yalnizca ACC kapaliyken; AC2* islemi varsa calismaz). Commit 4a34440. SIRADAKI: Ollama/Qwen Turkce uyari metni modulu icin 5 maddelik plan (once ollama list ciktisi gerekli: model adi/sunucu adresi DOGRULANMADI), sonra risk_engine/message_engine/tts_engine, main.py.
GUNCELLEME 6 (2026-11-04) - TOPLU KAYIT: (1) SAHIP KARARI: yarista LLM/Ollama YOK (1 sn ustu gecikme veya FPS dususu kabul edilmez); Ollama/Qwen uyari metni modulu IPTAL; yarisici anlik ses CrewChief'te kalir. message_engine/tts_engine/risk_engine kapsami Sahip karari bekliyor. (2) Testler "python -m modules.<klasor>.<modul> --selftest" ile calisir (dosya yoluyla reader/lfm ModuleNotFoundError verir). (3) Kanun guncellendi: LLM karari, durum tablosu, madde 4.13, OBS dersleri. (4) Gercek sayilar: acc_broadcasting_client 32+25, acc_event_detector 60+55, acc_player_tracker 44+17, obs 6+9, 13+15, 17+12; tum testler OK (04.11.2026). (5) settings.json'a "obs" eklendi; requirements.txt var (websocket-client==1.9.2, digerleri DOGRULANMADI); .env (OBS_WS_PASSWORD) yerel, git disi. (6) Ollama'da qwen3:8b ve qwen2.5-coder:14b yuklu (kullanilmayacak). (7) SIRADAKI: Sahip karari (yarisici ses disinda proje yarıs sonrasi odakli mi?), sonra main.py/prediction/reports planlari; acc_event_detector engel_debounce=2 ve LFM gercek JSON ornegi acik.