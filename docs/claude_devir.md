\# ACC Personal Race Assistant – Oturum Devir Notu



\## 1. Proje özeti

\- ACC Personal Race Assistant: LFM 30 dk yarışları için, tamamen yerel çalışan yarış asistanı.

\- İnternet yok (LFM verisi önceden önbelleğe alınır), oyuna tuş gönderimi yok.

\- Kapsam: sadece kullanıcı + komşu araçlar (ön/arka).

\- Akış: olay algılama -> events.json -> OBS (kurgu/sahne) + Ollama/Qwen (TTS/yorum) -> CrewChief benzeri uyarılar.

\- GitHub: xolmeca/ACC\_Personal\_Race\_Assistant



\## 2. Ortam

\- Python 3.13.7, venv, Windows 11, komutları kullanıcı PowerShell'den kendisi çalıştırır.

\- Proje yolu: <DOLDUR>

\- Kurulu paketler: <DOLDUR: pip freeze çıktısı>

\- Yerel AI: VS Code + Continue + Qwen 14B (büyük dosya okuma / kaynak tarama için).



\## 3. Modüller

| Modül | Durum |

|---|---|

| lfm\_track\_history | Tamam, test geçti |

| lfm\_lobby\_cache | Tamam, test geçti |

| lfm\_profile\_cache | Tamam, test geçti |

| acc\_shared\_memory\_reader | Tamam, gerçek ACC verisiyle doğrulandı |

| acc\_player\_tracker | Tamam, heading düzeltmesi canlıda doğrulandı |

| acc\_broadcasting\_client | Sentetik selftest 32 kontrol GEÇTİ; düzeltilmiş sürümle canlı --watch HENÜZ YOK |

| acc\_event\_detector | Yazıldı; --selftest/--badtest var; ÇALIŞTIRILMADI |



Önemli ders: SPageFileGraphic.position realtime DEĞİL. Overtake için CrossingGate (boyuna\_m) kullanılır.



\## 4. Konfigürasyon

\- settings.json: "broadcasting" bölümü (port 9000, connection\_password, command\_password). Değerler dosyada.

\- thresholds.json: event\_detector bölümü yoksa kod varsayılanları kullanılır.

\- cameras.json, CREDITS.md, .gitignore: <DOLDUR: içerik/durum>



\## 5. Bu oturumdaki kritik düzeltmeler

\*\*Teşhis:\*\* Canlı --watch'ta spline hep 0.000, ön/arka mesafeler anlamsızdı (7.78e-42, 5552.0). Ham bayt analizi: car update paketi 89 bayt; spline, track\_position'dan hemen sonra f32 olarak geliyor.



\*\*Düzeltmeler (acc\_broadcasting\_client.py):\*\*

\- Eski A/B layout (car\_layout, layout\_kilitli, aday skorlama döngüsü) kaldırıldı.

\- `\_son\_spline` / `\_spline\_ret` eklendi (Cozumleyici.\_\_init\_\_).

\- `\_arac`: sabit yerleşim + sıkı doğrulama (paket tam tüketilmeli, 0<=spline<=1, denormal yok, delta/laps/lap süresi makul, spline atlama kontrolü; 10 ardışık retten sonra referans sıfırlanır; hatada ProtocolError, paket atılır, durum bozulmaz).

\- izle() print ve selftest layout satırı temizlendi.



\*\*Alan sırası hatası:\*\* Yanlış "spline, delta, laps" yerine doğru sıra:

`TrackPosition u16 -> Spline f32 -> Laps u16 -> Delta i32 -> 3x LapInfo (best, last, current)`

\- LapInfo: laptime i32, car u16, driver u16, split\_sayisi u8, splitler i32 x n, bayraklar 4 x u8.

\- Kaynaklar: toonknapen/accbroadcastingsdk buffer.go (satır 118) ve docs.rs/acbc RealtimeCarUpdate.

\- Düzeltilen yerler: `\_arac` (satır \~405) `r.f32(), r.u16(), r.i32()`; `\_p\_car` (satır \~852) `struct.pack("<fHi", spline, laps, 250)`.

\- Not: ilk paketlerde laps=0 ve delta=0 olduğu için hata canlıda geç fark edildi.

\- Selftest: TAMAM (32 kontrol).



\## 6. Yedekler

acc\_broadcasting\_client.py.yedek ... .yedek5 (hangisinin hangi aşamaya ait olduğu: <DOLDUR>)



\## 7. Sıradaki adımlar

1\. Broadcasting canlı `--watch 120`. Başarı: spline 0<x<1 ve artıyor, tur sonunda 1->0, laps tur bitince +1, delta 0'da takılı değil, bayt uyuşmazlığı 0, ret oranı düşük, saçma ön/arka mesafe yok. Ret nedenleri araç bazında dökülsün (istatistik şu an sadece konsola yazılıyor, log'a değil).

2\. event\_detector `--selftest` ve `--badtest`.

3\. event\_detector canlı `--watch 120`.

4\. OBS entegrasyonu.

5\. Ollama/Qwen TTS.

6\. CrewChief benzeri uyarı katmanı.

7\. main.py ana döngü.



\## 8. Çalışma protokolü

\- Her yanıtın başında: "Şu an şu dosyadayız: X".

\- Her modül için önce 5 maddelik plan, kod onaydan sonra.

\- Mesajlar kısa; tek, küçük komut/kod bloğu; çıktı beklenir.

\- Kodu görmeden fonksiyonu tahminle yazma; önce istenen satır/fonksiyon yapıştırılır.

\- Büyük dosya okuma / kaynak-jar tarama için VS Code + Qwen 14B kullan, sohbet tokenını harcama.

\- Kaynak/protokol bilgisini açık kaynaktan doğrula (bu oturumda Claude'un iki alan-sırası hatası böyle yakalandı).



\## 9. Bilinen riskler

\- Broadcasting düzeltmesi canlıda doğrulanmadı.

\- thresholds.json'da event\_detector bölümü yoksa varsayılanlar geçerli.

\- Cooldown ve events.json gerçek yarış verisiyle test edilmeden OBS/Ollama'ya geçilmemeli.

\- CrossingGate, boyuna\_m işaret değişimine dayanıyor; kenar durumlar (pit, tur sonu sarma) canlıda izlenmeli.



\## 10. Yeni oturumda ilk mesaj

```

Proje: ACC Personal Race Assistant (Python 3.13.7, yerel, GitHub xolmeca/ACC\_Personal\_Race\_Assistant).

Ekteki docs/OTURUM\_DEVIR.md devir notudur; oku ve oradan devam et.

Durum: broadcasting\_client sentetik selftest 32/32 geçti, canlı --watch 120 sırada.

Kurallar: kısa cevap, önce plan, tek küçük komut bloğu, kodu görmeden tahmin yazma,

büyük dosya okumada VS Code + Qwen 14B kullanmamı hatırlat.

İlk iş: --watch 120 çıktısını değerlendirmek.

```

