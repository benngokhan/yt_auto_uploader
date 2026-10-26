#!/data/data/com.termux/files/usr/bin/bash
# Eski isim -> yeni otomatik kurucuya yönlendirir
DIR="$HOME/kartal_kaynak/tablet"
[ -f "$DIR/baglan.py" ] || DIR="$HOME/kartal_tablet"
exec python "$DIR/baglan.py" "$@"
