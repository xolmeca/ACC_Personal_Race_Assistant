# GUNCEL DURUM (her gorev sonunda guncellenir, en fazla 40 satir)
Tarih: 2026-11-04
Proje yolu: C:\Users\User\Documents\ACC_Personal_Race_Assistant
Ayrinti: docs\claude_devir.md (uzun gecmis), docs\PROJE_KANUNU.md (kurallar)

## Biten
- OBS modulu gercek OBS ile dogrulandi (kayit mkv, tasima yeniden deneme gerekli).
- Testler temiz: broadcasting 35 kontrol, event_detector, player_tracker, obs.
- PistBilgisi (kamera_setleri, hud_sayfalari) yamasi UYGULANDI, selftest ile dogrulandi.
- acc_replay_controller v1: instant_replay_paketi + replay_gonder, selftest 9 kontrol TAMAM, commit atildi.
- replay_deneme.py (proje koku) yazildi: gercek ACC'de komut yetkisi, pist verisi, arac listesi, replay gonderimi. HENUZ CALISTIRILMADI.
- requirements: python-dotenv, requests, websocket-client.

## Kararlar
- Yarista LLM yok. Proje yaris sonrasi odakli (olay kaydi, klip, rapor, pace).
- risk/message/tts engine askida. ACC-Auto-Director ve pydub kalsin.
- Kod ortami: VS Code + Continue + Ollama qwen2.5-coder 14b; zor kararlar Claude sohbetinde (ucretsiz plan, Claude Code yok).
- Calisma bicimi: az token, tek adim, tek PowerShell komutu; gormedigin dosyaya yama yazma.

## Simdi
- ACC'yi antrenman/bos oturumda ac, proje kokunden: python replay_deneme.py
- Tum ciktiyi + replay'in ekranda baslayip baslamadigini ajana yapistir.
- Basariliysa DOGRULANMADI maddelerini guncelle, replay'i olay/klip akisina bagla.

## Acik / dogrulanmayan
- InstantReplayRequest: tip 51, alan sirasi/turleri, odak araci int32, startSessionTime birimi, yaris sonrasi replay.
- Salt okunur kayitta komut reddedilir; settings.json command_password ACC ile ayni olmali.
- REQUEST_TRACK_DATA (11) gonderilmeden pist verisi gelmeyebilir; replay_deneme.py bunu da test eder.
- acc_event_detector engel_debounce=2, LFM gercek JSON ornegi.
