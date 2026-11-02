# Shorts senaryo reçetesi (ölçüme dayalı) — 2 Kasım 2026

Bugünkü video (`KfHoxTt2y60`, Havuç/radar) verisi + kanalın son 30 videosu birlikte okundu.
Bu dosya, üretim ajanının **birebir uyacağı** kuralları içerir (kapak şablonu gibi deterministik).

## 1) Referans: kanalın kendi verisi

| Ölçü | Değer |
|---|---|
| Son 30 video (10 gün) | medyan **145** izlenme · ortalama 224 · en yüksek (önceki) **731** |
| Havuç/radar videosu | **1.018** izlenme (≈1 saatte) → **kanal rekoru, medyanın ~7 katı** |
| İlk saat tutma | **%48,2** (Studio tipik aralığı %13–29) |
| Ortalama izlenme | **29 sn / 55 sn = %53,5** |
| Beğeni | 6 (kanal ortalaması 2–4) |

**Okuma:** Konu + çerçeveleme algoritmayı açtı ("yaygın efsane" + "gizli askeri sır" çerçevesi).
Darboğaz izlenme değil, **35. saniyeden sonraki düşüş** ve **yorum/beklenti**.

## 2) Süre ve metin bütçesi (deterministik)

- Hedef süre: **38–42 sn** (üst sınır 45; 50+ yasak)
- Türkçe anlatım ≈ **16 karakter/sn** → metin bütçesi **600–680 karakter** (boşluklar dahil)
- Mevcut 55 sn videolar ≈ 880 karakter → **~200 karakter kısalacak**

## 3) Vuruş haritası (beat map)

| Zaman | Ne olacak | Kural |
|---|---|---|
| 0–2 sn | Kanca: efsane/iddia + merak | İlk cümle soru ya da "sanılan vs gerçek" çelişkisi. Selamlama yasak |
| 2–8 sn | Gerilim: "ama işin aslı başka" | Somut bir ayrıntı (tarih, isim, sayı) |
| 8–26 sn | Açıklama: mekanizma | Tek ana fikir; ikinci fikir yasak |
| 26–32 sn | **Ana fikir ekranda yazı olarak** | 6–8 kelime, tek satır |
| 32–38 sn | Kapanış: tek cümle + soru | Soru **aynı anda ekranda** yazılı olacak |
| 38 sn | Bitiş | Son 5 sn'de kuru logo/jenerik yasak |

Not: mevcut videoda ana fikir ~35. sn'de geliyor → izleyici tam orada düşüyor. **26–30 sn'ye çekilecek.**

## 4) Başlık kalıpları (tutmuş olanlar)

- ✅ "X Efsanesi Nasıl Y Aslında Çıktı?" → *Havuç/radar* (1.018)
- ✅ "Neden ... ? + sayı" → *Boyun 2 santim* (612)
- ✅ "Sanılan Şey Aslında Değilmiş" → *Laktik asit* (269)
- ❌ Düz tanım başlığı ("X Nedir / Nasıl Olur") → 70–86 bandında kalıyor

Başlıkta **çelişki + merak** olacak; soru işareti korunacak; emoji 1 tane.

## 5) Etkileşim

- Sabitlenen yorum **soru şeklinde** olacak ("Sen hangisine inanıyordun?") — anlatı bitince izleyici cevap yazabilsin
- Ekran metnindeki soru ile sabit yorum **aynı** olacak (tekrar = katılım)
- Videoda "abone ol" çağrısı yok; sadece kapanış sorusu

## 6) Ölçüm kapısı (yayından sonra)

| Zaman | Eşik | Karar |
|---|---|---|
| +4 saat | tutma **<%30** | kanca zayıf → sonraki videoda kanca kalıbı değişir |
| +4 saat | tutma **%30–45** | normal, süre kısaltması korunur |
| +4 saat | tutma **>%45** | kalıp doğru, aynı iskeletle devam |
| +24 saat | izlenme < medyan (145) | konu havuzu filtrelenir (efsane/çelişki teması öne alınır) |

## 7) Yasaklar

- 45 sn üstü süre, 2+ ana fikir, "Merhaba arkadaşlar" tipi giriş
- Sonunda 5 sn logo/jenerik
- Seslendirmede 15 sn'den uzun tek nefes (duraklama yok)
- Başlıkta tıklamayla uyuşmayan vaat (Shorts'ta ilk 2 sn ile çelişki = kaydırma)

## 8) Uygulama sırası

1. Metin bu bütçeyle yazılır (600–680 karakter)
2. `ses_uret.py` ile seslendirilir, süre ölçülür (**38–42 sn** aralığında değilse metin kısaltılır)
3. Kapak: `uzun_kapak_8_yeni.png` şablonu (değişmedi)
4. Yayın → +4 saat ve +24 saat ölçümleri panelden okunur
