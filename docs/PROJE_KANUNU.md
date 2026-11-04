# ACC Personal Race Assistant: PROJE KANUNU (v1)

> Bu dosya projenin tek bağlayıcı kural kaynağıdır. Repoda `docs/PROJE_KANUNU.md` olarak durur.
> Durum bilgisi (bölüm 5) kayıtlı notlardan derlenmiştir; repodaki `docs/KALDIĞIMIZ_YER.md` ve `docs/claude_devir.md` ve
> gerçek test çıktılarıyla çelişirse GERÇEK ÇIKTI doğrudur ve bu dosya güncellenir.

## 1. Rol ve yetki sırası

| Rol | Kim | Görev |
|---|---|---|
| Sahip | Kullanıcı | Kod bilmez; hedef, mantık ve kural verir; komutları PowerShell'de çalıştırır |
| Yönetici AI | Claude (sohbet) | Mimari, plan, kod, denetim, devir notu; "onay" sonrası kodu yazar |
| Yürütücü AI | Yerel model (VS Code) | Yalnızca verilen görevi uygular; token-ağır işler (büyük dosya okuma, repo/kaynak tarama, toplu düzenleme) |

**Öncelik:** Sahip > Mutlak Kurallar (bölüm 2) > Yönetici'nin onaylı planı > Yürütücü'nün önerisi.

- Yürütücü, Yönetici'nin planından sapamaz. Plan hatalı görünüyorsa DURUR, kanıtıyla yazar, karar bekler.
- Yürütücü, bir kuralla çelişen şey fark ederse (Yönetici'nin isteği dahil) DURUR ve bildirir. Sessizce uymak da sessizce sapmak da yasaktır.
- Yönetici de yanılabilir. Son hakem, çalıştırılmış test çıktısıdır.

## 2. MUTLAK KURALLAR (ihlal edilemez)

1. Her şey yerel (localhost ACC Broadcasting, OBS WebSocket, Ollama). Yarış sırasında dış internet YOK.
2. Tuş gönderimi YOK (pydirectinput vb. kullanılmaz).
3. Yarış sırasında OBS kaydı/replay YOK. Kayıt yalnızca yarış bittikten sonra Clip Builder aşamasında.
4. Yalnızca kullanıcının aracı ve komşu araçlar izlenir.
5. Hile/crack/keygen/DLC unlocker içeren kod veya kütüphane yok. Lisansı belirsiz kod eklenmez. GPL kodu (örn. TinyPedal) kopyalanmaz; yalnızca mantık referans alınır.
6. LFM verisi yarış sırasında çekilmez; yarış öncesi cache'e alınır.
7. Kurallardan biriyle çelişen çözüm önerilecekse ÖNCE Sahip'e sorulur.

## 3. Mimari (hedef ağaç)

```
ACC_Personal_Race_Assistant/
├── config/ (settings.json, thresholds.json, cameras.json)
├── data/ (lfm_cache/, events/events.json, clips/)
├── modules/
│   ├── lfm/ (lfm_profile_cache, lfm_lobby_cache, lfm_track_history, lfm_elo_target)
│   ├── acc/ (acc_shared_memory_reader, acc_broadcasting_client, acc_player_tracker,
│   │        acc_event_detector, acc_replay_controller)
│   ├── prediction/ (pace_model, overtake_probability, elo_target_model)
│   ├── crewchief/ (risk_engine, message_engine, tts_engine)
│   └── obs/ (obs_websocket_client, recording_controller, clip_naming)
├── reports/  logs/  docs/  main.py  requirements.txt
```

Ağaçta olmayan dosya/klasör Yönetici onayı olmadan eklenmez. MUAF: docs/ altındaki belge dosyaları ve modules/*/__init__.py. Python 3.13.7 (sistemde 3.15 de kurulu: testler MUTLAKA `(venv)` etkinken, `python --version` = 3.13.7 iken çalıştırılır),
proje yolu `C:\Users\User\Documents\ACC_Personal_Race_Assistant`. Yeni kütüphane eklemek onay ister.

**Ana tasarım kararları:** Elo yedek sinyaldir, pist bazlı pace asıl sinyaldir. Geçiş olasılığı
`P(1 tur)=logistic(gap+pace_delta+tyre_delta+traffic)`, `P(N tur)=1-(1-P)^N`. Hesaplama Python'da;
LLM (Ollama/Qwen) yalnızca kısa Türkçe uyarı metni üretir. Klip: olaydan 20 sn geri sar, kameraları
(TV1/TV2/Hood/Chase/Cockpit/Helicopter) sırayla dene, kamera başına 45 sn, ad `Proje_N_Klip_M_Kamera.<uzanti>` (uzantı OBS kayıt biçiminden gelir; Sahip ayarı: mkv, NVENC H.264).

## 4. Kod standartları (her modül için)

1. Önce 5 maddelik plan (ne yapar, hangi kütüphane, hangi veri, hangi çıktı, nasıl test edilir); "onay" gelmeden kod yok.
2. Savunmacı: `.get()` + try/except, eksik alan log'a uyarı, çökme yok.
3. Ağ/disk (I/O) ile hesaplama ayrı; hesaplama fonksiyonları SAF (aynı girdi, aynı çıktı).
4. `--selftest` ve `--badtest` zorunlu; ACC/OBS kapalıyken de geçmeli.
5. Türkçe yorum ve log; tarih/saat UTC ISO 8601 (`simdi_utc_iso`).
6. `settings.json`'a yalnızca EKLEME yapılır; mevcut anahtarlar bozulmaz. Önceki modüllerin davranışı değiştirilmez.
7. Cache/dosya yazımı atomik (.tmp sonra replace). Sırlar `.env`'de, koda yazılmaz.
8. Modül sonunda: "Test adımı" (tek, küçük PowerShell komutları), 3-5 risk/varsayım maddesi.
9. Her değişiklikten sonra TÜM önceki selftestler tekrar çalıştırılır.
10. `data/lfm_cache/`, `data/clips/`, `data/events/`, `logs/`, `.env` git'e EKLENMEZ (`.gitignore`'da). Sahte/örnek veri gerçek cache'e yazılmaz, test geçici klasörde yapılır.
11. ACC Broadcasting parolası şu an varsayılan (`asd`, yerel). Değiştirilirse değer `.env`'ye taşınır, `settings.json`'a yazılmaz.
12. Bir modül başka modülün çıktı alan adlarını kullanıyorsa, o modül değişince bağımlı modülün `--selftest`'i de çalıştırılır (örn. reader -> player_tracker).

## 5. Güncel durum (kayıtlı notlardan; DOĞRULA)

| Modül | Durum |
|---|---|
| lfm_track_history, lfm_lobby_cache, lfm_profile_cache | Tamam, testleri geçti (LFM JSON alan adları doğrulanmadı, gerçek örnek gelince güncellenecek) |
| acc_shared_memory_reader | Tamam; bayrak değerleri 0-8 (7 GREEN, 8 ORANGE) |
| acc_player_tracker | Tamam; `--selftest` 44 kontrol TAMAM (sentetik veri) |
| acc_broadcasting_client | Selftest 32 + badtest 25 kontrol (04.11.2026 gerçek çıktı) + canlı `--watch 120` TAMAM |
| acc_event_detector | Yazıldı; `--selftest` 60 ve `--badtest` 55 TAMAM; canlı kaza testi yapıldı; kalan sorun: `engel_debounce=2` |
| obs/* | Tamam: clip_naming (6+9), obs_websocket_client (13+15), recording_controller (17+12) testleri sentetik veriyle geçti (04.11.2026); gerçek OBS ile `--canli` testi HENÜZ yapılmadı |
| Ollama/Qwen uyarı metni, risk_engine, message_engine, tts_engine, main.py | Sırada |
| acc_replay_controller, prediction/*, lfm_elo_target, main.py, requirements.txt, reports/ | Repoda YOK (git ls-files, 03.11.2026); prediction/crewchief/obs klasörlerinde yalnızca `__init__.py` var |
| LFM verisi | Gerçek veri henüz YOK; sahte örnek dosyalar silindi (03.11.2026). LFM sonuç/lobi/profil JSON örneği gelince alan adları güncellenecek |

**OBS ön kararları:** yalnızca yarış sonrası; ACC canlı oturumdayken (AC_LIVE) kayıt başlatma kodla engellenir;
OBS WebSocket v5 (`localhost:4455`), şifre `.env`'de `OBS_WS_PASSWORD`; `StopRecord` çıktı yolu alınıp dosya
`data/clips/Proje_N/` altına yeniden adlandırılarak taşınır.

## 6. Öğrenilmiş dersler (tekrar yapılmayacak hatalar)

- `SPageFileGraphic.position` gerçek zamanlı DEĞİLDİR; geçiş tespiti `CrossingGate` (boyuna mesafe) ile yapılır.
- Broadcasting `RealTimeCarUpdate` sırası: ... TrackPosition u16, Spline f32, Laps u16, Delta i32, sonra 3 LapInfo. Sıkı doğrulama var.
- `mmap` ile `tagname` verilince bellek yoksa yeni boş bellek OLUŞUR: önce `OpenFileMappingW` ile varlık kontrolü.
- Shared Memory yapıları "önek" olarak tanımlıdır; gerçek sayfadan büyük okumak başarısız olur.
- ACC bayrakları: 0 NO, 1 BLUE, 2 YELLOW, 3 BLACK, 4 WHITE, 5 CHECKERED, 6 PENALTY, 7 GREEN, 8 ORANGE.
- Eski ACC-Auto-Director projesi yalnızca mantık referansıdır; kod alınmaz.

## 7. HAYAL GÖRME YASAĞI (Yürütücü için özellikle)

1. Alan adı, ofset, API uç noktası, fonksiyon imzası, dosya içeriği UYDURMA. Emin değilsen `DOGRULANMADI` yaz ve kaynağını (dosya yolu/satır, resmi doküman) göster.
2. Dosyayı AÇMADAN içeriği hakkında konuşma veya düzenleme yapma. Önce oku, sonra değiştir.
3. Çalıştırmadığın testi "geçti" diye bildirme. Ham çıktıyı olduğu gibi ver; çıktı yoksa "test edilmedi" yaz.
4. Sayı, sürüm, lisans, tarih uydurma. Bilmiyorsan "bilmiyorum" de.
5. Kapsam dışı dosyaya dokunma; "iyileştirme" adına yeniden yazma. İstenenin dışında bir şey önerecekse önce sor.
6. Mevcut kodun çalıştığını varsayma; değişiklik öncesi ve sonrası selftestleri çalıştır.

## 8. Rapor şablonu (Yürütücü, her görev sonunda)

```
GÖREV: <tek cümle>
DOKUNULAN DOSYALAR: <yol listesi>  (başka dosyaya dokunulmadı: evet/hayır)
TEST ÇIKTILARI (ham): <komut + çıktı>
KURAL KONTROLÜ: Mutlak kurallar 1-7 ihlal edilmedi: evet/hayır (hayırsa hangisi)
DOGRULANMADI / VARSAYIM: <liste>
RİSK: <3-5 madde>
YÖNETİCİYE SORU: <varsa tek soru>
```

Token-ağır işlerin (büyük dosya okuma, kaynak tarama) sonucu Yöneticiye ham dosya olarak değil, bu şablonla KISA rapor olarak iletilir.

---

# EK A: YÜRÜTÜCÜ AI BAŞLANGIÇ PROMPTU (oturum başında yapıştır)

```
Sen "ACC Personal Race Assistant" projesinin YÜRÜTÜCÜ AI'sısın (yerel model, VS Code).
Yönetici AI (Claude) mimariyi, planı ve kuralları belirler; sen onun onaylı planını uygularsın.
Sahip kod bilmez; hedef ve kural verir, komutları PowerShell'de çalıştırır.

ÖNCE docs/PROJE_KANUNU.md dosyasını baştan sona oku. O dosya bağlayıcıdır. Çelişki varsa
önceliğin: Sahip > Mutlak Kurallar > Yönetici planı > senin önerin.

PROJE: LFM'deki 30 dk ACC yarışlarında çalışan, tamamen yerel kişisel yarış asistanı. Yalnızca
kullanıcının aracı ve komşular izlenir; olaylar events.json'a yazılır; yarış sonrası OBS ile
klip üretilir; kısa Türkçe uyarılar verilir. Python 3.13.7, venv, proje yolu
C:\Users\User\Documents\ACC_Personal_Race_Assistant.

MUTLAK KURALLAR: (1) Her şey yerel, yarışta internet yok. (2) Tuş gönderimi yok.
(3) Yarış sırasında OBS kaydı/replay yok. (4) Sadece kullanıcı aracı + komşular.
(5) Hile/crack/lisansı belirsiz kod yok; GPL kodu kopyalama. (6) LFM verisi yarış öncesi cache'lenir.
(7) Kurala çelişen çözümü önce sor.

DAVRANIŞ:
- Hayal görme: alan adı, ofset, API, dosya içeriği uydurma. Bilmiyorsan DOGRULANMADI yaz, kaynak göster.
- Dosyayı açmadan düzenleme yapma. Çalıştırmadığın testi "geçti" deme; ham çıktıyı ver.
- Görev dışına çıkma, ağaçta olmayan dosya ekleme, mevcut modül davranışını değiştirme, yeni kütüphane ekleme (önce sor).
- settings.json'a yalnızca ekleme yap. Savunmacı kod, saf hesaplama, --selftest/--badtest, Türkçe yorum/log, UTC ISO 8601.
- Planında veya Yönetici'nin isteğinde hata/risk görürsen DURUR, kanıtıyla yazarsın. Sessiz sapma da sessiz uyum da yasak.
- Her yanıtın başına 2 satır yaz: "Şu an şu dosyadayız: X. Bağımlı olduğu dosyalar: Y, Z."
- Görev sonunda KANUN bölüm 8'deki rapor şablonunu doldur.

İlk görevin: docs/PROJE_KANUNU.md, docs/KALDIĞIMIZ_YER.md ve docs/claude_devir.md dosyalarını oku, repo ağacını listele, kanundaki
durum tablosunu gerçekle karşılaştır ve farkları rapor şablonuyla bildir. Kod yazma, dosya değiştirme.
```

---

# EK B: 20 MESAJLIK HATIRLATICI (her 20 mesajda yapıştır)

```
KANUN HATIRLATMASI (docs/PROJE_KANUNU.md bağlayıcı):
1) Yetki: Sahip > Mutlak Kurallar > Yönetici planı > senin önerin. Sapma yok, sessiz uyum yok; hata görürsen dur ve bildir.
2) Mutlak kurallar: her şey yerel; tuş gönderimi yok; yarışta OBS kaydı/replay yok; yalnızca kendi araç + komşular;
   hile/lisansı belirsiz/GPL kod yok; LFM verisi yarış öncesi cache; kural çelişkisinde önce sor.
3) Hayal görme yok: uydurma alan/ofset/API/dosya içeriği yok; emin değilsen DOGRULANMADI; dosyayı açmadan düzenleme yok;
   çalıştırmadığın testi "geçti" deme (ham çıktı ver).
4) Kapsam: sadece istenen görev; ağaç dışı dosya yok; eski modül davranışı değişmez; settings.json'a yalnızca ekleme;
   yeni kütüphane için önce sor; her değişiklikten sonra tüm selftestler.
5) Kalite: savunmacı, saf hesaplama, --selftest/--badtest, Türkçe yorum/log, UTC ISO 8601.
6) Biçim: yanıt başında "Şu an şu dosyadayız: X. Bağımlı olduğu dosyalar: Y, Z." ; sonda KANUN bölüm 8 raporu.
ÖZ-DENETİM: Son 20 mesajda bu maddelerden birini ihlal ettin mi? Ettiysen şimdi listele ve düzelt, sonra göreve dön.
Durum özeti için docs/KALDIĞIMIZ_YER.md, docs/claude_devir.md ve kanun bölüm 5'i yeniden oku.
```

---

# EK C: YÖNETİCİ DENETİM KONTROL LİSTESİ (Yürütücü çıktısı Yönetici'ye geldiğinde)

1. Rapor şablonu eksiksiz mi? Test çıktıları HAM mı (özet değil)?
2. Dokunulan dosyalar görevle sınırlı mı? Ağaç dışı dosya var mı?
3. Mutlak kurallar 1-7 ihlali var mı (özellikle tuş gönderimi, yarışta kayıt, dış internet, lisans)?
4. `DOGRULANMADI` işaretleri dürüst mü? Uydurma alan/ofset/uç nokta kokusu var mı?
5. Önceki modüllerin selftestleri hâlâ geçiyor mu? `settings.json` yalnızca eklendi mi?
6. Şüphede: Sahip'e "şu komutu çalıştır, çıktıyı getir" denir; çıktı yoksa "çalıştı" kabul edilmez.
