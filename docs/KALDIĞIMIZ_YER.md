# KALDIĞIMIZ YER — ACC Personal Race Assistant

Bu dosya, yeni bir Claude sohbetine baglam vermek icin hazirlandi.
Asagidaki metni yeni sohbete yapistirin.

---

## PROJE
ACC Personal Race Assistant — LFM'deki 30 dk ACC yarislarinda calisan,
tamamen yerel kisisel yaris asistani. Yalnizca kullanicinin araci ve
komsu araclar izlenir. Olaylar events.json'a yazilir; yaris sonrasi OBS
ile klip uretilir; CrewChief benzeri kisa Turkce uyarilar verilir.

## KURALLAR (ihlal edilemez)
1. Tum islem yerel: localhost ACC Shared Memory/Broadcasting API,
   OBS WebSocket, Ollama. Yaris sirasinda dis internet YOK.
2. Tus gonderimi YOK (pydirectinput vb. kullanilmayacak).
3. Yaris sirasinda OBS kaydi/replay YOK.
4. Yalnizca kullanicinin araci ve komsu araclar izlenir.
5. Hile/crack/keygen/DLC unlocker kullanilmayacak.
6. LFM verisi yaris sirasinda cekilmez; yaris oncesi cache.

## TEKNOLOJI
Python 3.13.7, venv aktif, proje yolu
C:\Users\User\Documents\ACC_Personal_Race_Assistant, Windows 11.
Kurulu: requests, python-dotenv, pydub, websocket-client.

## TAMAMLANAN MODULLER (hepsi calisiyor, testleri gecti)
- modules/lfm/lfm_track_history.py
- modules/lfm/lfm_lobby_cache.py
- modules/lfm/lfm_profile_cache.py
- modules/acc/acc_shared_memory_reader.py (gercek ACC verisiyle dogrulandi)
- modules/acc/acc_player_tracker.py (heading duzeltmesi yapildi;
  canli veride fark 0-1d, komsu/yan_yana/ttc dogru)
- config/settings.json (lfm + field_map + acc)
- config/thresholds.json, config/cameras.json
- docs/CREDITS.md

## SIRADAKI MODUL
modules/acc/acc_event_detector.py
TakipDurumu ciktisini tuketecek; olay tespiti yapacak:
overtake_gained, overtake_lost, collision_suspect, spin_suspect,
off_track, pit_entry, pit_exit, penalty, flag, approaching_car,
closing_to_car_ahead. Her olay events.json'a zaman damgasiyla yazilacak.

## CALISMA PROTOKOLU
1. Her modul icin once 5 maddelik plan; kod sadece onay sonrasi.
2. Mesajlar kisa olsun; uzun aciklama yazma.
3. Kod yazarken tek blok ver; ozet verme.
4. Her yanitin basinda "Su an su dosyadayiz: X" yaz.
5. Eski sohbeti hatirlamadigini soyleyip durma.

## YENI SOHBETE YAPISTIRILACAK MESAJ
"Kota bitti; kaldigimiz yerden devam ediyoruz. Proje: ACC Personal
Race Assistant. Tamamlanan moduller: lfm_track_history, lfm_lobby_cache,
lfm_profile_cache, acc_shared_memory_reader, acc_player_tracker (hepsi
test gecti; heading duzeltmesi canli veride dogrulandi). Sirada
acc_event_detector.py var. Once 5 maddelik plan ver, kod yazma."