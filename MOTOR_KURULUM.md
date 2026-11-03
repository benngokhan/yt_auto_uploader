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

## Sahne şeması (pilottan çıkarıldı — orkestratörün üreteceği yapı)

`render_video_master(out_mp4, scenes_cfg, vo_files, plates_bgr, source_line, is_wide=False, target_min_dur=50, target_max_dur=58)`

Her sahne (`scene_configs` öğesi):

```python
{
  "img": "scene_01_hook.png",          # sahne görseli (1080x1920 kaynak)
  "zoom": (1.00, 1.14),                # Ken Burns zoom başlangıç→bitiş
  "pan_x": (0.0, 0.0),                 # yatay kaydırma (px)
  "pan_y": (24.0, -24.0),              # dikey kaydırma (px)
  "emoji": "❓",                       # üst başlık emojisi
  "title_line1": "SUDA PARMAKLAR",     # BEYAZ
  "title_line2": "NEDEN BURUŞUR?",     # SARI #FFD600
  "subs": [                            # (altyazı satırı, vurgulanacak kelimeler)
    ("Duşta ya da denizde kaldığında", []),
    ("parmak uçların neden buruşur?", ["neden", "buruşur?"]),
  ],
}
```

- `vo_files`: her sahne için tek WAV (voice-02).
- `plates_bgr`: ön işlenmiş görseller (teal-amber renk + parçacık efektleri `apply_teal_orange_cinematic` / `add_bioluminescent_particles`).
- Süre: motor `target_min_dur`/`target_max_dur` ile 51.8–56.5 sn aralığına kalibre ediyor (kural: 50–58 sn).

## Bilinen iki uyumsuzluk (kurulumda düzeltilecek)
1. **FPS**: `render_video_master` içinde `FPS = 30` sabit; kural 60 fps istiyor → 60'a çekilecek (render süresi ~2 katı).
2. **Yollar**: `FONT_BLACK_PATH`, `FONT_BOLD_PATH`, `EMOJI_FONT_PATH`, `BGM_PATH` modül sabitleri — orkestratör bunları `motor/assets/` altına yönlendirecek (motor kodu değiştirilmeden, sabit atamasıyla).

## Kullanıcı kararları — 3 Kasım 2026

| Konu | Karar |
|---|---|
| Süre | **38–42 sn** (6 sahne × ~6,5 sn). 50–58 sn pilot kuralı geçersiz. |
| Ses | ElevenLabs **Voice Library**'den seçilecek ses. `voice-02` oturum sesiydi, taşınabilir kimliği yok → `voice_id` verilene kadar üretim durur. |
| Görseller | **Pixabay** fotoğraf + teal-amber sinematik düzenleme. Ücretli/AI servis yok (Pollinations'ta logo var, kullanılmıyor). |
| Akış | **Her video elle onaylı.** Render → `motor/cikti/onay_bekleyen/` → kullanıcı izler → `--onay-verildi` ile Drive + tablo. |
| FPS | 60 (`render_engine.FPS_HEDEF`) |
| Fon müziği | `bgm_composer.py` ile üretiliyor → dış lisans bağımlılığı yok. |
| Varlıklar | Fontlar + müzik repoya commit edilmez; `motor/varlik_hazirla.py` indirir/üretir (`.gitignore`). |

**Eksik tek şey:** `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` (repo secrets) → `motor/ayarlar.json` içindeki `ses.voice_id`.
