import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import telegram_onay as to  # noqa: E402


def _updates(icerikler, offset=41):
    return {"ok": True, "result": [
        {"update_id": offset + i, "message": {"chat": {"id": 777}, "text": metin}}
        for i, metin in enumerate(icerikler)
    ]}


class TelegramOnayTests(unittest.TestCase):
    def test_preview_message_is_simple_and_has_no_secret(self):
        metin = to.preview_metni({"baslik": "Mum neden söner?", "sure_sn": 42,
                                  "sahne_sayisi": 7, "kaynak_video_id": "abcdefghijk",
                                  "video_numarasi": 194})
        self.assertIn("video_194", metin)
        self.assertIn("Mum neden söner?", metin)
        self.assertIn("onayladım", metin)
        self.assertIn("7", metin)
        self.assertNotIn("TELEGRAM_BOT_TOKEN", metin)

    def test_preview_sends_video_then_cover_and_stores_offset(self):
        with tempfile.TemporaryDirectory() as td:
            kok = Path(td)
            video, kapak = kok / "final.mp4", kok / "kapak.jpg"
            video.write_bytes(b"video-bytes")
            kapak.write_bytes(b"cover-bytes")
            durum_yolu = kok / "durum.json"
            sirasi = []

            def sahte_upload(token, method, fields, alan, yol):
                sirasi.append((method, alan, yol.name, fields.get("chat_id")))
                if method == "sendVideo":
                    return {"ok": True, "result": {"message_id": 1, "update_id": 41}}
                return {"ok": True, "result": {"message_id": 2}}

            with mock.patch.dict(os.environ, {"TELEGRAM_ONAY_DURUM": str(durum_yolu)}, clear=False), \
                 mock.patch.object(to, "_credentials", return_value=("gizli-token-satirda-yok", "777")), \
                 mock.patch.object(to, "_upload", side_effect=sahte_upload):
                durum = to.gonder_onizleme(video, kapak, {"baslik": "Test"})

            self.assertEqual([s[0] for s in sirasi], ["sendVideo", "sendPhoto"])
            self.assertEqual([s[1] for s in sirasi], ["video", "photo"])
            self.assertEqual(durum["offset"], 41)
            self.assertNotIn("gizli-token-satirda-yok", durum_yolu.read_text(encoding="utf-8"))

    def test_only_exact_approval_from_right_chat_after_preview_counts(self):
        with tempfile.TemporaryDirectory() as td:
            durum_yolu = Path(td) / "durum.json"
            durum_yolu.write_text(json.dumps({"offset": 41}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"TELEGRAM_ONAY_DURUM": str(durum_yolu)}, clear=False), \
                 mock.patch.object(to, "_credentials", return_value=("token", "777")), \
                 mock.patch.object(to, "_call", return_value=_updates(["merhaba", "onayladım"])):
                self.assertTrue(to.onay_var_mi())
            self.assertEqual(json.loads(durum_yolu.read_text(encoding="utf-8"))["offset"], 42)

        with tempfile.TemporaryDirectory() as td:
            durum_yolu = Path(td) / "durum.json"
            durum_yolu.write_text(json.dumps({"offset": 41}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"TELEGRAM_ONAY_DURUM": str(durum_yolu)}, clear=False), \
                 mock.patch.object(to, "_credentials", return_value=("token", "777")), \
                 mock.patch.object(to, "_call", return_value={"ok": True, "result": [
                     {"update_id": 42, "message": {"chat": {"id": 999}, "text": "onayladım"}},
                     {"update_id": 43, "message": {"chat": {"id": 777}, "text": "onayladim lütfen"}},
                 ]}):
                self.assertFalse(to.onay_var_mi())

    def test_approval_before_preview_is_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            durum_yolu = Path(td) / "durum.json"
            durum_yolu.write_text(json.dumps({"offset": 50}), encoding="utf-8")
            with mock.patch.dict(os.environ, {"TELEGRAM_ONAY_DURUM": str(durum_yolu)}, clear=False), \
                 mock.patch.object(to, "_credentials", return_value=("token", "777")), \
                 mock.patch.object(to, "_call", return_value={"ok": True, "result": []}):
                self.assertFalse(to.onay_var_mi())

    def test_missing_credentials_fail_closed(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(to.TelegramOnayHatasi):
                to._credentials()


if __name__ == "__main__":
    unittest.main()
