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
| **API paneli** | ✅ 8 API sağlıklı · kota kartları anlık · %90 kırmızı şerit canlı |
| **Panelden anahtar girişi** | 🔴 **Çalışmıyor** — `SITE_SYNC_TOKEN` ölü (§10) |

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


## 7. SON İŞLEM NOTLARI
- Telegram yayın kartı; başlık, özet, açıklama, hashtag, etiket, kategori ve sabit yorumu gösterecek şekilde bağlandı.
- Dört Telegram butonu gerçek işleyiciye bağlı; kuyruğa alma hatasında Drive taşıması geri alınıyor.
- Konu sistemi Drive tablosunu ve onay metadata dosyalarını okuyup anlamsal/kelime benzerliği kontrolü yapıyor.
- Konu analizindeki sabit Gemini model 404 hatası, kullanılabilir modeli API listesinden otomatik seçerek düzeltildi.
- Yeni video, konu sistemi ve panel doğrulanmadan üretilmeyecek.


## 8. GECE DEVİR NOTU — 2026-11-08
- Konu otomasyonu çalışıyor: Drive/onay geçmişindeki 176 kayıt kontrol edildi; panel canlı beş öneriyi gösteriyor.
- Telegram eksiksiz metadata kartı ve dört buton bağlandı; Reddet gerçek dosyaları Drive çöpüne taşıdı fakat Telegram kartı gecikmeli/görsel olarak güncellenmedi.
- Son test `42427542928` üretildi ancak anlatım yalnız 16,96 sn (2,26+5,56+4,40+4,74); hedef 38–42 sn olmadığı için reddedildi, kuyruğa alınmadı.
- Yarın ilk iş: gerçek karakter sayısını kaydet, minimum anlatım/38–42 sn kalite kapısı ekle, kısa metinde yeniden üret veya durdur; sonra buton kartı anlık güncellemesini düzelt.
- API paneli eklendi: Gemini aktif HTTP 200; Groq GitHub üzerinden HTTP 403 / Cloudflare 1010; yeni video kalite kapısı ve buton testi geçmeden onaylanmayacak.


## 9. API PANELİ + KOTA SAYACI — 2026-11-08

**Ne yapıldı (hepsi canlıda, test edildi):**

1. **Gerçek panel bulundu ve düzeltildi.** Sahibin kullandığı panel `benngokhan.github.io/admin/` (Vue 3, ayrı repo). İlk turda yanlışlıkla `yt_auto_uploader/frontend/` içine yazılmıştı — **o panel kullanılmıyor.** Doğru yer: `benngokhan.github.io/admin/js/`.
2. **Kırmızı uyarı şeridi** — Kontrol Paneli ve API & Kota sayfalarında. Kural: **%90+ doluluk veya geçersiz anahtar.** Sorun yoksa hiç görünmez. Aynı uyarı tekrar yazmaz (`api_uyari_gecmisi.json`).
3. **`api_uyari.py`** (yt_auto_uploader) — `api_telemetri.json` → `api_uyarilari.json`. `api-kota.yml` her koşuda çalıştırır, çıktı commit edilir.
4. **Kartlarda anlık kota.** Bar artık **doluluk** yüzdesi gösteriyor (eskiden kalan gösteriyordu = ters mantık). %75 turuncu, **%90 kırmızı**. Her kartta `kalan / limit` + `kullanılan · %x`.
5. **`kota_sayac.py`** — Gemini ve Groq **kota bilgisini API'de vermiyor** (test edildi, rate-limit başlığı yok). Bu yüzden kendi sayacımız: urllib çağrılarını sayar, `kota_kullanim.json`'a yazar. Bağlandığı dosyalar: `motor/uret.py`, `motor/tts.py`, `mpt_uret.py`, `konu_onerileri_uret.py`, `sheets_metadata.py`, `tablet/ses.py`.
6. **Gerçek ÜCRETSİZ KATMAN limitleri** (`kota_limitleri.json`): Gemini **1.500/gün** (15/dk), Groq **1.000/gün** (30/dk), OpenRouter **50/gün** (ücretsiz modeller). Hepsi kredi kartsız.
7. **ElevenLabs kotası kaybolmuyor** — anahtar 401 verse bile son bilinen kredi gösterilir (`son_bilinen()`).

**Kanıtlı sonuçlar:** Gemini 1.498/1.500 · Groq 998/1.000 · OpenRouter 46/50 · ElevenLabs 1.384/10.000 · YouTube 6.600/10.000 · Drive 9,8/15 GB · GitHub 4.959/5.000. **8 API sağlıklı, uyarı yok.**

---

## 10. YARIN İLK İŞ — 2 AÇIK SORUN

| # | Sorun | Sebep (kanıtlı) | Çözüm |
|---|---|---|---|
| **P1** | **Panelden anahtar girişi ÇALIŞMIYOR** | `SITE_SYNC_TOKEN` ölü. GitHub log: `failed to fetch public key: HTTP 401: Bad credentials`. Panel "kaydedildi" diyordu ama GitHub reddediyordu. | Yeni PAT (`repo` + `workflow`) → Secrets → `SITE_SYNC_TOKEN` **Update**. Sonra `api_secret_sonuc.json` doğrulaması devrede. |
| **P2** | **ElevenLabs 401** | Anahtar GitHub'a girdi (51 karakter, `sk_3a3…`) ama **yetki eksik**: `"The API key you used is missing the permission user_read"` | ElevenLabs → yeni anahtar → **User: Read** + Voices: Read + TTS: Write işaretle → Secrets `ELEVENLABS_API_KEY` **Update** |

**Not:** P2 üretimi durdurmuyor — ses **Gemini TTS**'ten geliyor (`motor/ayarlar.json` → `saglayici: gemini_tts`, `voice_id: Charon`). ElevenLabs sadece yedek.

---

## 11. PANEL ANAHTAR GİRİŞİ — NASIL ÇALIŞMALI

Panel → `/api/secret-yaz` → GitHub `repository_dispatch(api_anahtar)` → `api-kota.yml` → `gh secret set` → sonuç `api_secret_sonuc.json`'a yazılır → panel **90 sn bekleyip gerçek sonucu gösterir** (artık sahte "kaydedildi" demiyor).

Panelden yazılabilen 5 anahtar: `ELEVENLABS_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN`.

**Anahtar asla repoya/loga yazılmaz** — `::add-mask::` ile maskelenir.

