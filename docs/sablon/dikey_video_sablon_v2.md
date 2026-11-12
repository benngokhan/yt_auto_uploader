# DİKEY BİLGİ VİDEOSU — TASARIM ŞABLONU VE ÜRETİM KILAVUZU (v2)

**YouTube Kanal:** https://youtube.com/@bilgidozuofficial
**Tekrar yayın:** YouTube tüm Shorts video başlıkları ve konuları taranacak.
**Konu seçimi:** Kanal analizi ve milyon izlenme potansiyeline sahip konular.

> **v2 notu:** Bu sürümde ölçüler, fontlar ve renkler gerçek videodan ölçülen değerlerle güncellendi. Görseller `gorseller/` klasöründedir; md dosyasıyla aynı klasörde tutulmalıdır.

---

## 1. TASARIMIN GENEL YAPISI

Görsel kimlik şu unsurlardan oluşur:

- Koyu siyah arka plan.
- Beyaz, yüksek kontrastlı tipografi (font ailesi: **Poppins**).
- İki vurgu rengi: **marka limonu** (çubuk, etiket, logo, buton) ve **vurgu sarısı** (başlık 2. satır, vurgulu kelimeler).
- Üstte ince ilerleme çubuğu.
- Kısa kategori etiketi.
- Büyük ve dikkat çekici ana başlık.
- Ortada konuya uygun görsel veya animasyon.
- Konuşmayla senkronize altyazılar.
- Alt bölümde kaynak bilgisi ve kanal imzası.
- Erkek Türkçe seslendirme.
- Konuşmaya göre otomatik kısılan jenerik müzik.
- Sade, küçük ve animasyonlu takip butonu.

Temel prensip: Video profesyonel, modern, temiz ve mobil ekranda kolay okunabilir olmalıdır. Ekran gereksiz metinlerle veya büyük animasyonlarla doldurulmamalıdır.

### Bir bakışta yerleşim

```
┌──────────────────────────────────┐ y0
│  ÜST ARAYÜZ — kullanma (180 px)  │
├──────────────────────────────────┤ y180
│ ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  │ y200  İlerleme çubuğu
│ ( BİLGİ DOZU )                   │ y232  Kategori etiketi
│                                  │
│      (?) BAŞLIK SATIR 1  (beyaz) │ y329  Ana başlık
│          BAŞLIK SATIR 2  (sarı)  │
│                                  │
│ ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐  │ y470
│          ANA GÖRSEL ALANI        │
│ └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘  │ y1200
│                                  │
│        altyazı satır 1           │ y1230 Altyazı
│        altyazı satır 2           │
│                                  │
│     Görseller yapay zekâ ile…    │ y1380 Kaynak / alt bilgi
│     Kaynak: …                    │
│          BİLGİ DOZU              │ y1487
├──────────────────────────────────┤ y1500
│  ALT ARAYÜZ — kullanma (420 px)  │
└──────────────────────────────────┘ y1920
        sağ 150 px de boş bırakılır (x > 930)
```

<img src="gorseller/01_yerlesim_haritasi.png" width="340" alt="Ölçülü yerleşim haritası">
<img src="gorseller/02_sablon_onizleme.png" width="340" alt="Şablon önizleme">

*Solda: ölçülü yerleşim haritası (kırmızı alanlar kullanılmaz). Sağda: yer tutucu yazılı örnek şablon.*

---

## 2. TUVAL VE GÜVENLİ ALANLAR

| Parametre | Değer |
|---|---|
| Tuval | 1080 × 1920 px |
| En-boy oranı | 9:16 |
| Üst güvenli olmayan alan | 180 px |
| Alt güvenli olmayan alan | 420 px |
| Sağ kenar rezervi | 150 px (içerik x ≤ 930) |
| Sol iç boşluk | 72 px |
| Ana içerik alanı | y = 180–1500 px |

Önemli metinler platform arayüzleriyle çakışmamalıdır. Kaynaklar farklı değerler verdiği için (alt alan 300–575 px arası) muhafazakâr değerler seçilmiştir. Yayından önce Shorts, Reels ve TikTok arayüzlerinde son kontrol yapılmalıdır.

### v1 (orijinal video) ile v2 farkı

v1, orijinal videonun birebir ölçüsüdür. Orada çubuk, etiket ve başlık üst arayüz bölgesine, alt bilgi ise alt arayüz bölgesine denk geliyordu. v2'de tüm öğeler güvenli alana alındı.

<img src="gorseller/03_v1_v2_karsilastirma.png" width="640" alt="v1 ve v2 karşılaştırma">

| Öğe | v1 (y) | v2 (y) | Değişim |
|---|---|---|---|
| İlerleme çubuğu | 58 | 200 | 142 px aşağı |
| Kategori etiketi | 90 | 232 | 142 px aşağı |
| Ana başlık | 187 | 329 | 142 px aşağı |
| Altyazı | 1354 | 1230 | 124 px yukarı |
| Kaynak + logo | 1750 | 1380 | 370 px yukarı |

---

## 3. KATMANLAR VE YERLEŞİM ÖLÇÜLERİ

Konumlar sol üst köşeden (x, y) verilir; boyut genişlik × yükseklik şeklindedir.

<img src="gorseller/04_ust_alan_olcu.png" width="640" alt="Üst alan ölçüleri">

### 3.1. Üst ilerleme çubuğu

- Konum: x = 72, y = 200.
- Boyut: **936 × 6 px** (kalınlık 6 px).
- Arka iz: koyu gri `#393939`.
- İlerleyen bölüm: marka limonu `#E3F424`.
- Uçlar yuvarlatılmış.
- Video boyunca soldan sağa doğrusal ilerler; başlangıçta %0, bitişte %100.

### 3.2. Kategori etiketi

- Konum: x = 72, y = 232.
- Boyut: **204 × 44 px**, tam yuvarlak uçlu hap (köşe yarıçapı 22 px).
- Dolgu: marka limonu `#E3F424`.
- Yazı: siyah (`#0A0A0A`), **Poppins Bold, 23 px**, büyük harf.
- Örnek: BİLGİ DOZU.
- En fazla 1–3 kelime.

### 3.3. Ana başlık

- Konum: x = 188, y = 329. Kutu: **705 × 117 px**, yatayda ortalı.
- Font: **Poppins Bold**, **64 px** (en düşük 58 px).
- Büyük harf, en fazla 2 satır, satır aralığı 71 px (≈ 1.1).
- Satır başına en fazla yaklaşık 20 karakter (64 px'te 705 px'e sığma sınırı).
- 1. satır: beyaz `#FFFFFF`, solunda 38 px'lik sarı soru ikonu (`#FFD91E`, içinde koyu "?"), ikon ile metin arası 16 px.
- 2. satır: vurgu sarısı `#FFD91E`.
- Başlık kısa, merak uyandırıcı ve somut olmalı.

> Uzun başlıkları küçültmek yerine yeniden yazıp kısalt.

### 3.4. Ana görsel ve animasyon

- Önerilen alan: x = 72–930, y = 470–1200.
- Gerçekçi fotoğraf, 3D görsel, bilimsel illüstrasyon, harita veya animasyon kullanılabilir.
- Her sahnede tek ana odak bulunmalı.
- Hafif zoom, paralaks veya kontrollü kamera hareketleri kullanılabilir.
- Gereksiz hızlı geçişlerden kaçınılmalı.
- Görseller anlatılan bilgiyle doğrudan ilişkili olmalı.

### 3.5. Altyazı

- Konum: x = 155, y = 1230. Kutu: **771 × 116 px**, yatayda ortalı.
- Font: **Poppins Bold**, **50 px** (48–52 arası).
- En fazla 2 satır, satır aralığı 63 px.
- Beyaz metin, vurgulu kelimeler `#FFD91E`.
- Hafif gölge: yaklaşık 3 px aşağı, 5–6 px blur, %75 siyah.
- Satır başına tercihen 24–28 karakter (50 px'te 771 px'e sığma sınırı).
- Her parça yaklaşık 1–3 saniye görünür, seslendirmeyle birebir senkron olur.

> Altyazılar uzun paragraf değil, konuşma ritmine göre kısa parçalar halinde verilmelidir.

### 3.6. Kaynak ve alt bilgi

- Konum: x = 281, y = 1380. Kutu: **518 × 108 px**, yatayda ortalı.
- Kaynak satırları: **Poppins Regular, 26 px**, `#ECECEF`, satır aralığı 35 px.
- Kanal imzası (logo): **Poppins Bold, 45 px**, "BİLGİ" beyaz, "DOZU" `#E3F424`; üst kenarı y = 1454.

İçerik sırası:

1. Gerekliyse görsel üretim açıklaması.
2. Kaynak bilgisi.
3. Kanal imzası: BİLGİ DOZU.

Örnek:

```
Görseller yapay zekâ ile canlandırılmıştır
Kaynak: MIT • The New York Times
BİLGİ DOZU
```

> Kaynaklar gerçek ve doğrulanabilir olmalıdır. Kaynak uydurulmamalıdır.

<img src="gorseller/05_altyazi_alt_bilgi_olcu.png" width="640" alt="Altyazı ve alt bilgi ölçüleri">

---

## 4. RENK PALETİ

<img src="gorseller/06_renk_paleti.png" width="520" alt="Renk paleti">

| Kullanım | HEX |
|---|---|
| Marka limonu (çubuk, etiket, "DOZU", buton) | `#E3F424` |
| Vurgu sarısı (başlık 2. satır, vurgulu kelime, ikon) | `#FFD91E` |
| Ana metin | `#FFFFFF` |
| İkincil metin (kaynak satırları) | `#ECECEF` |
| İlerleme izi | `#393939` |
| Düz arka plan | `#0E1014` |
| Kapak turkuazı (yalnız kapakta) | `#4DE2CC` |
| Kapak sarısı (yalnız kapakta) | `#FFD73B` |

Ölçü çizimlerinde kullanılan turuncu `#FFAE16`, yeşil `#7BFF78`, fuşya `#F05BEF` ve kırmızı `#F05A62` yalnızca rehber çerçevelerdir; videoda kullanılmaz.

> Videonun ana renkleri siyah, beyaz ve limon/sarıdır. Diğer renkler yalnızca gerektiğinde kullanılmalıdır.

---

## 5. TİPOGRAFİ HİYERARŞİSİ

Tüm videoda tek font ailesi kullanılır: **Poppins** (Google Fonts, ücretsiz).

| Öğe | Boyut | Ağırlık |
|---|---|---|
| Ana başlık | 64 px (en düşük 58) | Bold |
| Altyazı | 50 px (48–52) | Bold |
| Kategori etiketi | 23 px | Bold |
| Kaynak bilgisi | 26 px | Regular |
| Kanal imzası | 45 px | Bold |
| Takip butonu yazısı | 24 px (22–26) | Bold |

> Türkçe karakterler (İ, ı, ş, ğ, ü, ö, ç, â) doğru görüntülenmelidir.

---

## 6. VİDEO AKIŞI VE KURGU

1. İlk 1–2 saniyede kategori etiketi ve ana başlık görünmelidir.
2. Ana anlatım sırasında konuya uygun görseller kullanılmalıdır.
3. Altyazılar sesle senkron ilerlemelidir.
4. Önemli kelimeler sarı renkle vurgulanmalıdır.
5. Geçişler yumuşak ve profesyonel olmalıdır.
6. Kapanışta kaynak ve kanal imzası korunmalıdır.
7. Son bölümde standart takip çağrısı gösterilmelidir.

---

## 7. İÇERİK VE DOĞRULUK KURALLARI

- Bilimsel, tarihî ve sağlıkla ilgili iddiaları güvenilir kaynaklarla doğrula.
- Kaynak adını ve mümkünse yayın yılını belirt.
- Yapay zekâ görsellerini gerçek fotoğrafmış gibi sunma.
- Yanıltıcı başlıklar kullanma.
- Her sahnede tek ana bilgi ver.
- Altyazı ve seslendirme birebir uyumlu olmalı.
- Kaynak bulunamıyorsa bunu açıkça belirt.

---

## 8. SES TASARIMI VE SESLENDİRME

### 8.1. Jenerik müzik

> Videoda düşük yoğunluklu, telifsiz, profesyonel bir jenerik müzik kullanılmalıdır.

Otomatik müzik kısma (audio ducking):

- Konuşma başladığında müzik otomatik kısılmalı.
- Konuşma sırasında müzik yaklaşık 12–18 dB azaltılmalı.
- Konuşma bittiğinde müzik yumuşak şekilde yükselmeli.
- Attack: 150–300 ms.
- Release: 600–1000 ms.
- Müzik hiçbir zaman seslendirmeyi bastırmamalı.
- Cümle aralarında ani ses seviyesi değişiklikleri olmamalı.

### 8.2. Erkek seslendirme

Tüm videolarda erkek Türkçe seslendirme kullanılmalıdır.

Ses karakteri: doğal, güven veren, sıcak, akıcı, enerjik ancak abartısız, net ve anlaşılır. Aynı video boyunca ses karakteri değişmemelidir.

### 8.3. Seslendirme onay süreci

Bu süreç zorunludur:

1. Önce tam seslendirme metnini oluştur.
2. Metni kullanıcıya sun.
3. Mümkünse 10–20 saniyelik erkek seslendirme örneği hazırla.
4. Kullanıcıya ses örneğini dinlet.
5. Açık onay al.
6. Onaydan sonra nihai seslendirmeyi üret.
7. Nihai seslendirmeyi müzikle miksajla.

Kullanıcı onayı alınmadan nihai seslendirme tamamlanmış kabul edilmemelidir.

---

## 9. KAPANIŞ VE TAKİP BUTONU TASARIMI

### 9.1. Zorunlu kapanış cümlesi

Her videonun sonunda erkek seslendirme şu cümleyi aynen söylemelidir:

**"Daha fazla Bilgi Dozu için takip et!"**

- Doğal ve akıcı seslendirilmeli.
- "Bilgi Dozu" kelimeleri hafifçe vurgulanmalı.
- Cümle kesilmeden tamamlanmalı.

### 9.2. Küçük ve zarif TAKİP ET butonu

> Takip butonu büyük, kaba veya ekranın dikkatini tamamen üzerine çeken bir tasarıma sahip olmamalıdır.

<img src="gorseller/08_kapanis_takip_butonu.png" width="340" alt="Kapanış karesi ve takip butonu">

**Tasarım ölçüleri:**

| Özellik | Değer |
|---|---|
| Genişlik | 190–220 px (öneri: 200) |
| Yükseklik | 54–62 px (öneri: 58) |
| Köşe yuvarlaklığı | 12–16 px (öneri: 14) |
| Yazı | TAKİP ET, 22–26 px, Poppins Bold |
| Dolgu rengi | `#E3F424` |
| Yazı rengi | `#0E1014` |
| Konum (öneri) | Yatay ortalı (x = 440–640), y ≈ 1148–1206 |

> Konum önerisi ölçüm değil, tasarım önerisidir: buton, güvenli alan içinde kalacak şekilde altyazının hemen üstüne yerleştirilmiştir (altyazı y = 1230'da başlar). Kapanışta yerleşimi kendi videonda bir kez dene.

**Animasyon:**

- Kısa ve yumuşak pop-in animasyonu.
- Hafif scale efekti.
- Bir defalık küçük pulse animasyonu.
- Sürekli yanıp sönme veya aşırı büyüyüp küçülme kullanılmamalı.
- Buton ekranın önemli bölümünü kaplamamalı.

**Ses efekti:**

- Buton görünürken kısa, yumuşak bir click/pop efekti kullanılmalı.
- Ses efekti animasyonla eş zamanlı olmalı.
- Seslendirmeyi bastırmamalı.

**Görünürlük süresi:**

- Son karede 1,5–2 saniye görünür kalmalı.
- Kapanış cümlesiyle görsel olarak bağlantılı olmalı.
- Video, buton animasyonu tamamlanmadan bitmemeli.

> **Önemli:** Butonun görevi izleyiciye takip çağrısını hatırlatmaktır. Ana içerikten daha fazla dikkat çekmemelidir.

---

## 10. KAPAK TASARIMI

Kapak da aynı kimliği taşır: koyu zemin, üstte etiket ve kategori, dev başlık, küçük ayırıcı, altta açıklama cümlesi.

<img src="gorseller/07_kapak_olcu.png" width="340" alt="Kapak ölçüleri">

| # | Öğe | Konum (x, y) | Boyut | Detay |
|---|---|---|---|---|
| 1 | Etiket | 62, 78 | 303 × 60 | Turkuaz `#4DE2CC` çerçeveli hap, harf aralıklı Poppins Bold |
| 2 | Kategori (ör. FİZİK & BİLİM) | 653, 105 | 363 × 27 | Beyaz, geniş harf aralıklı |
| 3 | Başlık (3 satır) | 80, 314 | 920 × 404 | Dar ve kalın font (Anton benzeri, tahmin). Büyük harf yüksekliği 115 px, satır aralığı 131 px. Satır 1–2 beyaz, satır 3 `#FFD73B` |
| 4 | Ayırıcı | 440, 793 | 201 × 15 | Turkuaz nokta (15 px) + sarı çizgi (133 × 8) + turkuaz nokta |
| 5 | Altyazı cümlesi | 112, 1687 | 856 × 99 | Poppins Medium ~41 px, satır aralığı 58 px, beyaz, ortalı |

> Bu kapak güvenli alan kurallarına göre tasarlanmamıştır: etiket ve kategori üst 180 px'e, açıklama cümlesi alt 420 px'e denk gelir. Kapak yalnızca küçük resim olarak kullanılacaksa sorun olmaz. Videonun ilk karesi olarak kullanılacaksa öğeler güvenli alana çekilmelidir.

---

## 11. DIŞA AKTARMA AYARLARI

- Format: MP4.
- Çözünürlük: 1080 × 1920.
- En-boy oranı: 9:16.
- Kare hızı: tercihen 30 FPS.
- Video codec: H.264.
- Ses codec: AAC.
- Bitrate: 8–15 Mbps.
- Son video telefon ekranında test edilmelidir.

---

## 12. BAŞKA BİR YAPAY ZEKÂYA VERİLECEK HAZIR ÜRETİM PROMPTU

**ROLÜN:** Profesyonel video yönetmeni, senarist, motion designer ve ses tasarımcısısın.

**GÖREV:** [KONU] hakkında [HEDEF SÜRE] uzunluğunda, Türkçe, 9:16 formatında bir Bilgi Dozu videosu üret.

> Bu belgedeki bütün tasarım, ölçü, renk, tipografi, seslendirme ve kurgu kurallarına uy.

**GÖRSEL KURALLAR:**

1. Tuval 1080 × 1920 px olmalı.
2. Tüm yazılar Poppins fontuyla olmalı.
3. İlerleme çubuğu (x72, y200, 936 × 6) ve kategori etiketi (x72, y232, 204 × 44) belirtilen koordinatlarda olmalı.
4. Başlık 64 px (en düşük 58), en fazla iki satır olmalı; 1. satır beyaz, 2. satır `#FFD91E`.
5. Altyazı 50 px, en fazla iki satır, y = 1230 civarında olmalı.
6. Kaynak bilgisi 26 px, y = 1380 civarında olmalı; altında "BİLGİ DOZU" imzası bulunmalı.
7. Ana renkler siyah, beyaz, marka limonu `#E3F424` ve vurgu sarısı `#FFD91E` olmalı.
8. Görseller konuya uygun ve kaliteli olmalı.
9. Üst 180 px, alt 420 px ve sağ 150 px boş bırakılmalı.

**SES KURALLARI:**

1. Türkçe erkek seslendirme kullan.
2. Seslendirme metnini önce kullanıcıya onaya sun.
3. Mümkünse 10–20 saniyelik ses örneği hazırla.
4. Kullanıcı onayı olmadan final seslendirmeyi tamamlamış sayma.
5. Telifsiz jenerik müzik kullan.
6. Konuşma başladığında müziği otomatik olarak 12–18 dB azalt.
7. Konuşma bitince müziği yumuşakça yükselt.
8. Finalde şu cümleyi aynen kullan: "Daha fazla Bilgi Dozu için takip et!"

**TAKİP BUTONU KURALLARI:**

1. Marka limonu `#E3F424` renkte olmalı.
2. Yaklaşık 190–220 × 54–62 px boyutunda olmalı.
3. Yazı 22–26 px olmalı.
4. Güvenli alan içinde yatay ortalanmalı.
5. Küçük ve zarif pop-in animasyonu kullanılmalı.
6. Kısa click/pop ses efekti eklenmeli.
7. Aşırı büyüme, sürekli yanıp sönme ve dikkat dağıtıcı animasyonlardan kaçınılmalı.
8. Son karede 1,5–2 saniye görünür kalmalı.

**TESLİM SIRASI:**

1. Başlık ve kısa özet.
2. Zaman kodlu sahne planı.
3. Tam seslendirme metni.
4. Altyazılar.
5. Görsel ve animasyon promptları.
6. Kaynak listesi.
7. Erkek seslendirme örneği.
8. Kullanıcı onayı.
9. Nihai seslendirme ve müzik miksajı.
10. Tamamlanmış video.

> Video üretme imkânın yoksa sahne sahne üretime hazır görsel promptları, zaman kodları ve kurgu talimatları hazırla.

---

## 13. SON KONTROL LİSTESİ

**Görsel:**

- [ ] 1080 × 1920 çözünürlük.
- [ ] 9:16 format.
- [ ] Üst 180 / alt 420 / sağ 150 px boş.
- [ ] İlerleme çubuğu y200'de, 6 px kalınlıkta.
- [ ] Kategori etiketi 204 × 44 px.
- [ ] Başlık en fazla iki satır, Poppins Bold 64 px.
- [ ] Altyazılar okunabilir, en fazla iki satır.
- [ ] Kaynaklar doğrulanmış.
- [ ] Türkçe karakterler doğru.

**Ses:**

- [ ] Erkek Türkçe seslendirme.
- [ ] Seslendirme metni kullanıcı onayından geçti.
- [ ] Jenerik müzik telifsiz.
- [ ] Konuşma sırasında müzik otomatik kısılıyor.
- [ ] Konuşma bitince müzik yükseliyor.
- [ ] Seslendirme net ve anlaşılır.

**Kapanış:**

- [ ] "Daha fazla Bilgi Dozu için takip et!" cümlesi kullanıldı.
- [ ] Küçük TAKİP ET butonu eklendi.
- [ ] Buton yaklaşık 190–220 px genişliğinde.
- [ ] Animasyon sade ve zarif.
- [ ] Click/pop efekti senkronize.
- [ ] Buton son karede 1,5–2 saniye görünüyor.

---

> **SABİT ÜRETİM İLKESİ:** Konu, anlatım ve görseller değişebilir. Ancak görsel kimlik, yerleşim, tipografi, renk paleti, erkek seslendirme, otomatik müzik kısma, kullanıcı onayı ve küçük animasyonlu takip butonu bütün videolarda korunmalıdır.
