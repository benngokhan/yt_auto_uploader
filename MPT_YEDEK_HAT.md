# Yedek Üretim Hattı (MoneyPrinterTurbo)

Amaç: ana üretim (hazır şablonlu, elle onaylı videolar) durursa kanal susmasın.
Günde 2 videoyu bu hat üretir; şablon sabit olduğu için bozulma riski yok.

## Akış
```
konu → MoneyPrinterTurbo (stok görüntü + altyazı + ses)
     → video_<N>.mp4  → Drive / Kısa Video klasörü
     → tabloya "BEKLEMEDE" satırı  → mevcut yükleyici (uploader.py) slotta YouTube'a atar
```

## Nerede çalışır
GitHub Actions → **Yedek Üretim (MoneyPrinterTurbo)** (`workflow_dispatch`, elle).
Sunucu yok, ek ücret yok; GitHub'ın ücretsiz dakikalarını kullanır (~10–15 dk/run).
İlk test başarılı olunca `.github/workflows/mpt-uret.yml` içindeki `schedule` bloğu açılır → 08:00 ve 17:00 TR.

## Gereken 2 secret
| Secret | Nereden | Not |
|---|---|---|
| `PIXABAY_API_KEY` | https://pixabay.com/api/docs/ (giriş yapınca anahtar sayfada yazar) | Ücretsiz. **Pexels yeni anahtar vermeyi durdurdu** (Kas 2026) → varsayılan Pixabay. Alternatif: `COVERR_API_KEY`. |
| `ELEVENLABS_VOICE_ID` | ElevenLabs panel → ses → ID | Kanonik ses. **Fallback yok**; yoksa hat durur. |

Görüntü kaynağı otomatik seçilir: `PIXABAY_API_KEY` varsa Pixabay, yoksa Pexels/Coverr.
`VIDEO_SOURCE` değişkeni (Variables) ile elle sabitlenebilir.

Zaten tanımlı olanlar: `GEMINI_API_KEY` (senaryo), `ELEVENLABS_API_KEY` (ses),
`GOOGLE_TOKEN_JSON` + `GOOGLE_CLIENT_SECRETS_JSON` (Drive/tablo), `TELEGRAM_*` (bildirim).

## Ayarlar (`mpt_uret.py`)
- Süre: hedef **38–42 sn**, sınır **30–45 sn** (`SENARYO_KURALLARI.md`). Dışına çıkarsa sadece **uyarı** basar, üretimi durdurmaz.
- Metin: **600–680 karakter**, tek fikir, selamlama yasak, kapanış sorusu ekranda.
- Format: **9:16**, klip süresi 4 sn, tek video.
- Ses: ElevenLabs (kanonik voice_id).

## Elle çalıştırma
Actions → **Yedek Üretim (MoneyPrinterTurbo)** → *Run workflow*
- `konu`: tek cümle (örn. "Karıncalar neden kendi ağırlıklarının 50 katını taşır?")
- `kuru`: `true` ise üretir ama Drive'a/tabloya dokunmaz.

## Test (ses doğrulanmadan)
Kuru çalışmada hattı denemek için `--ses-edge` var; Edge Türkçe ses kullanır ve
**yayına alınmaz** (`--kuru` olmadan çalışmaz, kanonik ses kuralı).

## Bilinen sınırlar
- Kapak üretmez → video kapaksız yayınlanır (mevcut kural: kapak yoksa uyarı, yayın devam).
- Uzun video üretmez, sadece short.
- Stok görüntüler temsilîdir; kaynak satırı tabloya "MoneyPrinterTurbo (yedek hat)" olarak yazılır.
