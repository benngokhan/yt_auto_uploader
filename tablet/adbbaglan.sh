#!/data/data/com.termux/files/usr/bin/bash
# Kartal AI · Kablosuz ADB otomatik bağlanıcı
# IP/port ezberlemek yok: tablete kendi kendine bağlanır.
# Kullanım:  bash ~/kartal_tablet/adbbaglan.sh   ya da   bash adbbaglan.sh 192.168.1.42:41234
set -u

GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; RESET="\033[0m"
ok()   { echo -e "${GREEN}✔${RESET} $1"; }
info() { echo -e "${YELLOW}➜${RESET} $1"; }
err()  { echo -e "${RED}✘${RESET} $1"; }

command -v adb >/dev/null 2>&1 || { err "adb yok. Önce: pkg install android-tools"; exit 1; }

# 0) Zaten bağlı mı?
if adb devices 2>/dev/null | grep -qP "\tdevice$"; then
  ok "Zaten bağlı:"; adb devices | grep -P "\tdevice$"
  TGT=$(adb devices | grep -P "\tdevice$" | head -n1 | cut -f1)
  SAVE="$HOME/kartal_tablet/.env"
  mkdir -p "$(dirname "$SAVE")"; touch "$SAVE"
  grep -v '^ADB_TARGET=' "$SAVE" > "$SAVE.tmp" 2>/dev/null || true
  echo "ADB_TARGET=$TGT" >> "$SAVE.tmp" && mv "$SAVE.tmp" "$SAVE"
  exit 0
fi

CONNECTED=0

# 1) Elle verildiyse onu kullan
if [ $# -ge 1 ] && [ -n "${1:-}" ]; then
  info "Verilen hedefe bağlanılıyor: $1"
  adb connect "$1" >/dev/null 2>&1
fi

# 2) mDNS ile otomatik keşif (kablosuz hata ayıklama açıksa cihaz kendini yayınlar)
if ! adb devices 2>/dev/null | grep -qP "\tdevice$"; then
  info "Ağda ADB servisi aranıyor (mDNS)…"
  adb mdns check >/dev/null 2>&1 || true
  sleep 1
  HOSTS=$(adb mdns services 2>/dev/null | grep -E "_adb-tls-connect" | awk '{print $NF}' | sort -u)
  if [ -n "$HOSTS" ]; then
    for h in $HOSTS; do
      info "Bulundu: $h"
      adb connect "$h" >/dev/null 2>&1
      sleep 2
      adb devices | grep -qP "\tdevice$" && { CONNECTED=1; break; }
    done
  else
    info "mDNS servisi görünmedi (normal olabilir), yerel IP deneniyor…"
  fi
fi

# 3) Yerel Wi-Fi IP + yaygın portlar denenir
if [ "$CONNECTED" -eq 0 ] && ! adb devices 2>/dev/null | grep -qP "\tdevice$"; then
  MYIP=$(ip -4 addr show wlan0 2>/dev/null | grep -oP 'inet \K[0-9.]+' | head -n1)
  [ -z "$MYIP" ] && MYIP=$(ifconfig wlan0 2>/dev/null | grep -oP 'inet \K[0-9.]+' | head -n1)
  if [ -n "$MYIP" ]; then
    info "Tabletin Wi-Fi IP'si: $MYIP"
    for p in 5555 41234 37777 $(adb mdns services 2>/dev/null | grep -oE '[0-9]{4,5}$' | sort -u); do
      adb connect "$MYIP:$p" >/dev/null 2>&1
      sleep 1
      adb devices | grep -qP "\tdevice$" && { CONNECTED=1; break; }
    done
  else
    err "Wi-Fi IP okunamadı (Wi-Fi kapalı olabilir)."
  fi
fi

echo
adb devices

if adb devices 2>/dev/null | grep -qP "\tdevice$"; then
  TGT=$(adb devices | grep -P "\tdevice$" | head -n1 | cut -f1)
  ok "Bağlandı: $TGT"
  SAVE="$HOME/kartal_tablet/.env"
  mkdir -p "$(dirname "$SAVE")"; touch "$SAVE"
  grep -v '^ADB_TARGET=' "$SAVE" > "$SAVE.tmp" 2>/dev/null || true
  echo "ADB_TARGET=$TGT" >> "$SAVE.tmp" && mv "$SAVE.tmp" "$SAVE"
  ok "Hedef .env'e kaydedildi, bir daha sormayacak."
  exit 0
fi

if adb devices 2>/dev/null | grep -q "unauthorized"; then
  err "Tablet izin bekliyor → ekrandaki 'USB hata ayıklamasına izin ver' penceresinde 'Her zaman izin ver' + 'İzin ver'."
  exit 2
fi

err "Otomatik bağlanamadım. Elle yol:"
cat <<'EOS'

  1) Ayarlar → Geliştirici seçenekleri → Kablosuz hata ayıklama = AÇIK
  2) Aynı ekranda "Kablosuz hata ayıklama" YAZISINA dokun (anahtar değil)
  3) Açılan sayfada "IP adresi ve bağlantı noktası" yazar → örn 192.168.1.42:41234
  4) Şunu çalıştır:
       bash ~/kartal_tablet/adbbaglan.sh 192.168.1.42:41234
EOS
exit 1
