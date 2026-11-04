# GUNCEL DURUM (her gorev sonunda guncellenir, en fazla 40 satir)
Tarih: 2026-11-05
Proje yolu: C:\Users\User\Documents\ACC_Personal_Race_Assistant
Ayrinti: docs\claude_devir.md (uzun gecmis), docs\PROJE_KANUNU.md (kurallar)

## Biten
- OBS modulu gercek OBS ile dogrulandi (kayit mkv, tasima yeniden deneme gerekli).
- Testler temiz: broadcasting 35 kontrol, event_detector, player_tracker, obs.
- PistBilgisi (kamera_setleri, hud_sayfalari) gercek ACC ile dogrulandi (Spa benzeri 5552 m).
- acc_replay_controller v1: instant_replay_paketi + replay_gonder, selftest 9 kontrol TAMAM.
- YAMA: acc_broadcasting_client _oturum, cs/cam sonrasi HUD stringi (_hud) okunuyor. Gercek ACC'de replay=False, hava_c 23, pist_c 30 gelince dogrulandi; selftest 35 TAMAM.
- replay_deneme.py ve replay_test_240.py (240 sn otomatik izleme) yazildi.
- GitHub Jackhod/ACCDirectorAssistant incelendi: C# WPF canli yonetmen, bize yarar kod yok.

## Kararlar
- Yarista LLM yok. Proje yaris sonrasi odakli (olay kaydi, klip, rapor, pace).
- risk/message/tts engine askida. ACC-Auto-Director ve pydub kalsin.
- Kod ortami: VS Code + Continue + Ollama qwen2.5-coder 14b; zor kararlar Claude sohbetinde (ucretsiz plan, Claude Code yok).
- Calisma bicimi: az token, tek adim, tek PowerShell komutu; gormedigin dosyaya yama yazma.

## Simdi
- ACC'de garajdan cik, pistte dur/yavas sur. python replay_test_240.py (odak arac id yeniden okunur, baslangic ms: 0/5000/30000/120000).
- Tum ciktiyi + ACC ekraninda replay olup olmadigini yapistir.

## Acik / dogrulanmayan
- REPLAY BASLAMADI: garajda, arac listesi bos, odak=-1, baslangic ham sn (0/5/30) ile 4 gonderim denendi. Pistte + ms testi bekliyor.
- InstantReplayRequest: tip 51, alan sirasi/turleri, odak araci int32, startSessionTime birimi (ms olabilir), yaris sonrasi replay.
- session_zamani_ms hep -1; gun_saati_ms degeri saniye cinsi gorunuyor (alan adi yaniltici).
- Salt okunur kayitta komut reddedilir; command_password ACC ile ayni olmali.
- acc_event_detector engel_debounce=2, LFM gercek JSON ornegi.
