# GUNCEL DURUM (her gorev sonunda guncellenir, en fazla 40 satir)
Tarih: 2026-11-05 (baska Claude hesabina devir icin guncellendi)
Proje yolu: C:\Users\User\Documents\ACC_Personal_Race_Assistant
Eski proje (referans, sadece oku): C:\Users\User\Desktop\ACC_AUTO_DIRECTOR_FINAL\AutoDirector
Ayrinti: docs\claude_devir.md, docs\PROJE_KANUNU.md

## Biten
- OBS/broadcasting/event_detector/player_tracker testleri temiz (broadcasting selftest 35).
- Oturum ayristirici yamasi (_hud); kamera(50)/HUD(49) komutlari gercek ACC'de calisti.
- REPLAY calisti: sadece ZAMANLI RACE oturumunda, antrenmanda calismadi. startSessionTime = MS (kesin).
- acc_replay_controller baslangic_ms selftest 9/9. Isimle arac bulma find_by_driver_name test 12/12.
- replay_yaris.py "Hakan Aksen" | <yaris_no> | hedefsiz. Isimle kisim gercek ACC'de DENENMEDI.
- LFM modulleri modules\lfm altinda, 3 modul SELFTEST TAMAM (2026-11-05).

## Kararlar
- Yarista LLM yok; proje yaris sonrasi odakli (olay kaydi, klip, rapor, pace). risk/message/tts askida.
- Oyuncu araci ISIMDEN bulunur (LFM'de kapi no her yaris degisir). Sahip: Hakan Aksen.
- Kod: VS Code+Continue+Ollama; zor kararlar Claude sohbetinde (ucretsiz plan, Claude Code yok, token az).
- Calisma bicimi: kisa, tek adim, tek PowerShell komutu; gormedigin dosyaya yama yazma; betikler bip+log ile komut satirina donmeden calisir.

## Simdi
- 1) (BITTI) lfm selftest 3/3 gecti.
- 2) Zamanli yarista: python replay_yaris.py "Hakan Aksen"; log'da hedef -> carId; kamera kendi aracina kilitlendi mi.
- 3) LFM gercek uc nokta (url), .env LFM_API_TOKEN, settings.json lfm bolumu: kullanicidan al, tek lobiyle dene.
- 4) Sonra: lobi Elo'dan hedef sira ozelligi; replay'i olay/klip akisina bagla (OBS veya eski ffmpeg_ekran_kaydedici 10sn once/20sn sonra).

## Acik / dogrulanmayan
- LFM uc nokta/alan adlari DOGRULANMADI; hedef sira (Elo) hesabi kodda YOK, LFM Elo formulu bilinmiyor.
- lfm_profile_cache.py satir 178-385 incelenmedi. Lobi name ile ACC tam_ad eslesmesi LFM isim bicimine bagli.
- Antrenmanda session_zamani_ms=-1; garajda arac listesi bos; odak_arac_id oyuncu araci DEGIL.
- Eski kod kurali: kamera seti+adi birlikte veya ikisi bos; controller'da kontrol yok.
- command_password ACC ile ayni olmali; engel_debounce=2; LFM gercek JSON ornegi.

## Yeni hesaba notlar
- CLAUDE.md + bu dosyayi yukle. Dosya okutmak icin PowerShell ile dosyaya yazdirip yukle (panoya degil).
- PowerShell: parantez icinde ; yerine $( ) kullan; Python'a pipe'ta Turkce harf bozulur, \u kacislari kullan.
- GitHub tree/arama sayfalari otomatik erisime kapali; kullanici elle kopyalar.
