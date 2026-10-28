#!/data/data/com.termux/files/usr/bin/bash
# Kartal AI · Tablet kurulum sihirbazı (Samsung Galaxy Tab S7 FE / Android 11+)
# Kullanım:  bash kur.sh
set -e

BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; RESET="\033[0m"
ok()   { echo -e "${GREEN}✔${RESET} $1"; }
info() { echo -e "${YELLOW}➜${RESET} $1"; }
err()  { echo -e "${RED}✘${RESET} $1"; }

KARTAL_DIR="$HOME/kartal_tablet"
mkdir -p "$KARTAL_DIR/shots" "$KARTAL_DIR/indirilenler"

echo -e "${BOLD}🦅 Kartal AI · Tablet Ajanı Kurulumu${RESET}"
echo "------------------------------------------------------------"

# 1) Paketler
info "Paketler kuruluyor (ilk seferde 3-5 dk sürebilir)…"
pkg update -y >/dev/null 2>&1 || true
pkg install -y python android-tools termux-api openssh >/dev/null 2>&1
ok "python + adb + termux-api hazır"

# 2) Termux'u uyanık tut (ekran kapanınca ajan ölmesin)
termux-wake-lock 2>/dev/null && ok "Uyandırma kilidi alındı (ajan arka planda çalışır)" || info "termux-wake-lock yok (Termux:API uygulaması kurulunca aktif olur)"

# 3) Ajanı indir (depo herkese açık, şifre gerekmez)
# ÖNEMLİ: worker + ses.py + paylas2.py + bekci.py BİRLİKTE kopyalanmalı,
# yoksa worker import hatasıyla açılır.
info "Kartal Ajanı indiriliyor…"
if command -v git >/dev/null 2>&1; then
  TMP="$HOME/.kartal_repo"
  rm -rf "$TMP"
  git clone --depth 1 https://github.com/benngokhan/yt_auto_uploader.git "$TMP" >/dev/null 2>&1
  cp -f "$TMP/tablet/"*.py "$KARTAL_DIR/" && ok "Ajan dosyaları kopyalandı (worker + ses + paylas + bekci)" || err "Kopyalanamadı"
  cp -f "$TMP/tablet/"*.sh "$KARTAL_DIR/" 2>/dev/null || true
  rm -rf "$TMP"
else
  err "git yok. 'pkg install git' çalıştır."
fi

# 4) Telegram bot anahtarı
ENVF="$KARTAL_DIR/.env"
touch "$ENVF"; chmod 600 "$ENVF"

if grep -q "^TELEGRAM_BOT_TOKEN=." "$ENVF" 2>/dev/null; then
  ok "Telegram anahtarı zaten kayıtlı"
else
  echo
  echo -e "${BOLD}Telegram bot anahtarı gerekli${RESET}"
  echo "Telegram'da @BotFather → /mybots → botunu seç → API Token"
  read -r -p "Bot token yapıştır (gizli görünür): " TOK
  if [ -n "$TOK" ]; then
    echo "TELEGRAM_BOT_TOKEN=$TOK" >> "$ENVF"
    ok "Token kaydedildi"
  else
    err "Token atlandı — ajan Telegram komutlarını alamaz"
  fi
fi

if grep -q "^GEMINI_API_KEY=." "$ENVF" 2>/dev/null; then
  ok "Gemini anahtarı zaten kayıtlı"
else
  echo
  echo -e "${BOLD}Gemini görüntü anahtarı (opsiyonel ama önerilir)${RESET}"
  echo "https://aistudio.google.com/apikey adresinden ücretsiz alabilirsin."
  echo "Boş bırakırsan ajan yalnızca ekran yazılarıyla çalışır (yine de iş görür)."
  read -r -p "Gemini API key (boş = atla): " GK
  [ -n "$GK" ] && echo "GEMINI_API_KEY=$GK" >> "$ENVF" && ok "Gemini kaydedildi"
fi

# 5) ADB kablosuz bağlantı
echo
echo -e "${BOLD}Kablosuz hata ayıklama bağlantısı${RESET}"
echo "Tablette: Ayarlar → Tablet hakkında → Yapı numarası'na 7 kez dokun"
echo "          Ayarlar → Geliştirici seçenekleri → Kablosuz hata ayıklama = AÇIK"
echo "          'Kablosuz hata ayıklama' ekranındaki IP + Port'u aşağıya yaz (örn 192.168.1.42:41234)"
echo
read -r -p "IP:PORT (boş = şimdilik atla): " TGT
if [ -n "$TGT" ]; then
  echo "ADB_TARGET=$TGT" >> "$ENVF"
  adb connect "$TGT" || true
  sleep 2
  adb devices
  # Pil optimizasyonunu kapat (Samsung ajanı öldürmesin)
  adb shell "dumpsys deviceidle whitelist +com.termux" >/dev/null 2>&1 || true
  adb shell "settings put global stay_on_while_plugged_in 3" >/dev/null 2>&1 || true
  ok "Bağlantı denendi (yukarıda 'device' yazmalı)"
fi

# 6) Başlatma kısayolu (worker + bekçi, arka plan)
cat > "$KARTAL_DIR/baslat.sh" <<'EOS'
#!/data/data/com.termux/files/usr/bin/bash
# KartaL Tablet Ajanı — başlat: worker + bekçi (arka planda)
KARTAL="$HOME/kartal_tablet"
mkdir -p "$KARTAL/log"
termux-wake-lock 2>/dev/null || true
pkill -f kartal_tablet_worker.py 2>/dev/null || true
pkill -f "bekci.py" 2>/dev/null || true
sleep 1
if ! adb devices 2>/dev/null | grep -q "	device"; then
  TGT=$(grep '^ADB_TARGET=' "$KARTAL/.env" 2>/dev/null | cut -d= -f2-)
  [ -n "$TGT" ] && adb connect "$TGT" >/dev/null 2>&1
  adb devices 2>/dev/null | grep -q "	device" || bash "$KARTAL/adbbaglan.sh" >/dev/null 2>&1 || true
fi
cd "$KARTAL"
nohup python kartal_tablet_worker.py >> "$KARTAL/log/ajan.log" 2>&1 &
nohup python bekci.py >> "$KARTAL/log/bekci.log" 2>&1 &
sleep 3
if pgrep -f kartal_tablet_worker.py >/dev/null; then
  echo "🦅 Kartal Tablet Ajanı ayakta (worker + bekçi)"
  echo "   Telefona /menu yaz. Sesli mesaj da işe yarar."
else
  echo "❌ Worker başlamadı — log sonu:"
  tail -10 "$KARTAL/log/ajan.log" 2>/dev/null
fi
EOS
chmod +x "$KARTAL_DIR/baslat.sh"

# Otomatik bağlanıcıları da yanına koy
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
for f in baglan.py adbbaglan.sh baglan.sh; do
  if [ -f "$SRC_DIR/$f" ]; then
    cp -f "$SRC_DIR/$f" "$KARTAL_DIR/" && chmod +x "$KARTAL_DIR/$f"
  fi
done
[ -f "$KARTAL_DIR/adbbaglan.sh" ] && chmod +x "$KARTAL_DIR/adbbaglan.sh"

echo
echo -e "${GREEN}${BOLD}✅ Kurulum bitti!${RESET}"
echo "Başlatmak için:  bash ~/kartal_tablet/baslat.sh"
echo "Sonra telefondan botuna /menu yaz."
echo
echo -e "${YELLOW}Not:${RESET} Termux'u pil optimizasyonundan muaf tut (Ayarlar → Pil → Termux → Kısıtlama yok)"
