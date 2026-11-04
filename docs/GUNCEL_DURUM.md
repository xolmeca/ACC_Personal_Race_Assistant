# GUNCEL DURUM (her gorev sonunda guncellenir, en fazla 40 satir)
Tarih: 2026-11-04
Proje yolu: C:\Users\User\Documents\ACC_Personal_Race_Assistant
Ayrinti: docs\claude_devir.md (uzun gecmis), docs\PROJE_KANUNU.md (kurallar)

## Biten
- OBS modulu gercek OBS ile dogrulandi (kayit mkv, tasima yeniden deneme gerekli).
- Testler temiz: broadcasting 32+25, event_detector 60+55, player_tracker 44+17, obs 6+9, 13+15, 17+12.
- Proje temizlendi, git status bos. requirements: python-dotenv, requests, websocket-client.

## Kararlar
- Yarista LLM yok. Proje yaris sonrasi odakli (olay kaydi, klip, rapor, pace).
- risk/message/tts engine askida. ACC-Auto-Director ve pydub kalsin.

## Simdi
- acc_replay_controller v1: yalnizca InstantReplayRequest paketi kuran saf fonksiyon + gonderim.
- PistBilgisi (kamera_setleri, hud_sayfalari) yamasi: UYGULANDI MI DOGRULANMADI, once Select-String ile kontrol et.

## Acik / dogrulanmayan
- Komut alan sirasi/turleri, odak araci int/short, startSessionTime birimi, yaris sonrasi replay.
- REQUEST_TRACK_DATA (11) gonderilmeden pist verisi gelmeyebilir.
- acc_event_detector engel_debounce=2, LFM gercek JSON ornegi.
