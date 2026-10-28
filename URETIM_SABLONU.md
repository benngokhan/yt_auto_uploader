# ÜRETİM ŞABLONU v1.0 — 28.10.2026
_Kullanıcı talebiyle oluşturuldu ("şablonu adam akıllı yap, üretim tek sohbette devam etsin")._
_Sistem nasıl çalışıyorsa öyle yazıldı. Çelişki: KİLİT KURALLARI > bu dosya > her şey._

---

## 0. TEK SOHBET KURALI

- **Üretim + yayın koordinasyonu = CEO sohbeti (bu sohbet).** "Üret", "yayın kontrolü", "stok ekle" komutları burada karşılanır.
- Üretim bandları (BANT 1–5) **toplu içerik üretimi** içindir; yayın saati, tablo satırı, stok, zincir, yorum, gönderi metni = bu sohbet.
- Her üretim turu başı: agent önce **HANDOVER.md → bu dosya** → Drive tablosu UYARILAR sekmesini okur. Soru sormadan çalışır.

## 1. İÇERİK ŞABLONU (Shorts)

1. **Kanca (1. cümle):** TEK kısa soru, en fazla ~6 kelime. Uzun giriş YASAK.
2. **Gövde:** 2–3 doğrulanabilir gerçek (hype=0). Kaynak: NASA / NIH / dergi adı.
3. **Kapanış:** etkileşim sorusu (sabit yorumun sorusuyla aynı).
4. **Başlık:** vurucu soru/iddia + **tek emoji** + `#bilgidozu #shorts` — maks 100 karakter.
5. **Açıklama:** 1–3 satır, gerçek kaynaklar.
6. **Sabit yorum:** kapanıştaki etkileşim sorusu (yayında otomatik atılır + sabitlenir).

### Konu seçimi
- Tekrar YASAK: `konular.md` / `uploaded.txt` ile karşılaştır.
- Kanal analizi öncelikli (kanal verisi trendi belirler), RASTGELE konu seçimi YASAK.

## 2. GÖRSEL + SES ŞABLONU (KİLİT — KİLİT v1'e bak)

- Görsel: `render_video` (SHA-256 kilitli) · referans `video_41.mp4` · 1080×1920 · H.264+AAC +faststart.
- Ses: **voice-00** (merkezde üretilir) · −14 LUFS · TP ≤ −1.5 · 44.1 kHz · harici TTS YASAK.
- Prosedürel render YASAK. Sapma = FAIL (bant_qc kapısı).

## 3. ÜRETİM HATTI (SOP)

```
konu seç → script → voice-00 sesi → render (SHA şablon) → QC → stok → slot → yayın → rapor
```

1. **QC (yayın öncesi zorunlu):** gerçek dosyaya band_qc (sha'ya değil DOSYAYA bak) + başlık/altyazı yazım kontrolü + 1. kare & orta kare binme kontrolü.
2. **Stok:** mp4 → Drive "KartaL Stok" → tabloya satır (Durum=BEKLEMEDE · Başlık · Açıklama · Sabit Yorum · Konu · Kaynak) → manifeste sha256 → **commit+push** (repo = tek kaynak; bot kendisi çeker).
3. **Yayın:** bot slot saatlerinde (10:05 / 19:00 / 20:30 TR) seçer + yükler + tabloyu doldurur. Ritim değişikliği = yalnız kullanıcı kararı.
4. **Yayın sonrası:** zincir geri-bağlantı (aynı kategorideki son yayın) + sabit yorum otomatik; link + view haftalık tabloya.

## 4. YAYIN RAPORU ŞABLONU (standart format)

Her yayından sonra CEO sohbetine ATILAN rapor birebir bu formatta:

```
🟢 BİLGİ DOZU · YENİ VİDEO YAYINDA!

━━━━━━━━━━━━━━━━━━━━

🎬 <BAŞLIK + EMOJİ>

📂 video_XX.mp4 · Shorts 📱

📦 Kalan Stok: X Shorts · Y Uzun (~Z Gün)

🔗 Zincir Geri-Bağlantı (video_YY.mp4): Açıklama + Yorum otomatik bağlandı ✅

✅ SABİT YORUM (Otomatik Atıldı · Sabitle):

<pinned comment metni>

📢 YOUTUBE GÖNDERİLER METNİ (1 Kez Dokun Tamamı Kopyalanır):

🔥 <başlık + emoji>

💬 <sabit yorum>

👇 Hemen izle ve fikrini yaz:

<https link>
```

Boş alan yoksa satır "— yok —" ile dolu kalır (sıralama bozulmaz).

## 5. YASAKLAR (kısa liste — KİLİT v1 + HANDOVER §5 için)

- Prosedürel render YASAK · başlıkta tek emoji · TTS tek ses (voice-00) · müzik ≥ −28 dB
- Rastgele konu SEÇİMİ + eski konu TEKRARI YASAK
- Bot kodu / slot saati / tabloya elle yazım / çöpten dosya çekme YASAK
- 131–135 yayınlara dokunulmaz · onay sorma + ısrar YASAK · cevap kısa + düz Türkçe

## 6. SÜRÜM

- **v1.0 — 28.10.2026:** Kullanıcı talebiyle (tek sohbet + sağlam şablon). Değişiklik = yalnız kullanıcı kararı, yeni sürüm no + bu tabloya kayıt.
