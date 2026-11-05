# GUNCEL DURUM (her gorev sonunda guncellenir, en fazla 40 satir)
Tarih: 2026-11-05 (hesap devri #2, kota bitti)
Proje: C:\Users\User\Documents\ACC_Personal_Race_Assistant
Eski proje (sadece oku): C:\Users\User\Desktop\ACC_AUTO_DIRECTOR_FINAL\AutoDirector
Ayrinti: docs\claude_devir.md, docs\PROJE_KANUNU.md, docs\proje_notlari.txt

## Biten
- OBS/broadcasting/event_detector/player_tracker testleri temiz. Kamera/HUD/REPLAY gercek ACC'de calisti (REPLAY sadece zamanli RACE).
- acc_shared_memory_reader selftest GECTI; --read gercek ACC acikken DENENMEDI. modules\lfm 3 modul selftest GECTI.
- LFM lobi: https://api3.lowfuelmotorsport.com/api/race/{lobby_id} (TOKEN GEREKMEZ). 351701 -> 18 surucu: isim=vorname+nachname, elo, sr, lisans, lfm_id=user_id. satirlari_cikar_lobi ic ice sozluk yamasi yapildi.
- LFM sonuc: ayni adreste bitmis yaris race_results>GT3>OVERALL[] icinde bestlap, car_name, car_number(kapi no), user_id, rating var.
- lfm_track_history yamali (_liste_bul), settings results_urls=[.../race/351701]; --build --fetch calisti, Toyan best 106057ms DOGRU.
- Profil: https://api3.lowfuelmotorsport.com/api/users/getUserData/{lfm_user_id}?with_achievements=true (girissiz; ACC Elo=rating_by_sim sim_id 1). /api/user sadece kendi hesap.

## Kararlar
- Yarista LLM yok; proje yaris sonrasi odakli. Oyuncu araci ISIMDEN bulunur (Hakan Aksen).
- Anahtar LFM user_id (degismez), steamid onemsiz. LFM ismi "Aksen Hakan", ACC "Hakan Aksen" -> kelime kumesiyle esle.
- Hedef (Crew Chief): "arkandan yaklasanin rank'i senden iyi", "arkadan gelenin bu pistteki en hizli turu xx.xxx". Hedef sira = lobi Elo siralamasinda yerim.
- Kayitta arac = kapi numarasi (car_number) + kullanici adi olsun (kullanici istedi).
- Calisma bicimi: kisa, tek PowerShell komutu, cikti bekle; gormedigin dosyaya yama yazma.
- settings.json/.py dosyalarini Set-Content ile YAZMA (BOM); [IO.File]::WriteAllText + UTF8Encoding($false) kullan.

## Simdi
- 1) track_history: pist anahtari track_name olmali (su an tum track sozlugu); arac=car_number+kullanici adi; eski cekilen_*.json kopyalarini sil (51 kayit/17 surucu = 3 kopya). normalize_row ve satir ~123-146 oku.
- 2) Rakibin pistteki TUM zamanlarin en hizli turu: cok bitmis yarisi topla (profile/<id>/trackstats istegi BULUNAMADI).
- 3) Hedef sira modulu (lobi Elo), ACC arac eslesmesi (isim kumesi), profil_url_template=getUserData sablonu.
- 4) Zamanli yarista: python replay_yaris.py "Hakan Aksen"; log'da hedef->carId.

## Acik / dogrulanmayan
- LFM Elo formulu bilinmiyor; trackstats API adresi yok; DNF bestlap bozuk (31:23.647) elenmeli.
- Antrenmanda session_zamani_ms=-1; command_password ACC ile ayni olmali; engel_debounce=2.
- GUVENLIK: sohbette LFM oturum anahtari sizdi -> LFM'den cikis yap/tekrar gir. F12'de "cURL kopyala" KULLANMA, "URL'yi kopyala".

## Yeni hesaba notlar
- CLAUDE.md + bu dosyayi yukle. Ilk mesaj: "Projeyi devral. CLAUDE.md'ye uy, GUNCEL_DURUM.md oku, 5 satirda ozetle, siradaki adimi soyle. Ucretsiz plandayim, kisa ve tek adimli yonlendir."
- PowerShell: parantez icinde ; yerine $( ); Python pipe'ta Turkce harf bozulur. GitHub/LFM sayfalarina otomatik erisim yok, cikti elle yapistirilir.