# HANDOVER — Bilgi Dozu Otomasyonu
_Tarih: 28.10.2026 · Yazan: bir önceki agent · Amaç: yeni sunucudaki agent hiçbir işlem yapmadan, sadece okuyarak projenin tam halini anlasın._

---

## 1) Proje ne?

- **Kanal:** "Bilgi Dozu" — youtube.com/@bilgidozuofficial · Türkçe bilim/merak Shorts kanalı (boyuna nadir uzun video).
- **Amaç:** Günde 3 otomatik yayın; içerik → stok → yayın → bildirim → analiz döngüsü insansız çalışsın.
- **Sınır:** Video ÜRETİMİ dışarıda (kullanıcı kendi üretiyor). Agent yalnızca **yazılım + GitHub + veri + fikir** tarafı.

## 2) Sistem ne yapıyor? (akış)

1. **Stok:** mp4 + kapak dosyaları Drive "KartaL Stok" klasöründe.
2. **Tablo (tek kaynak):** `bilgidozu_yukleme_tablosu.xlsx` — video başına 1 satır: Durum · Dosya Adı · Başlık · Açıklama · Hashtag · Etiket · Sabit Yorum · Konu/Kategori · Kaynak · YouTube Link · Yüklenme Zamanı · Görüntülenme.
3. **Slot'lar (10:05 / 19:00 / 20:30 TR):** GitHub Actions kalkar → havuzdan **rastgele** 1 video seçer (tekrar yasağı, floor 51) → manifestte varsa SHA256 doğrular → YouTube API ile public yükleme → tabloya link + zaman yazar → repo master'ı Drive'a senkronlar → Telegram kartı (butonlar: Videoyu İzle · Yorumu Sabitle · Gönderi Metnini Kopyala · İlgili Video önerisi · Topluluk sekmesini Aç).
4. **İlgili video (zincir):** aynı konu (kategori, lower'da birebir) içinde en son YAYINLANAN; yoksa genel en son yayın.
5. **Slot Watchdog:** slotun run'ı 75 dk içinde başlamazsa Telegram "🚨 SLOT ATEŞLENMEDİ" alarmı (harici servis yok, aynı repoda 2. workflow).
6. **Görüntülenme Raporu:** her gün 09:00 TR, **sıfır YouTube kotası** (yt-dlp scraping) → tablonun Görüntülenme sütununu günceller + Telegram özet (toplam, günlük artış, top 3).

## 3) Kritik konumlar ve ID'ler

| Ne | Nerede |
|---|---|
| Repo (tek kaynak) | `github.com/benngokhan/yt_auto_uploader` → lokal `/home/user/yt_auto_uploader` |
| Workflows | `.github/workflows/`: `youtube-drive-uploader.yml` (ana) · `slot-watchdog.yml` · `goruntulenme-raporu.yml` |
| Ana kod | `uploader.py` (motor) · `sheets_metadata.py` (tablo/seçim/floor) · `stats_views.py` (view raporu) |
| CANLI tablo (Drive) | `1vVff6kevp_BKMjF4zmQkbEMxgzaiYo2f` |
| Stok klasörü (Drive) | `1w8tz_lv7iMFsRRCaTKUSY_ri0F107rz_` (KartaL Stok) |
| SHA256 manifest | `approved_new_series_manifest.json` (repo kökü) |
| Tekrar-yasağı logu | `uploaded.txt` (repo kökü) |
| Kurtarma scripti | `/home/user/restore_repo.sh` |

**Push formülü:** `git push "https://<PAT>@github.com/benngokhan/yt_auto_uploader.git" main`
`.git/config` **HER ZAMAN token'siz** kalır (bare URL); token yalnız komut satırında geçer. PAT `restore_repo.sh` içinde durur.

## 4) Mevcut durum (bu dokümanın tarihi itibarıyla)

- **Havuz: 51-111 = 63 hazır Shorts** (47/49/50 CEO kararıyla 29.10 arşive çekildi).
- **41-50:** `ESKİ_STOK_ASKIDA` — kanala hiç yayımlanmadıkları kanal taramasıyla kanıtlandı; 48 yayında (`q6YFVt6JV4c`).
- **17/18/20/21:** kanaldan SİLİNİLMİŞ → tablodaki durum `SİLİNDİ`.
- **Yayınlar:** tabloda ~35 linkli satır; son dizi 131-135 (135 = `LGXmOwTtGOw`, kalıcı, silinmez/unlist edilmez).
- **Uzun video:** yalnız 101+ (`MIN_LONG_NUMBER=101`).
- Slot'lar cron: `07:05 / 16:00 / 17:30 UTC`.

## 5) KİLİT kuralları (asla kırılmaz — kullanıcıdan gelen kalıcı emirler)

1. **Tek kaynak = repo master.** Yeni içerik ÖNCE repo'ya push; Drive'a bot append-only yazar (yalnız boş hücreyi doldurur).
2. **Seçim rastgele + tekrar yasağı.** Floor: shorts 51+, uzun 101+.
3. Çöpten dosya ÇEKİLMEZ; çöp taşıma yok; boşluk doldurma = canlı videoların yeniden adlandırılmasıyla.
4. Prosedürel render YASAK · başlıklarda **tek emoji** · TTS tek ses (`voice-00`) · müzik ≥ −28 dB · UYARILAR sayfası: `🩺` formatı, `>` ön eki YASAK.
5. Yayınlanmış 131-135'e dokunulmaz.
6. **Onay sorulmaz** (otonomi verilmiş), **israr edilmez**, cevaplar **kısa + düz Türkçe**.
7. Shorts kapağı API'de yok (platform kısıtlaması — çağrı boşa kota olur) → **yeniden ekleme**.
8. Topluluk post API'si yok → maksimum otomasyon = 1-tık gönderi metni + buton.
9. BANT tetikleme yetkisi = YALNIZCA CEO.

## 6) Bilinen sorunlar ve mitigasyonları (panik yapmadan önce oku)

- **Workspace snapshot `.git` + `.github` + `frontend/css|js` atar** (turn boundary'lerde 4 kez gözlemlendi). Panik yok: `bash /home/user/restore_repo.sh` (tek komut, ~1 sn). Remote = source of truth; repo'da uncommitted iş YAPMA (yazdığın her şeyi hemen commit+push et).
- **Lokal tablo Drive'dan geç kalabilir** (135 olayı) → sonraki senkron kendiliğinden düzeltir; Drive'a elle müdahale etme.
- **GitHub cron 30-50 dk gecikme normaldir.** 75 dk üstü = watchdog alarm verir; alarm gelmeden "kırıldı" deme.
- **YouTube kotası:** 10.000/gün, 10:00 TR'de sıfırlanır; `quotaExceeded` → video kuyrukta korunur, sonraki slot dener (otomatik).
- **yt-dlp scraping** — YouTube ileride engelleyebilir; yedek yol = resmî YouTube Analytics API.
- 2 "API yok" deliği (Shorts kapağı, topluluk postu) PLATFORM yanlı; tarayıcı otomasyonu kırılgan — kullanıcının açık kararı olmadan yapma.

## 7) Sıradaki agent'ın görevi ve yapabilecekleri

**Görev (öncekiyle aynı):** yazılım + GitHub tek sorumlu + fikir danışmanı. Video üretmez.

**İlk okuması gerekenler (işlem gerektirmez):** bu dosya → `URETIM_SABLONU.md` (üretim + rapor şablonu, tek sohbet kuralı) → `/home/user/google_drive/BANT_DURUM.md` (bekleyen işler listesi dosyanın sonunda) → Drive tablosunun UYARILAR sekmesi.

**Yapabilecekleri:**
- 29.10 slotlarını izle (yeni sistemlerin ilk günü): 10:05/19:00/20:30 yayınlandı mı? 09:00 view raporu geldi mi? Watchdog alarmı geldi mi?
- Yeni stok ekle: mp4 (+kapak) KartaL Stok'a → tabloya satır (Durum=BEKLEMEDE, başlık, açıklama, kaynak) → manifeste sha256 → commit+push. Bot otomatik çeker.
- "Neden?" sorularını KANITLA cevapla (workflow logu, kanal taraması, kod).
- Kullanıcı isterse özellik ekle (retention analizi, trend kaynaklı konu seçimi vb.) — karar kullanıcının.

**Yapamayacakları:** KİLİT kurallarını kırmak · slot saatlerini kullanıcı kararı olmadan değiştirmek · Drive tablosuna elle yazmak · onay sormayı alışkanlık haline getirmek.

## 8) Kısa sözlük

| Terim | Anlam |
|---|---|
| Floor | Havuza girebilecek en küçük video numarası (51) |
| Havuz | Durum=BEKLEMEDE + başlık dolu + link yok + numara ≥ floor olan satırlar |
| ESKİ_STOK_ASKIDA | Arşiv durumu — asla seçilmez |
| Telafi | 10:05 slotu: önceki günün eksik akşam slotlarını telafi eder; önceki gün tamamsa sabah slotu atlanır |
| KartaL Stok | Drive'daki stok klasörü |
| BANT | Kullanıcının üretim bandı dokümanı — tetik yetkisi yalnız CEO'da |
| KİLİT | Bu dokümanın 5. bölümündeki kalıcı kurallar |
