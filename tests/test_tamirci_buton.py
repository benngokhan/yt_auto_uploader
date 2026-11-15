"""Tamirci Telegram düğmeleri: 'Durum' ve 'Bu hataya bak'."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ajan_heal as a  # noqa: E402
import tamirci_buton_worker as w  # noqa: E402

RUN = {"id": 111, "name": "YouTube Drive Uploader", "created_at": "2026-11-15T05:00:00Z",
       "html_url": "https://github.com/x/y/actions/runs/111", "status": "completed", "conclusion": "failure"}


def _kur(monkeypatch, tmp_path, guncellemeler, failed=()):
    cagri = []

    def sahte_tg(method, payload):
        cagri.append((method, payload))
        if method == "getUpdates" and "offset" not in payload:
            return {"ok": True, "result": guncellemeler}
        return {"ok": True, "result": {"message_id": 5}}

    monkeypatch.setattr(a, "_tg_api", sahte_tg)
    monkeypatch.setattr(a, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(a, "_get_failed_runs", lambda: list(failed))
    monkeypatch.setattr(a, "_gh", lambda m, p, b=None, timeout=30: RUN if p == "actions/runs/111" else {"workflow_runs": []})
    monkeypatch.setattr(a, "_get_log_tail", lambda rid: "error: failed to push some refs (fetch first)")
    monkeypatch.setattr(a, "_llm", lambda prompt: "İki iş aynı anda kayıt yapmaya çalıştı.")
    monkeypatch.setattr(w, "CHAT", "-100")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    return cagri


def _cb(uid, data, chat=-100):
    return {"update_id": uid, "callback_query": {"id": str(uid), "data": data,
            "message": {"message_id": 9, "chat": {"id": chat}}}}


def _mesajlar(cagri):
    return [p for m, p in cagri if m == "sendMessage"]


def test_dugmeler():
    assert a._dugmeler()["inline_keyboard"][0][0]["callback_data"] == "durum"
    satir = a._dugmeler(42)["inline_keyboard"][0]
    assert [d["callback_data"] for d in satir] == ["bak:42", "durum"]
    assert all(len(d["callback_data"].encode()) <= 64 for d in a._dugmeler(99999999999)["inline_keyboard"][0])


def test_durum_hata_yok(monkeypatch, tmp_path):
    cagri = _kur(monkeypatch, tmp_path, [_cb(1, "durum")])
    w.main()
    m = _mesajlar(cagri)
    assert len(m) == 1 and "çözülmemiş hata yok" in m[0]["text"] and m[0]["chat_id"] == "-100"
    # işlenenler Telegram'da onaylanır
    assert ("getUpdates", {"offset": 2, "limit": 1, "timeout": 0, "allowed_updates": ["callback_query"]}) in cagri


def test_durum_hatalari_listeler(monkeypatch, tmp_path):
    cagri = _kur(monkeypatch, tmp_path, [_cb(1, "durum")], failed=[RUN])
    a._state_save({"111": {"attempts": 3, "kind": "git_cakismasi", "gave_up": True}})
    w.main()
    m = _mesajlar(cagri)[0]
    assert "Video yükleme" in m["text"] and "bıraktım" in m["text"]
    assert m["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "bak:111"


def test_devredilen_hata_durumda_sayilmaz(monkeypatch, tmp_path):
    cagri = _kur(monkeypatch, tmp_path, [_cb(1, "durum")], failed=[RUN])
    a._state_save({"111": {"devredildi": True}})
    w.main()
    assert "çözülmemiş hata yok" in _mesajlar(cagri)[0]["text"]


def test_hataya_bak_sade_aciklar(monkeypatch, tmp_path):
    cagri = _kur(monkeypatch, tmp_path, [_cb(7, "bak:111")])
    w.main()
    m = _mesajlar(cagri)[0]
    assert "hata açıklaması" in m["text"] and "aynı anda" in m["text"]
    assert m["reply_to_message_id"] == 9


def test_ayni_dugmeye_cok_basis_tek_yanit(monkeypatch, tmp_path):
    cagri = _kur(monkeypatch, tmp_path, [_cb(1, "durum"), _cb(2, "durum"), _cb(3, "durum")])
    w.main()
    assert len(_mesajlar(cagri)) == 1
    assert any(m == "getUpdates" and p.get("offset") == 4 for m, p in cagri)


def test_yabanci_sohbet_ve_bozuk_veri_yok_sayilir(monkeypatch, tmp_path):
    cagri = _kur(monkeypatch, tmp_path, [_cb(1, "durum", chat=555), _cb(2, "bak:abc"), _cb(3, "sil:her_sey")])
    w.main()
    assert _mesajlar(cagri) == []


def test_llm_cokerse_yine_yanit_verir(monkeypatch, tmp_path):
    cagri = _kur(monkeypatch, tmp_path, [_cb(1, "bak:111")])
    monkeypatch.setattr(a, "_llm", lambda p: (_ for _ in ()).throw(RuntimeError("x")))
    w.main()
    m = _mesajlar(cagri)[0]
    assert "Sorun:" in m["text"] and "Ayrıntı" not in m["text"]


def test_bekleyen_yoksa_sessiz(monkeypatch, tmp_path):
    cagri = _kur(monkeypatch, tmp_path, [])
    w.main()
    assert [m for m, _ in cagri] == ["getUpdates"]
