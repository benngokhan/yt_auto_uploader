# Boston v1 / 206.1 — onaylı şablon ve kapak aktarımı

## Kapsam ve aktiflik
Bu ekleme 206’da onaylanan bağımsız şablonu motor paketine sürümlü, opt-in bir varlık-aktarım girişi olarak ekler. **Mevcut panel/workflow varsayılanı değiştirilmez.** Normal `--konu` hattı hâlâ eski hattır. Bu değişiklik tek başına panelin yeni şablonla otomatik üretime geçtiği anlamına gelmez.

Sebep: güncel ana dalın planı 7 sahne/kısa v2 sözleşmesine bağlı; 206’nın onaylı düzeni 8 ayrı görsel, 53sn, kapanışta tek tam CTA içeriyor. Bu iki sözleşme sessizce birbirine çevrilmez. Yeni yol açıkça seçilir; uyumsuz pakette eski şablona veya başka sese geri dönülmez.

## Sabitler
1080×1920/30fps/53sn; 8 ayrı dosya ve farklı çözümlenmiş piksel hashleri; Poppins altyazı, sade üst logo, beyaz/ölçülü altın vurgu; CTA yalnız sonda. 250×70px tek ince kenarlı takip butonu, 44px yazı, küçük mouse ve tek basış. Müzik/zil yerel sentez; anlatım örneklerinin konumu, hızı ve genliği korunur.

Kapak zorunludur: iki satır Anton, ortak punto ve taban hizası, 2px kontur, ölçülü genişlik dengesi. Ç/Ğ gibi uzantılar ölçülür; gerekirse iki satırın ortak baseline aralığı büyür. Başlık veya alt yazı sığmazsa kırpılmaz/uydurulmaz; işlem durur. Orijinal 206 kapağı uygun girdilerle aynı JPEG piksellerini üretir.

`motor/boston206_lock.json` kod ve üç fontun SHA256 değerlerini sabitler. Dosya değişirse kilit doğrulanmadan şablon çalışmaz. Bu bir imza/güvenli tedarik zinciri kanıtı değildir; yetkili kod değişikliği hem dosyayı hem manifesti değiştirebilir. Yeni sürüm için gözden geçirme ve regresyon testi gerekir.

## Varlık paketi
Klasör içeriği:
- `plan.json`: `template_version=boston-v1-206.1`, `timeline_edges` (0'dan53'e9artan değer), `script_lines`, `voice_id=voice-00`, `voice_speed_factor=1`, `motor_integration=false` (kaynak bağımsız taslağı işareti), okunmuş `source.url/label/reviewed`, `design.cover_title` (2satır), `design.cover_category/cover_subtitle`.
- `alignment.json`: ham ses SHA256, gerçek süre, ses-temelli kelime start/end değerleri, groups, words, ASRbenzerliği≥0.95. Bu ölçüm doğruluk garantisi değil bir kalite kapısıdır.
- `asset_review.json`:8satır,scene1..8,file,sha256,pixel_sha256,approved_for_illustrative_draft. İnsan incelemesi beyanıdır; hashler anlamsal doğruluğu ispatlamaz.
- `assets/narration.wav`:mono24kHzPCM16,40–53sn.
- `assets/scene01.png`..`scene08.png` (jpg/jpeg de kabul edilir); symlink ve path traversal kabul edilmez.

Son satır tam olarak: `Merakını besle, Bilgi Dozu’nu takip et!`

Ses kimliği yalnız paket sahibinin beyanıdır. `voice-00` Arenaoturumetiketidir; bu modül ses sentezlemez, kalıcı dış API ses erişimi sağlamaz ve başka sese geçmez. Eksik varlıkta yeni inference çağrısı yapmaz.

## Kullanım
Önce denetim (varsayılan; MP4encode yok):
```
python motor/uret.py --boston-bundle /paket --boston-output /yeni-kontrol
```
Yerel örnek kareler (ses/görsel üretimi ve MP4encode yok):
```
python motor/uret.py --boston-bundle /paket --boston-output /yeni-onizleme --boston-mode stills
```
Yeni finalencode yalnız ayrıca yetkilendirilmiş iş için:
```
python motor/uret.py --boston-bundle /paket --boston-output /yeni-final --boston-mode render
```
Çıktı klasörü yeni olmalıdır; kaynak paket değiştirilmez. Kaynak çıktı klasörünün içine kopyalanmaz. Üretim/yayın bayraklarıyla birleştirilemez. Çıktı video.mp4/kapak.jpg ve kanıt dosyalarıdır; numara, Drive, Excel, Telegram veya YouTubekuyruğuna yazım yapılmaz.

## Doğrulama ve sınırlar
094yerelçalışma:25yeni+34mevcut=59testPASS. Mevcut206varlıklarıyla yenidenTTS/görsel/MP4üretmedenyapılanregresyonda5ayrızamandakiçerçeveler206kaynakeditörünepikselpikseleaynı;kapakJPEGpikselleriaynı;sesmiksiSHA256aynı.
Bu, yeni bir tamMP4encode/decode veya canlıpaneldenuçtanuçaüretimtestideğildir. Varsayılanüretimaktivasyonu,seskalıcıerişimi,güncelkonuanalizi,Telegramarızailetisi,yedekhattıvekuyrukentegrasyonubudeğişikliğinkapsamındadeğildir.

## Geri dönüş
Eklenen Bostonmodüllerinikullanan`--boston-bundle`girişiniseçmeyerekmevcutnormalhatkorunur. Revert işlemi yalnız bu entegrasyon commit’ine uygulanmalı; başka değişiklikler ezilmemeli. Bu işlem geçmiş bütçe veya üretim günlüklerini sıfırlamaz.
