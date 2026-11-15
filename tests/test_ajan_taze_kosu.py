"""Tamirci: git çakışmasında eski koşuyu re-run etmek yerine main'de taze koşu başlatır.

Kök neden (15.11.2026): re-run, koşuyu ESKİ commit + ESKİ workflow dosyasıyla tekrarlar;
depo ilerlediği için push yine reddedilir ve 3 deneme boşa gider.
"""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ajan_heal as a  # noqa: E402

GIRDISIZ = "name: x\non:\n  workflow_dispatch:\n  schedule:\n    - cron: '17 3 * * *'\njobs: {}\n"
GIRDILI = "name: x\non:\n  workflow_dispatch:\n    inputs:\n      no:\n        required: true\n  schedule:\n    - cron: '1 1 * * *'\n"
BOS_SUSLU = "on:\n  schedule:\n    - cron: '*/30 * * * *'\n  workflow_dispatch: {}\n\npermissions:\n  contents: write\n"
DISPATCHSIZ = "on:\n  schedule:\n    - cron: '1 1 * * *'\n"


def test_girdisiz_dispatch_algilama():
    assert a._girdisiz_dispatch_var(GIRDISIZ)
    assert a._girdisiz_dispatch_var(BOS_SUSLU)
    assert not a._girdisiz_dispatch_var(GIRDILI)
    assert not a._girdisiz_dispatch_var(DISPATCHSIZ)


def _kur(monkeypatch, tmp_path, yaml):
    cagri = []

    def sahte_gh(method, path, body=None, timeout=30):
        cagri.append((method, path, body))
        if method == "GET" and path.startswith("contents/"):
            return {"content": base64.b64encode(yaml.encode()).decode()}
        return {}

    monkeypatch.setattr(a, "_gh", sahte_gh)
    monkeypatch.setattr(a, "STATE_FILE", tmp_path / "state.json")
    return cagri


RUN = {"id": 111, "path": ".github/workflows/konu-onerileri.yml"}


def test_girdisiz_workflow_taze_baslatilir(monkeypatch, tmp_path):
    cagri = _kur(monkeypatch, tmp_path, GIRDISIZ)
    state = {}
    assert a._restart(RUN, state) == "taze"
    assert ("POST", "actions/workflows/konu-onerileri.yml/dispatches", {"ref": "main"}) in cagri
    assert not any("rerun" in c[1] for c in cagri)
    assert state["111"]["devredildi"] is True


def test_girdili_workflow_eski_usul_rerun(monkeypatch, tmp_path):
    cagri = _kur(monkeypatch, tmp_path, GIRDILI)
    assert a._restart(RUN, {}) == "rerun"
    assert any(c[1] == "actions/runs/111/rerun-failed-jobs" for c in cagri)
    assert not any("dispatches" in c[1] for c in cagri)


def test_taze_kosu_siniri_sonsuz_donguyu_keser(monkeypatch, tmp_path):
    cagri = _kur(monkeypatch, tmp_path, GIRDISIZ)
    state = {}
    for i in range(a.MAX_FRESH_RUNS):
        assert a._restart({"id": 200 + i, "path": RUN["path"]}, state) == "taze"
    assert a._restart({"id": 999, "path": RUN["path"]}, state) == "limit"
    assert sum("dispatches" in c[1] for c in cagri) == a.MAX_FRESH_RUNS


def test_devredilen_kosu_tekrar_islenmez(monkeypatch, tmp_path):
    _kur(monkeypatch, tmp_path, GIRDISIZ)
    a._state_save({"111": {"attempts": 1, "kind": "git_cakismasi", "devredildi": True},
                   "_health": {"last_failed_count": 1}})
    monkeypatch.setattr(a, "_get_failed_runs", lambda: [{"id": 111, "name": "x", "html_url": "u", "path": RUN["path"]}])
    mesajlar = []
    monkeypatch.setattr(a, "_tg", mesajlar.append)
    monkeypatch.setattr(a, "_get_log_tail", lambda rid: (_ for _ in ()).throw(AssertionError("işlenmemeliydi")))
    a.main()
    assert len(mesajlar) == 1 and "temizlendi" in mesajlar[0]


def test_git_cakismasi_ana_akista_taze_kosu(monkeypatch, tmp_path):
    cagri = _kur(monkeypatch, tmp_path, GIRDISIZ)
    monkeypatch.setattr(a, "_get_failed_runs", lambda: [{"id": 111, "name": "Analizli konu önerilerini güncelle", "html_url": "u", "path": RUN["path"]}])
    monkeypatch.setattr(a, "_get_log_tail", lambda rid: " ! [rejected] main -> main (fetch first)\nerror: failed to push some refs")
    mesajlar = []
    monkeypatch.setattr(a, "_tg", mesajlar.append)
    a.main()
    assert any("dispatches" in c[1] for c in cagri)
    assert not any("rerun" in c[1] for c in cagri)
    assert len(mesajlar) == 1 and "geçici sorun" in mesajlar[0]
