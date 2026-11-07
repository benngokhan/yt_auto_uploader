# DEVİR — yeni ajan buradan başlar
> **KURAL:** Her iş bitince CEO bu dosyayı günceller (en fazla 5 satır ekler).
> Yeni ajan ilk iş olarak bunu okur → sahibi hiçbir şey anlatmak zorunda kalmaz.
> Son güncelleme: **2026-11-08**

---

## 1. TEK SATIR BAŞLATMA (sahibi yeni ajana bunu verir)

```
Sen bu projenin CEO'sun. Önce repo'daki CEO-compiled.md ve DEVIR.md dosyalarını oku,
sonra işe başla. Bana sadece sonuç yaz.
```

Başka hiçbir şey anlatmasına gerek yok. Proje bilgisi, kurallar, sınırlar — hepsi bu iki dosyada.

---

## 2. PROJE NE (30 saniye)

**Bilgi Dozu** — Türkçe bilim/merak YouTube kanalı.
- Günde **2 Shorts** yayın (12:30 + 19:30 TR)
- Otomasyon: GitHub Actions → Drive kuyruğu → YouTube
- Repo: `benngokhan/yt_auto_uploader` (private)
- Tek klasör: `1Mht2RXUJG9qAhinl8PGjMgOXg58AOUIR` (video + kapak birlikte)
- Kalite kapısı: `dogrula.py` 39/39 · 38-42 s · 30-70 MB

---

## 3. SON DURUM (2026-11-08)

| Konu | Durum |
|---|---|
| Yayın akışı | ✅ Çalışıyor — 07.11'de iki slot da yayınlandı (video_164, 165) |
| Stok | **10 Shorts + 10 kapak** hazır → ~5 gün yeter |
| Sıradaki video | `video_166.mp4` |
| Motor | 🔴 **İki hata veriyor** (08.11 tespit) — aşağıya bak |
| Açık karar | Uzun videolar bırakılsın mı? (sayılar: 14-129 izlenme vs Shorts 532) |
| Bilinen sorun | Analitik: 151 videodan sadece 38'inde izlenme verisi · günde +7 izlenme |

---

## 4. SAHİBİNİN KALICI KARARLARI

1. **Günde 2 video.** 3 değil.
2. **Uzun video sevilmiyor** — sadece Cuma, kanalda olsun diye.
3. **En az 3 günlük stok tamponu** her zaman dursun (ters giderse nefes payı).
4. **Onay sorma.** Söylenen iş yapılır, bitince sonuç yazılır.
5. **Sade ve kısa yaz.** Teknik terim yığını yok, en fazla 6 satır.
6. **Adım adım gidilir.** İleri atlama yok.

---

## 4b. MOTOR HATALARI (2026-11-08 tespit · ikisi de tek satırlık iş)

| # | İş | Hata | Sebep (kanıtlı) |
|---|---|---|---|
| M1 | Motor - video üret | `HTTP 403 Forbidden` → `KeyError: 'content'` | **Gemini/Groq API anahtarı boş.** `config.json` → `gemini_api_key: ""` · `groq_api_key: ""` |
| M2 | Analizli konu önerilerini güncelle | `HTTP 404 Not Found` | Bir uç nokta/ID yanlış. Kod okunup bulunacak |

**M1 çözümü:** `.github/workflows` → Secrets'a `GEMINI_API_KEY` eklenmeli.
GitHub Actions env'de görünüyordu (`GEMINI_API_KEY: ***`) ama anahtar geçersiz/süresi dolmuş olabilir → anahtar yenilenmeli.

---

## 5. AÇIK İŞLER (sıraya göre)

- [ ] **M1:** Gemini API anahtarını yenile (sahibinde) → motor çalışır
- [ ] **M2:** 404 veren uç noktayı bul ve düzelt (CEO)
- [ ] Motor kurulumu bitince: panel→Telegram onay akışı test
- [ ] Uzun video kararı (sahibinde)
- [ ] Analitik kapsamı: 113 videoda veri yok — düzeltilecek
- [ ] Tablo senkron: video_164 yükleme saati boş, düzeltilecek
- [ ] Başlık kuralı: %85'i 70 karakteri aşıyor

---

## 6. AJAN DEĞİŞİRSE

1. Yeni ajana §1'deki tek satırı ver.
2. Ajan `CEO-compiled.md` + bu dosyayı okur, işe başlar.
3. Ajan iş bitince bu dosyanın §3 ve §5'ini günceller.

**Sahibi hiçbir şeyi tekrar anlatmaz.** Bilgi dosyada durur, ajanın hafızasında değil.

## CEO GÜNCELLEME — 2026-11-08
- Telegram yayın kartı tüm metadata ve dört gerçek işlem butonuyla bağlandı; işleyici testi geçti.
- Konu önerisi 404 hatası için Gemini modeli otomatik keşif/seçim sistemine çevrildi.
- Mevcut köpekbalığı videosu onaysız kalacak; işlem yapılmayacak.
- Sıradaki kapı: konu analizi başarılı sonuç + panel doğrulaması; ardından tek uçtan uca video testi.
