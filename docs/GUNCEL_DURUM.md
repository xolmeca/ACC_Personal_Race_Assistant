# GUNCEL DURUM (her gorev sonunda guncellenir, en fazla 40 satir)
Tarih: 2026-11-05
Proje yolu: C:\Users\User\Documents\ACC_Personal_Race_Assistant
Ayrinti: docs\claude_devir.md (uzun gecmis), docs\PROJE_KANUNU.md (kurallar)

## Biten
- OBS, broadcasting, event_detector, player_tracker testleri temiz (broadcasting selftest 35).
- Ayristirici yamasi: _oturum'da HUD stringi (_hud) okunuyor; replay/hava_c artik dogru geliyor.
- Kamera (tip 50) ve HUD (tip 49) komutlari gercek ACC'de KABUL edildi (komut_testi.py 3/3).
- REPLAY CALISTI: zamanli RACE oturumunda replay=True, kamera Set1_Cam* oldu (replay_yaris.py).
- startSessionTime birimi MS: baslangic 23.5 -> yarisin en basi, 21085 -> yaris ici (2 goruntu).
- acc_replay_controller: parametre baslangic_ms, selftest 9/9. replay_yaris.py <yaris_no> yazildi.
- Test betikleri: replay_oto, replay_ss (pillow gerekli), replay_yaris, komut_testi (bip + log, komut satirina donmeden).

## Kararlar
- Yarista LLM yok. Proje yaris sonrasi odakli (olay kaydi, klip, rapor, pace).
- risk/message/tts engine askida. ACC-Auto-Director ve pydub kalsin.
- Kod ortami: VS Code + Continue + Ollama qwen2.5-coder 14b; zor kararlar Claude sohbetinde (ucretsiz plan).
- Calisma bicimi: az token, tek adim, tek PowerShell komutu; gormedigin dosyaya yama yazma.
- LFM'de yaris numarasi (kapi no) HER YARISTA DEGISIR; sabit yazma, arguman al (bu yaris 966).
- Betikler ACC'ye gecildiginde komut satirina donmeden calismali: bip ile haber, sonuc log dosyasinda.

## Simdi
- Zamanli yarista: python replay_yaris.py <yaris_no> (menude de calisabilir, tek gozlem).
- Log'da "yaris no X -> carId Y" ara; replay kamerasi KENDI aracina kilitlendi mi yaz.
- Sonra replay'i olay/klip akisina bagla (event_detector -> replay_gonder, baslangic = olay zamani - pay).

## Acik / dogrulanmayan
- find_by_race_number yamasi VERILDI ama sonucu dogrulanmadi; odak_arac_id oyuncu araci DEGIL (hep 23).
- Antrenmanda session_zamani_ms=-1 ve replay baslamadi; sadece zamanli oturumda denendi/calisti.
- Garajda arac listesi bos geliyor; araclar pistteyken doluyor.
- startSessionTime ms: 2 goruntuye dayanir; replay suresi/kamera secimi, yaris sonrasi replay denenmedi.
- Salt okunur kayitta komut reddedilir; command_password ACC ile ayni olmali.
- acc_event_detector engel_debounce=2, LFM gercek JSON ornegi.
- GitHub: ACCDirectorAssistant (C# canli yonetmen) yaramadi; EmperorCookie/accapi README: request_instant_replay(startTime, durationMs), kaynak okunamadi.
