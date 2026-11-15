#!/usr/bin/env python3
"""Tamirci botunun Telegram düğmelerini işler.

Düğmeler (ajan_heal._dugmeler):
  - "📋 Durum"          -> callback "durum"        : son 24 saatin hata özeti
  - "🔍 Bu hataya bak"  -> callback "bak:<run_id>" : o koşunun logunu sade dille anlatır

Telegram onay işçisiyle aynı workflow turunda (5 dk) çalışır; ek koşu/dakika harcamaz.
Hiçbir dosya yazmaz/commit etmez: işlenen güncellemeler Telegram tarafında
offset ile onaylanır. Yalnız TELEGRAM_CHAT_ID grubundan gelen basışlar işlenir.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import ajan_heal as a

try:
    from zoneinfo import ZoneInfo
    TR = ZoneInfo("Europe/Istanbul")
except Exception:  # pragma: no cover
    TR = timezone.utc

CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
MAX_ISLEM = 6  # tek turda en çok bu kadar farklı istek yanıtlanır (spam engeli)


def _saat(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TR).strftime("%d.%m %H:%M")
    except Exception:
        return "?"


def _gonder(text: str, markup: dict | None = None, yanit_id: int | None = None) -> None:
    payload = {"chat_id": CHAT, "text": text[:3900], "parse_mode": "HTML",
               "disable_web_page_preview": True, "reply_markup": markup or a._dugmeler()}
    if yanit_id:
        payload["reply_to_message_id"] = yanit_id
        payload["allow_sending_without_reply"] = True
    a._tg_api("sendMessage", payload)


def durum_metni() -> tuple[str, dict]:
    """(mesaj, düğmeler) — son 24 saatin sade durum özeti."""
    state = a._state_load()
    simdi = datetime.now(TR).strftime("%d.%m %H:%M")
    try:
        failed = [r for r in a._get_failed_runs() if not state.get(str(r["id"]), {}).get("devredildi")]
    except Exception as e:
        return (f"📋 <b>Durum</b> — {simdi}\n\nGitHub'a şu an ulaşamadım ({a._e(type(e).__name__, 40)}). "
                f"Birkaç dakika sonra tekrar dener misin?"), a._dugmeler()

    satirlar = [f"📋 <b>Durum</b> — {simdi}", ""]
    tuslar = []
    if not failed:
        satirlar.append("✅ Son 24 saatte çözülmemiş hata yok.")
    else:
        satirlar.append(f"🔴 Son 24 saatte çözülmemiş <b>{len(failed)}</b> hata var:")
        for r in failed[:8]:
            kayit = state.get(str(r["id"]), {})
            tur = kayit.get("kind")
            if tur:
                sorun, _, _ = a._sorun_ozeti(tur, "")
            else:
                sorun = "Henüz incelemedim; bir sonraki taramada bakacağım."
            if kayit.get("gave_up"):
                hal = "bıraktım, elle bakılmalı"
            elif kayit.get("attempts"):
                hal = f"{kayit['attempts']}/{a.MAX_REPAIR_ATTEMPTS} kez denedim"
            else:
                hal = "sırada"
            satirlar.append(f"• <b>{a._e(a._is_adi(r['name']), 60)}</b> ({_saat(r['created_at'])}) — {a._e(sorun, 160)} <i>[{hal}]</i>")
        if len(failed) > 8:
            satirlar.append(f"… ve {len(failed) - 8} hata daha.")
        for r in failed[:4]:
            tuslar.append([{"text": f"🔍 {a._is_adi(r['name'])[:28]}", "callback_data": f"bak:{r['id']}"}])

    # Ek bilgi: çalışan işler ve son video yükleme
    try:
        son = a._gh("GET", "actions/runs?per_page=60").get("workflow_runs", [])
        calisan = sum(1 for r in son if r.get("status") in ("in_progress", "queued"))
        satirlar.append("")
        satirlar.append(f"Şu an çalışan iş: {calisan}")
        for r in son:
            if r.get("name") == "YouTube Drive Uploader" and r.get("status") == "completed":
                sonuc = {"success": "✅ başarılı", "failure": "🔴 başarısız", "cancelled": "⚪ iptal"}.get(r.get("conclusion"), r.get("conclusion") or "?")
                satirlar.append(f"Son video yükleme işi: {sonuc} ({_saat(r['created_at'])})")
                break
    except Exception:
        pass
    saglik = state.get("_health", {}).get("ts")
    if saglik:
        satirlar.append(f"Son hata taramam: {_saat(saglik)}")

    tuslar.append([{"text": "📋 Durumu yenile", "callback_data": "durum"}])
    return "\n".join(satirlar), {"inline_keyboard": tuslar}


def hata_metni(run_id: int) -> str:
    """Bir koşunun hatasını sade Türkçe anlatır."""
    try:
        run = a._gh("GET", f"actions/runs/{run_id}")
    except Exception:
        return "🔍 Bu işin kaydına ulaşamadım; kayıt silinmiş ya da çok eski olabilir."
    ad = a._e(a._is_adi(run.get("name", "?")), 60)
    link = a._kayit_linki(run.get("html_url", ""))
    sonuc = run.get("conclusion")
    if run.get("status") != "completed":
        return f"🔍 <b>{ad}</b>\n\nBu iş şu an yeniden çalışıyor; sonucu bekliyorum.\nKoşu: {link}"
    if sonuc == "success":
        return f"🔍 <b>{ad}</b>\n\n✅ Bu iş sonradan başarıyla tamamlandı; şu an bir sorun yok.\nKoşu: {link}"
    if sonuc != "failure":
        return f"🔍 <b>{ad}</b>\n\nBu iş hata vermedi; iptal edilmiş ya da atlanmış görünüyor.\nKoşu: {link}"

    log = a._get_log_tail(run_id)
    tur = a._classify(log)
    sorun, cozum, kim = a._sorun_ozeti(tur, log)
    kimden = {"sen": "Senin bakman gerekiyor.", "ajan": "Bunu ben hallediyorum.", "yok": "Senin bir şey yapmana gerek yok."}.get(kim, "")
    devir = a._state_load().get(str(run_id), {}).get("devredildi")

    ayrinti = ""
    try:
        yanit = a._llm(
            "Sen bir YouTube otomasyon sisteminin tamircisisin. Aşağıda başarısız bir işin hata kaydı var. "
            "Bunu teknik bilgisi olmayan kanal sahibine EN FAZLA 3 kısa cümleyle, sade Türkçe anlat: "
            "ne oldu ve neden oldu. Kod, dosya yolu, İngilizce terim kullanma. Kayıtta olmayan bir şeyi "
            "uydurma; emin değilsen 'kayıttan tam anlaşılmıyor' de. Yalnız açıklamayı yaz.\n\n"
            f"İş: {run.get('name')}\nÖn teşhis: {sorun}\n\nKAYIT:\n{log[-3500:]}"
        )
        ayrinti = " ".join((yanit or "").split())
    except Exception as e:
        print(f"[bak] LLM açıklaması alınamadı: {type(e).__name__}")

    parcalar = [f"🔍 <b>{ad} — hata açıklaması</b>", "", f"Sorun: {a._e(sorun, 300)}"]
    if ayrinti:
        parcalar.append(f"Ayrıntı: {a._e(ayrinti, 700)}")
    parcalar.append(f"Ne yapmalı: {a._e(cozum, 300)}")
    if devir:
        parcalar.append("Durum: Yerine yeni bir iş başlatıldı; bu eski kayıttır.")
    elif kimden:
        parcalar.append(kimden)
    parcalar.append(f"Koşu: {link}")
    return "\n".join(parcalar)


def main() -> None:
    if not CHAT or not os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        print("[tamirci-buton] token/chat yok, atlandı")
        return
    veri = a._tg_api("getUpdates", {"timeout": 0, "allowed_updates": ["callback_query"]})
    guncellemeler = veri.get("result") or []
    print(f"[tamirci-buton] {len(guncellemeler)} düğme basışı bekliyor")
    if not guncellemeler:
        return

    islenen: set[str] = set()
    for upd in guncellemeler:
        cb = upd.get("callback_query") or {}
        if not cb:
            continue
        # Basışı kapat (eskiyse Telegram reddeder; önemli değil)
        a._tg_api("answerCallbackQuery", {"callback_query_id": cb.get("id"), "text": "Bakıyorum…"})
        msg = cb.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != CHAT:
            print("[tamirci-buton] yabancı sohbetten basış, yok sayıldı")
            continue
        data = str(cb.get("data") or "")
        if data in islenen:  # aynı düğmeye art arda basılmışsa tek yanıt
            continue
        if len(islenen) >= MAX_ISLEM:
            break
        islenen.add(data)
        try:
            if data == "durum":
                metin, tuslar = durum_metni()
                _gonder(metin, tuslar)
            elif data.startswith("bak:") and data[4:].isdigit():
                rid = int(data[4:])
                _gonder(hata_metni(rid), a._dugmeler(), msg.get("message_id"))
            else:
                print(f"[tamirci-buton] tanınmayan düğme: {data[:30]}")
        except Exception as e:
            print(f"[tamirci-buton] işlem hatası: {type(e).__name__}: {e}")
            _gonder("🔧 Bu isteği işlerken takıldım. Birkaç dakika sonra tekrar dener misin?")

    # İşlenenleri Telegram'da onayla (bir daha gelmesinler)
    son_id = max(u["update_id"] for u in guncellemeler)
    a._tg_api("getUpdates", {"offset": son_id + 1, "limit": 1, "timeout": 0, "allowed_updates": ["callback_query"]})


if __name__ == "__main__":
    main()
