#!/data/data/com.termux/files/usr/bin/bash
# Kartal AI · tek komutla kablosuz ADB bağlantısı
SRC="$HOME/kartal_kaynak/tablet/baglan.py"
[ -f "$SRC" ] || SRC="$HOME/kartal_tablet/baglan.py"
mkdir -p "$HOME/kartal_tablet"
exec python "$SRC" "$@"
