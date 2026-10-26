#!/data/data/com.termux/files/usr/bin/bash
# Kartal AI · Shizuku (rish) köprüsünü Termux'a kurar ve test eder.
# Önce Shizuku uygulamasında: "Use Shizuku in terminal apps" → "Export files"
# Kullanım: bash rish_kur.sh
set -u
G="\033[32m"; Y="\033[33m"; R="\033[31m"; X="\033[0m"
ok()   { echo -e "${G}✔${X} $1"; }
info() { echo -e "${Y}➜${X} $1"; }
err()  { echo -e "${R}✘${X} $1"; }

command -v termux-setup-storage >/dev/null 2>&1 && termux-setup-storage >/dev/null 2>&1 || true

# rish dosyalarını bul
FOUND_RISH=""
FOUND_DEX=""
for d in "$HOME/storage/downloads" "$HOME/storage/shared/Download" "$HOME/storage/shared/Downloads" \
         "$HOME/storage/shared/Documents" "$HOME/storage/shared" "/sdcard/Download" "/sdcard/Download/sh" \
         "/sdcard/Documents" "/sdcard/Documents/sh"; do
  [ -d "$d" ] || continue
  [ -z "$FOUND_RISH" ] && [ -f "$d/rish" ] && FOUND_RISH="$d/rish"
  [ -z "$FOUND_DEX" ]  && [ -f "$d/rish_shizuku.dex" ] && FOUND_DEX="$d/rish_shizuku.dex"
done

if [ -z "$FOUND_RISH" ] || [ -z "$FOUND_DEX" ]; then
  err "rish dosyaları bulunamadı."
  echo "  1) Shizuku aç → 'Use Shizuku in terminal apps' → 'Export files'"
  echo "  2) Hedef klasör olarak Downloads (veya Documents) seç"
  echo "  3) Bu komutu tekrar çalıştır"
  exit 1
fi
ok "Bulundu: $FOUND_RISH"

cp -f "$FOUND_RISH" "$HOME/rish"
cp -f "$FOUND_DEX" "$HOME/rish_shizuku.dex"
chmod +x "$HOME/rish"
chmod 400 "$HOME/rish_shizuku.dex"
export RISH_APPLICATION_ID=com.termux

# rish betiğinin dex yolunu HOME'a çevir (bazı sürümler farklı yol yazar)
if ! grep -q "$HOME/rish_shizuku.dex" "$HOME/rish" 2>/dev/null; then
  sed -i "s#DEX=\".*rish_shizuku.dex\"#DEX=\"$HOME/rish_shizuku.dex\"#" "$HOME/rish" 2>/dev/null || true
fi

info "Köprü test ediliyor…"
OUT=$("$HOME/rish" -c id 2>&1)
echo "   $OUT"

if echo "$OUT" | grep -q "uid=2000"; then
  ok "Shizuku köprüsü ÇALIŞIYOR (uid 2000)"
  mkdir -p "$HOME/kartal_tablet"
  grep -v '^RISH_BIN=' "$HOME/kartal_tablet/.env" > "$HOME/kartal_tablet/.env.tmp" 2>/dev/null || true
  echo "RISH_BIN=$HOME/rish" >> "$HOME/kartal_tablet/.env.tmp"
  mv "$HOME/kartal_tablet/.env.tmp" "$HOME/kartal_tablet/.env"
  ok "Ajan rish'e bağlandı → bash ~/kartal_tablet/baslat.sh"
else
  err "Köprü cevap vermedi. Kontrol:"
  echo "  • Shizuku uygulaması açık ve 'Shizuku is running' yazıyor mu?"
  echo "  • Shizuku → 'Use Shizuku in terminal apps' → Termux için izin verildi mi?"
  echo "  • Dosyalar ~ (Termux ev dizini) içinde mi? (sdcard'da olmaz)"
fi
