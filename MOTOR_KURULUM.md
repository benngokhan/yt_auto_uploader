# Bilgi Dozu Üretim Motoru — kurulum durumu

Kaynak: Drive `CEO / Video Üretimi - Gerekli Kaynaklar` klasörü (kullanıcının kendi pilot motoru).
Kod repoya `motor/` altına alındı (tarihsel referans olduğu gibi duruyor, **olduğu gibi çalışmaz**).

## Klasörde ne var (doğrulandı)
| Dosya | Ne işe yarıyor | Durum |
|---|---|---|
| `render_engine.py` | Katman motoru: üst başlık bandı (1. satır beyaz + 2. satır sarı `#FFD600` + emoji), karaoke altyazı bandı (aktif kelime sarı), rozet (lime `#DCFF2E`), kaynak satırı, wordmark, animasyonlu **TAKİP ET** butonu, teal-amber sinematik renk, biyolüminesans parçacıklar, LUFS miks | Çalışır ama yollar sabit |
| `karaoke_timing.py` | Gerçek ses → kelime zamanlaması (faster-whisper), `validate_alignment` (SHA-256 + kelime sırası doğrulama) | Bağımlılık: `requirements-karaoke.txt` |
| `audio_balance.py` | Konuşma + müzik dengesi, konuşurken otomatik kısma (ducking), fade-out | Hazır |
| `dinamik_baslik.py` | Anlatıma bağlı değişen üst başlıklar (0.25 sn yumuşak geçiş) | Hazır (13 test) |
| `bgm_composer.py` | Konuya göre fon müziği üretimi | Motor otomatik çağırmıyor |
| `visual_style_cinematic.py` | Onaylı görsel stil istemi (teal gölge + amber vurgu) | Yol uyarlaması gerek |
| `build_shorts_video.py` | Pilot örneği: 6 sahne, sabit görsel/ses yolları | **Tarihsel** — şablon olarak kullanılacak |
| `02_FONT` (Drive) | Montserrat Black/Bold + NotoColorEmoji | Actions'ta indirilecek |

## Kurallar (CEO `00_ONCE_OKU_Uretim_Kurallari.md`)
- Shorts: 9:16, 1080×1920, **50–58 sn**, **60 fps**
- Altyazı: 2 satır, o an seslendirilen kelime **sarı**, diğerleri beyaz
- Ses: **voice-02** (doğal tempolu kadın); referans WAV var, farklı ses sessizce konmaz
- Müzik: konuşurken ~2 LU kısılır, sonunda 3 sn fade-out
- Görseller: AI sinematik, teal gölge + amber vurgu; yazı/filigran/stok yok
- Kapanış: "Sıradaki videoda … bakacağız" + küçük animasyonlu TAKİP ET butonu
- Kapak: kullanıcı yaptırır (bu hat kapak basmaz)

## Eksik olan (kurulacak parçalar)
1. **Orkestratör** (`motor/uret.py`): konu → 6 sahnelik plan (ses metni, üst başlık satır1/satır2+emoji, altyazı) → sahne sahne TTS (voice-02) → kelime hizalaması → 6 AI görsel → `scenes_meta` + `scene_configs` JSON → `render_video_master` → mp4
2. **Yol uyarlaması**: `FONT_*`, `EMOJI_FONT_PATH`, `BGM_PATH` sabitleri `motor/assets/` altına taşınacak
3. **Görsel üretimi**: AI görsel servisi bağlanacak (teal/amber stil istemi hazır)
4. **Teslim**: mp4 → Drive `Kısa Video` + tabloya satır (mevcut `mpt_uret.py` teslim kodu yeniden kullanılır)
5. **Actions**: `motor-uret.yml` (elle tetik → test)

## Gerekli anahtarlar
- `ELEVENLABS_VOICE_ID` = **voice-02** ses ID'si (zorunlu)
- Görsel üretimi için servis seçimi (Gemini image / başka)
