# GUNCEL DURUM (her gorev sonunda guncellenir, en fazla 40 satir)
Tarih: 2026-11-05
Proje yolu: C:\Users\User\Documents\ACC_Personal_Race_Assistant
Eski proje (referans): C:\Users\User\Desktop\ACC_AUTO_DIRECTOR_FINAL\AutoDirector (harita icin harita_cikar.py)
Ayrinti: docs\claude_devir.md (uzun gecmis), docs\PROJE_KANUNU.md (kurallar)

## Biten
- OBS, broadcasting, event_detector, player_tracker testleri temiz (broadcasting selftest 35).
- Ayristirici yamasi: _oturum'da HUD stringi (_hud); replay/hava_c dogru geliyor.
- Kamera (50) ve HUD (49) komutlari gercek ACC'de KABUL edildi.
- REPLAY CALISTI zamanli RACE oturumunda (replay=True, kamera Set1_Cam*). Antrenmanda calismadi.
- startSessionTime = MS: 2 goruntu + eski proje kodu (instant_replay ms int, baslangic = olay zamani - pay).
- acc_replay_controller: baslangic_ms, selftest 9/9.
- ISIMLE ARAC BULMA: find_by_driver_name / find_all_by_driver_name (sira, buyuk-kucuk, Turkce harf yok sayilir, TEK eslesme sart). Test 12/12.
- replay_yaris.py yeniden yazildi: "python replay_yaris.py "Hakan Aksen"" veya yaris no veya hedefsiz.

## Kararlar
- Yarista LLM yok. Proje yaris sonrasi odakli (olay kaydi, klip, rapor, pace).
- risk/message/tts askida. ACC-Auto-Director ve pydub kalsin.
- Kod ortami: VS Code + Continue + Ollama; zor kararlar Claude sohbetinde (ucretsiz plan).
- Calisma bicimi: az token, tek adim, tek PowerShell komutu; gormedigin dosyaya yama yazma.
- LFM'de kapi numarasi her yarista DEGISIR: oyuncu araci ISIMDEN bulunur (Hakan Aksen / Aksen Hakan), numaradan degil.
- Betikler komut satirina donmeden calismali: bip + log dosyasi. Gecici dosyalar git'e girmez.

## Simdi
- Zamanli yarista: python replay_yaris.py "Hakan Aksen". Log'da: hedef 'Hakan Aksen' -> carId N; kamera kendi aracina kilitlendi mi?
- UYARI cikarsa log'daki "roster ornegi" satirini yapistir (ACC ismi hangi bicimde gosteriyor).
- Sonra replay'i olay/klip akisina bagla; OBS veya eski ffmpeg_ekran_kaydedici (10 sn once/20 sn sonra klip) secimi.

## Acik / dogrulanmayan
- find_by_driver_name gercek ACC'de DENENMEDI; odak_arac_id oyuncu araci DEGIL (hep 23 geldi).
- LFM rank/Elo "kacinci olmaliyim" ozelligi: eski klasorde kod YOK (sadece PROJE_VIZYONU.md'de LFM linki); hangi programdaydi bilinmiyor.
- Antrenmanda session_zamani_ms=-1; garajda arac listesi bos; menude replay hemen basladi (tek gozlem).
- Eski kod kurali: kamera seti ve adi birlikte verilmeli veya ikisi de bos; controller'da bu kontrol yok.
- Salt okunur kayitta komut reddedilir; command_password ACC ile ayni olmali.
- acc_event_detector engel_debounce=2, LFM gercek JSON ornegi.
