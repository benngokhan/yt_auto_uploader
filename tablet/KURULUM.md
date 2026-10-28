# 🦅 Kartal AI · Tablet Ajanı — Samsung Galaxy Tab S7 FE (Android) Kurulum Rehberi

> **Sonuç:** Telefonundan Telegram'a yazdığın komutla tablet **kendi kendine** uygulama açar, dokunur, yazar, kaydırır, video paylaşır ve YouTube Studio'da işlem yapar. Bilgisayar gerekmez.

---

## 1. Ne mümkün, ne değil? (Dürüst tablo)

| Görev | Durum | Nasıl |
|---|---|---|
| Ekranı görme, dokunma, yazma, uygulama açma | ✅ **Tamamen mümkün** | Termux + kablosuz ADB |
| Doğal dilde görev ("Instagram'ı aç, keşfete git") | ✅ Mümkün | Kartal adım adım yürütür (ekran yazıları + Gemini görüntü) |
| Instagram Reels / TikTok paylaşımı | ✅ **En sağlıklı yol bu** | Ev internetin + açık hesabın → sunucu IP engeli yok |
| YouTube Studio'da "İlgili Video" bağlama | ✅ Mümkün (API'de yok, UI'dan) | Kartal Studio'yu açar, butonu bulur, dokunur |
| Tabletin **kapalıyken** uyandırılması | ⚠️ Kısıtlı | Ekranı açık/şarjda tut (aşağıdaki ayarlarla) |
| Ekran kilidi açma | ⚠️ Kısıtlı | Parmak izi/PIN ilk açılışta gerekir, sonra açık kalır |
| iPad'de aynısı | ❌ | Apple izin vermiyor; sadece Kestirmeler |

---

## 2. Gerekli 3 uygulama (hepsi ücretsiz, Play Store'da arama)

1. **F-Droid** → `https://f-droid.org` adresinden APK indir, kur. *(Play Store'daki Termux sürümü bakımsız, kullanma.)*
2. **Termux** → F-Droid içinden kur.
3. **Termux:API** → F-Droid içinden kur. *(termux-api komutları için)*

> Tablet **Android 13** ise (S7 FE güncel sürüm) kablosuz hata ayıklama sorunsuz çalışır.

---

## 3. Kablosuz hata ayıklamayı aç (tek seferlik, 2 dakika)

1. `Ayarlar → Tablet hakkında → Yazılım bilgileri → Yapı numarası` → **7 kez dokun** → “Geliştirici oldunuz”.
2. `Ayarlar → Geliştirici seçenekleri → Kablosuz hata ayıklama` → **AÇ**.
3. Aynı ekranda **“IP adresi ve Bağlantı noktası”** yazar → örn. `192.168.1.42:41234` → **bunu bir yere not al**.
4. Wi-Fi'yi **asla değiştirme**; değişirse port değişir, aynı adımı tekrarla.
5. `Ayarlar → Geliştirici seçenekleri → Ekran açık kalsın (şarjdayken)` → **AÇ**.
6. `Ayarlar → Pil → Uygulama pil kullanımı → Termux → Kısıtlanmamış` seç. *(Bunu yapmazsan Samsung ajanı 15 dakikada öldürür.)*

---

## 4. Kurulum (Termux'ta 4 satır)

Termux'u aç ve sırayla yapıştır:

```bash
pkg update -y && pkg install -y git
git clone --depth 1 https://github.com/benngokhan/yt_auto_uploader.git ~/kartal_kaynak
bash ~/kartal_kaynak/tablet/kur.sh
```

`kur.sh` sırasıyla şunları sorar:

| Soru | Cevap |
|---|---|
| **Bot token** | Telegram → `@BotFather` → `/mybots` → botunu seç → *API Token* |
| **Gemini API key** (opsiyonel) | `https://aistudio.google.com/apikey` → ücretsiz anahtar. Boş bırakırsan da çalışır (sadece ekran yazılarıyla). |
| **IP:PORT** | 3. adımda not aldığın `192.168.1.42:41234` |

Kurulum sonunda şu çıktıyı görmelisin:
```
127.0.0.1:41234   device      <-- "device" yazması şart
✅ Kurulum bitti!
```

> `unauthorized` yazıyorsa: tablette çıkan **“USB hata ayıklamasına izin ver”** penceresinde **Her zaman izin ver → İzin ver**'e dokun, sonra `adb kill-server && adb connect IP:PORT` tekrar çalıştır.

---

## 5. ADB bağlantısı (tek komut, IP/port ezberlemek yok)

```bash
python ~/kartal_kaynak/tablet/baglan.py
```

Bu komut: tabletin IP'sini kendi bulur → kablosuz hata ayıklama portunu tarar → gerekirse **1 kez** 6 haneli eşleştirme kodunu sorar → bağlanıp hedefi `.env`'e yazar.

Başarı çıktısı: `✔ Bağlandı: 10.x.x.x:41234`

> Elle vermek istersen: `python ~/kartal_kaynak/tablet/baglan.py 10.136.3.175:41234`

## 6. Başlat

```bash
bash ~/kartal_tablet/baslat.sh
```

Ekranda `🦅 Kartal Tablet Ajanı ayakta (worker + bekçi)` yazınca, **telefonundan** botuna **`/menu`** yaz.

> **Güncelleme = kurulumu tekrar çalıştırmak.** Dosya peşinde koşmayacaksın; her yeni sürümde tek komut: `bash ~/kartal_kaynak/tablet/kur.sh` (önce `git -C ~/kartal_kaynak pull`).

> **İlk kilit:** İlk mesajı hangi Telegram hesabından atarsan ajan sadece o hesaba bağlanır. Başkası yazamaz.

### Her açılışta kendisi başlasın (isteğe bağlı)
F-Droid'den **Termux:Boot** kur → sonra Termux'ta:
```bash
mkdir -p ~/.termux/boot
echo 'bash ~/kartal_tablet/baslat.sh' > ~/.termux/boot/kartal.sh
chmod +x ~/.termux/boot/kartal.sh
```
Tablet her yeniden başladığında ajan otomatik ayağa kalkar.

---

## 7. Telefondan komutlar (kopyala-yapıştır)

### 👁 Göz
| Komut | Ne yapar |
|---|---|
| `/ekran` | Tablet ekranının fotoğrafını Telegram'a gönderir + görünen yazıları listeler |
| `/bul Paylaş` | Ekranda “Paylaş” var mı, koordinatı nerede |
| `/bul Paylaş tikla` | Bulur **ve dokunur** |
| `/uygulamalar` | Yüklü uygulamaların paket adları |

### ✋ El
| Komut | Ne yapar |
|---|---|
| `/tikla 540 900` | Koordinata dokunur |
| `/yaz merhaba dünya` | Klavyeden yazar |
| `/tus geri` · `/tus ev` · `/tus enter` · `/tus bildirim` | Tuş basar |
| `/kaydir yukari` · `asagi` · `sol` · `sag` | Kaydırır |
| `/ac instagram` · `/ac studio` · `/ac com.zhiliaoapp.musically` | Uygulama açar |

### 🧠 Beyin
| Komut | Ne yapar |
|---|---|
| `/gorev Instagram'ı aç ve keşfet akışına geç` | Ekranı okur, adım adım kendi yapar, her adımı Telegram'a yazar |
| *(doğrudan cümle yazarsan)* | Otomatik olarak `/gorev` sayılır |

### 🎙 Sesli mesaj (tablete KONUSMA — telefondan sesli mesaj at)
| Yaptığın | Ne olur |
|---|---|
| Telefondan bota sesli mesaj: **"YouTube aç"** | Gemini duyup yazıya çevirir → "🎧 Duydum: YouTube aç" → beyin tablette yapar |
| **"Mail oku"** | Gmail'i açar, gelen kutusunu görür, özetler |
| **`/mail`** (yazılı) | Aynı işi komutla |

> Neden telefondan? Telefon mikrofonu + Gemini tanıması, tabletteki ucuz tanınmadan 10 kat isabetli.
> Sesli mesaj için **Gemini anahtarı şart** (yoksa: `/api AIzaSy...`). Maks 3 dk, Türkçe konuş.

### 📺 Kanal işleri
| Komut | Ne yapar |
|---|---|
| `/paylas /sdcard/Download/video_132.mp4` | Android paylaşım menüsünü açar |
| `/paylas https://drive.google.com/.../video_132.mp4 Instagram` | Linki indirir, menüden Instagram'ı da seçer |
| `/studio MOxaXPkS0zw` | YouTube Studio'da o videoyu açar (İlgili Video için) |
| `/mail` | Gmail'i açar, gelen kutusunu okur, özetini atar |

---

## 8. Günlük akış: bot YouTube'a atar → Kartal tablete Reels/TikTok atar

1. `19:00` / `20:15` slotlarında bot YouTube'a yükler, Telegram'a kart atar.
2. Kartal tablete `/paylas <Drive linki> Instagram` yazarsın (veya ben bunu tam otomatiğe bağlarım).
3. Tablet ev internetinle Reels'i yükler → **veri merkezi IP engeli yok, hesap kilitlenme riski düşük**.
4. Aynı yöntem TikTok için: `/paylas <link> TikTok`.

> **Not:** Instagram/TikTok yüklemeyi “onayla” adımında bazen elle 1 dokunuş ister (telif, kapak seçimi vb.). Kartal o ekranı Telegram'a fotoğraf olarak atar, sen tek dokunuşla bitirirsin. Tam otomatik moda geçmek için o ekranları birlikte kalibre edeceğiz.

---

## 9. Sorun giderme

| Belirti | Çözüm |
|---|---|
| `adb: no devices` | Wi-Fi değişmedi mi? `adb connect IP:PORT` tekrar. Port değişmişse yeni portu `.env`'e yaz. |
| `unauthorized` | Tablet ekranındaki izin penceresine “Her zaman izin ver”. |
| Ajan 15 dk sonra ölüyor | Pil optimizasyonundan muaf tut + `termux-wake-lock`. |
| Ekran siyah, `screencap` boş | Ekranı `/tus kapat` ile uyandır, sonra kaydır. |
| `/bul` hiçbir şey bulamıyor | Uygulama erişilebilirlik metni vermiyor (bazı oyunlar). `/ekran` + `/tikla X Y` kullan veya Gemini anahtarını ekle. |
| Telegram'a hiç cevap yok | `baslat.sh` çalışıyor mu? Aynı bot token başka yerde `getUpdates` ile yarışıyor olabilir. |

---

## 10. Güvenlik

- Bot token, Gemini anahtarı **sadece** `~/kartal_tablet/.env` içinde (`chmod 600`). Depoya **asla** gitmez.
- Ajan **tek sohbet** ile kilitli; ilk mesajı atan hesap sahibi olur.
- Tablet yalnızca **aynı Wi-Fi** içinden ADB kabul eder; internete port açılmaz.
- Ajan `getUpdates` ile çalışır — yani GitHub Actions ile aynı botu kullanırken çakışmaz (Actions sadece mesaj **gönderir**, okumaz).
