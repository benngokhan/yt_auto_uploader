# MOTOR SORULARI — Bilgi Dozu üretim hattı

**Kim yazdı:** Arena ajanı (Gökhan'ın talebiyle) · **Tarih:** 3 Kasım 2026
**Kim okuyacak:** CEO klasörünü okuyan acente
**Amaç:** Kanalın kendi şablonuyla video üreten hattı kurmak. Aşağıdaki sorular yanıtlanınca
hat GitHub Actions üzerinde uçtan uca kurulup ilk test videosu üretilecek.

---

## 0. Nereden geldik (durum)

- `/home/user/repo_live` (GitHub: `benngokhan/yt_auto_uploader`) üzerinde çalışılıyor.
- Bu klasördeki `01_KOD` kaynakları repoya **`motor/`** altına alındı:
  `render_engine.py`, `karaoke_timing.py`, `audio_balance.py`, `dinamik_baslik.py`,
  `bgm_composer.py`, `visual_style_cinematic.py`, `build_shorts_video.py`.
- Bu kod **tarihsel referans**: `FONT_*`, `EMOJI_FONT_PATH`, `BGM_PATH` ve
  `build_shorts_video.py` içindeki `scene_0X_*.png` / `vo_clean/scene_0X.wav` yolları
  eski çalışma alanına (`/home/user/...`) sabit. Uyarlanmadan çalışmıyor.
- Yedek hat olarak MoneyPrinterTurbo denendi (stok görüntü + kendi altyazısı).
  **Sonuç: şablon uyuşmuyor** → kullanıcı kararıyla **bırakıldı**, kanalın kendi motoru kurulacak.
- Kurulum planı: repo kökü `MOTOR_KURULUM.md`.

## 1. Kesinleşmiş kurallar (bu klasörden okundu, teyit yeterli)

- Shorts: 9:16, 1080×1920, **50–58 sn**, **60 fps**.
- Üst başlık: 2 satır; 1. satır beyaz, 2. satır tamamen sarı `#FFD600`, emoji var;
  anlatımın anlamlı bölümlerinde değişir (4–7 başlık), 0.25 sn yumuşak geçiş.
- Altyazı: 2 satır, o an seslendirilen kelime sarı, diğerleri beyaz; gerçek sesle hizalı.
- Rozet/bar: lime `#DCFF2E`; wordmark "BİLGİ DOZU"; alt kaynak satırı korunur.
- Ses: **voice-02** (doğal tempolu kadın). **Farklı sese sessizce geçiş yasak.**
- Müzik: konuşurken ~2 LU kısılır, sonda 3 sn fade-out.
- Görseller: AI, sinematik, teal gölge + amber vurgu; yazı/filigran/stok görüntü yok.
- Kapanış: "Sıradaki videoda … bakacağız" + küçük animasyonlu **TAKİP ET** butonu.
- Kapak: kullanıcı yaptırır; bu hat kapak basmaz.

---

## 2. SORULAR (her biri kısa cevapla geçilebilir)

### S1 — voice-02 kimliği (en kritik)
1.1 Erişim nasıl sağlanıyor: ElevenLabs **voice ID** mi, klonlanmış ses mi, başka servis mi?
1.2 Tam kimlik bilgisi (voice_id + model_id + varsa `stability / similarity_boost / style / speed`).
1.3 `03_SES_REFERANSI/voice_02_karga_reference.wav` sadece dinleme örneği mi, yoksa
    **klonlama referansı** olarak da kullanılabilir mi?
1.4 Ses bulunamazsa davranış: hat **durmalı** mı (mevcut kural), yoksa başka ses onaylı mı?

### S2 — Sahne görselleri
2.1 Görseller hangi yolla üretiliyor: (a) AI görsel servisi, (b) hazır arşiv/Drive klasörü,
    (c) kullanıcı elle yüklüyor?
2.2 AI ise: hangi servis/anahtar (Gemini image, başka), model adı, görsel başına maliyet kabul mü?
2.3 Her video için kaç görsel? Pilot 6 sahne kullanmış — bu **sabit mi**, konuya göre değişir mi?
2.4 `04_GORSEL_REFERANSI`ndaki 4 örnek: bunlar **stil referansı** mı, yoksa doğrudan
    kullanılabilir arka planlar mı?
2.5 Sahne geçişinde Ken Burns (yavaş zoom/kaydırma) kuralı sabit mi?

### S3 — Senaryo ve sahne şeması
3.1 6 sahnenin her biri için şu üçlü kim üretiyor: **ses metni**, **üst başlık (satır1/satır2+emoji)**,
    **altyazı grupları**? Mevcut bir LLM prompt'u var mı, varsa nerede?
3.2 `master_spec.json` şeması (ya da pilot `build_shorts_video.py` içindeki `scenes_meta` +
    `scene_configs` alanlarının tam listesi) — bunu **üreteceğimiz** dosyanın şablonu olarak kullanacağız.
3.3 Kanca kuralı: ilk cümle tek soru ve ≤6 kelime — hat bunu **otomatik reddetmeli** mi?

### S4 — Müzik
4.1 `ambient_science_bgm.wav` nerede duruyor, lisansı ne?
4.2 Konuya göre fon müziği `bgm_composer.py` ile mi üretilecek, yoksa sabit havuz mu?
4.3 Müzik yoksa video müziksiz mi yayınlanır (hata mı, devam mı)?

### S5 — Teslim ve yayın
5.1 Üretilen mp4: Drive **Kısa Video** klasörü + tabloya satır → mevcut yükleyici slotta yayınlar.
    Bu akış onaylı mı?
5.2 Dosya adlandırma: `video_<N>.mp4` (N = kuyruktaki en büyük +1) doğru mu?
5.3 Tabloya yazılacak alanlar: Başlık / Açıklama / Hashtag / Etiketler / Sabit yorum / Kategori /
    Kaynak — hangi alan otomatik, hangisi elle?
5.4 Üretim **günde kaç** video olsun, saatleri ne? (Şu an yayın slotları TR 12:30 ve 19:30.)

### S6 — Teknik sınırlar
6.1 Kelime hizalaması için **faster-whisper** kullanılıyor. Actions CPU'da model boyutu
    (`small` / `medium`) tercihi ne? Hizalama hatası → üretim durmalı mı?
6.2 60 fps 1080×1920 render, Actions'ta ~8–15 dk sürüyor (tahmin). Ücretsiz dakika bütçesi uygun mu?
6.3 Video başına toplam süre hedefi var mı (ör. 20 dk altı)?

### S7 — Onay ve geri dönüş
7.1 Bu hat **otomatik** mi çalışsın (günde X video, onaysız), yoksa her video **elle onay** mı beklesin?
7.2 Hatalı üretimde davranış: yükleme durur + Telegram uyarısı — doğru mu?
7.3 Bu hattın ürettiği videolar mevcut `video_<N>` sırasına **karışacak** mı, ayrı seri mi olacak?

---

## 3. Cevap formatı (acente için)

Aşağıdaki bloğu doldurup bu dosyanın sonuna eklemek ya da ayrı bir MD açmak yeterli:

```yaml
voice:
  saglayici: ""          # elevenlabs | openai | diger
  voice_id: ""
  model_id: ""
  ayarlar: {stability: , similarity_boost: , style: , speed: }
  referans_wav_klonlama: ""   # evet | hayir
  ses_yoksa: ""               # dur | devam

gorsel:
  kaynak: ""             # ai | arsiv | elle
  servis: ""             # gemini-image | diger
  anahtar_var: ""        # evet | hayir
  sahne_sayisi: ""       # 6 | degisken
  referanslar: ""        # stil | dogrudan-kullan

senaryo:
  llm_prompt_var: ""     # evet | hayir
  master_spec_sablonu: ""# evet | hayir (varsa dosya adi)
  kanca_otomatik_red: "" # evet | hayir

muzik:
  kaynak: ""
  lisans: ""
  yoksa: ""              # dur | muziksiz-devam

teslim:
  akis_onay: ""          # evet | hayir
  gunluk_adet: ""
  saatler: ""

teknik:
  whisper_model: ""      # small | medium | large
  hizalama_hatasi: ""    # dur | devam
  dakika_butcesi_uygun: ""

onay:
  otomatik: ""           # evet | hayir
  seri: ""               # ayni-seri | ayri-seri
```
