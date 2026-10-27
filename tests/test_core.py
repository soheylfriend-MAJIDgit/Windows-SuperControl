# -*- coding: utf-8 -*-
"""تستهای بدون رابط گرافیکی برای هستهٔ Windows SuperControl.

اجرا:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bootstrap as b  # noqa: E402

FOLDER_ID = "1PmMAu537pzN3mjKf_PYctUOlbOIQCUf1"
MAIN_ID = "1GtCEP0gcIKR2xQ_lBc1WrTdT1VEw6vTW"
CONFIG_ID = "1nrCZJoXHuLXmQir9xwLrO1dEWV5OdYog"
DIALOG_ID = "10z2lb0jbThUh8kaWERYUttxudeCzX-Wf"
CODE_ID = "11B1QGU0zuhD53sdNk_y5TAo_Qq-KkEI9"


def folder_html(entries, code_bytes_version=1):
    """شبیهسازی خروجی embeddedfolderview."""
    rows = []
    for name, fid in entries:
        rows.append(
            '<div class="flip-entry" data-id="%s" data-title="%s">'
            '<a href="https://drive.google.com/file/d/%s/view?usp=drive_web">'
            '<img alt="Plain Text" src="x.png"><div class="flip-entry-title">%s</div>'
            '</a></div>' % (fid, name, fid, name)
        )
    return "<html><body>" + "".join(rows) + "</body></html>"


DEFAULT_ENTRIES = [
    ("Code.gs.txt", "1uO9Z0-4yyIi05BCGy63y3JnTDy1CmxE2"),
    ("config.txt", CONFIG_ID),
    ("dialog.txt", DIALOG_ID),
    ("main.py.txt", MAIN_ID),
    ("name.txt", "1fzI9jceihjTmeJ4wYguWYA0EGMV3EcMP"),
    ("salam.py.txt", CODE_ID),
]

CODE_V1 = b"# -*- coding: utf-8 -*-\nprint('salam v1')\n"
CODE_V2 = b"# -*- coding: utf-8 -*-\nprint('salam v2 - edited')\n"
DIALOG_TEXT = (
    "id=1\nfrom=Arena Agent (chat)\ntype=yesno\n"
    "question=\u0627\u0631\u062a\u0628\u0627\u0637 \u0628\u0631\u0642\u0631\u0627\u0631\u0647\u061f\n"
    "note=\u0627\u06cc\u0646 \u06cc\u06a9 \u067e\u06cc\u0627\u0645 \u062a\u0633\u062a\u06cc \u0627\u0633\u062a.\n"
    "answer=\n"
)


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.state_file = self.root / "state.json"
        self.log_file = self.root / "launch.log"
        self.answer_file = self.root / "dialog-answer.txt"
        self.local_drive = self.root / "drive"
        self.local_drive.mkdir()

        self.patchers = [
            mock.patch.object(b, "DATA", self.root),
            mock.patch.object(b, "STATE_FILE", self.state_file),
            mock.patch.object(b, "CACHE_DIR", self.cache),
            mock.patch.object(b, "LOG_FILE", self.log_file),
            mock.patch.object(b, "ANSWER_FILE", self.answer_file),
            mock.patch.object(b, "STARTED_FLAG", self.root / "started.flag"),
            mock.patch.object(b, "HERE", self.root),
        ]
        for p in self.patchers:
            p.start()

        self.code = {"bytes": CODE_V1}
        self.entries = list(DEFAULT_ENTRIES)
        self.html = {"text": folder_html(self.entries)}
        self.dialog = {"text": DIALOG_TEXT}
        self.downloads = []
        self.runs = []

        def fake_download(fid, timeout=20):
            self.downloads.append(fid)
            if fid == CONFIG_ID:
                return (b"# remote config\nWEBAPP_URL=\nWEBAPP_SECRET=\n")
            if fid == DIALOG_ID:
                return self.dialog["text"].encode("utf-8")
            if fid == CODE_ID:
                return self.code["bytes"]
            raise b.DriveError("unknown id " + fid)

        def fake_list(fid):
            return b.parse_folder_html(self.html["text"])

        def fake_run(argv, **kwargs):
            self.runs.append((argv, kwargs))

            class P:
                returncode = 0
                stdout = b"hello from code\n"
                stderr = b""

            return P()

        self.dl_patch = mock.patch.object(b, "download_file", side_effect=fake_download)
        self.ls_patch = mock.patch.object(b, "list_folder", side_effect=fake_list)
        self.run_patch = mock.patch.object(b.subprocess, "run", side_effect=fake_run)
        self.dl_patch.start()
        self.ls_patch.start()
        self.run_patch.start()
        self.patchers += [self.dl_patch, self.ls_patch, self.run_patch]

        self.core = b.Core()
        self.core.cfg["LOCAL_DRIVE_PATH"] = str(self.local_drive)
        self.core.cfg["WEBAPP_URL"] = ""
        self.api = b.Api(self.core)

    def tearDown(self):
        try:
            self.core.shutdown()
        except Exception:
            pass
        for p in reversed(self.patchers):
            p.stop()
        self.tmp.cleanup()

    def wait_runs(self, count=1, tries=50):
        import time
        for _ in range(tries):
            with self.core.lock:
                if sum(1 for f in self.core.state["files"].values()
                       if f.get("runs", 0) >= count) >= 1:
                    return
            time.sleep(0.02)
        self.fail("code execution did not finish")


class TestParsers(Harness):
    def test_folder_listing_parser(self):
        items = b.parse_folder_html(folder_html(DEFAULT_ENTRIES))
        names = {i["name"] for i in items}
        self.assertIn("salam.py.txt", names)
        self.assertIn("config.txt", names)
        self.assertIn(CODE_ID, {i["id"] for i in items})

    def test_folder_listing_link_only(self):
        raw = ('<a href="/file/d/%s/view">salam.py.txt</a>' % CODE_ID)
        items = b.parse_folder_html(raw)
        self.assertEqual(items[0]["id"], CODE_ID)
        self.assertEqual(items[0]["name"], "salam.py.txt")

    def test_data_title_only(self):
        raw = '<div data-title="test.py.txt" data-id="%s"></div>' % CODE_ID
        items = b.parse_folder_html(raw)
        self.assertEqual(items[0]["name"], "test.py.txt")

    def test_flip_entry_title_blocks(self):
        # ساختار جایگزین گوگل: نام فقط داخل div مخصوص عنوان است
        raw = (
            '<div class="flip-entry" id="entry-%s">'
            '<a href="https://drive.google.com/file/d/%s/view?usp=drive_web">'
            '<img alt="Plain Text" src="t.png">'
            '<div class="flip-entry-title">salam.py.txt</div>'
            '<div class="flip-entry-last-modified">4:20 pm</div>'
            '</a></div>' % (CODE_ID, CODE_ID)
        )
        items = b.parse_folder_html(raw)
        self.assertEqual(items[0]["id"], CODE_ID)
        self.assertEqual(items[0]["name"], "salam.py.txt")

    def test_open_link_fallback(self):
        raw = ('<div class="flip-entry"><a href="https://drive.google.com/open?id=%s">'
               '<div class="flip-entry-title">new.py.txt</div></a></div>' % CODE_ID)
        items = b.parse_folder_html(raw)
        self.assertEqual(items[0]["name"], "new.py.txt")

    def test_dialog_parser(self):
        blocks = b.parse_dialogs(DIALOG_TEXT)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["id"], "1")
        self.assertEqual(blocks[0]["type"], "yesno")
        self.assertEqual(blocks[0]["answer"], "")

    def test_multiple_dialogs(self):
        blocks = b.parse_dialogs("id=1\nquestion=A\nanswer=\nid=2\nquestion=B\nanswer=بله\n")
        self.assertEqual([x["id"] for x in blocks], ["1", "2"])
        self.assertEqual(blocks[1]["answer"], "بله")

    def test_placeholder_answer_is_not_an_answer(self):
        self.assertEqual(b._valid_answer("جوابت رو همینجا بده"), "")
        self.assertEqual(b._valid_answer("بله"), "بله")

    def test_jalali_digits(self):
        self.assertTrue(any(c in "۰۱۲۳۴۵۶۷۸۹" for c in b.now_fa()))

    def test_html_warning_detection(self):
        self.assertTrue(b._looks_like_html(b"<!DOCTYPE html><html>...", "text/html"))
        self.assertFalse(b._looks_like_html(CODE_V1, "text/plain"))

    def test_kv_parser_ignores_comments(self):
        cfg = b.parse_kv("# note\nFOO = bar\nWEBAPP_URL=\n")
        self.assertEqual(cfg, {"FOO": "bar", "WEBAPP_URL": ""})


class TestManualMode(Harness):
    def test_first_detection_is_pending(self):
        result = self.core.poll_once()
        self.assertEqual(result["files"], 1)      # only .py.txt not excluded
        self.assertEqual(result["events"], 1)
        state = self.api.get_state()
        self.assertEqual(len(state["files"]), 1)
        f = state["files"][0]
        self.assertEqual(f["name"], "salam.py.txt")
        self.assertEqual(f["status"], "منتظر تایید")
        self.assertTrue(f["pending"])
        self.assertIn("salam v1", f["preview"])
        self.assertEqual(state["stats"]["pending"], 1)
        self.assertTrue(state["connected"])
        self.assertEqual(self.runs, [])          # nothing executed
        self.assertTrue((self.cache / (CODE_ID + ".py")).exists())

    def test_edit_is_detected_and_pending_again(self):
        self.core.poll_once()
        self.api.reject(CODE_ID)
        self.assertEqual(self.api.get_state()["files"][0]["status"], "رد شد")
        self.code["bytes"] = CODE_V2
        self.core.poll_once()
        f = self.api.get_state()["files"][0]
        self.assertEqual(f["status"], "منتظر تایید")
        self.assertTrue(f["pending"])
        self.assertIn("edited", f["preview"])

    def test_no_retrigger_when_unchanged(self):
        self.core.poll_once()
        self.api.reject(CODE_ID)
        r = self.core.poll_once()
        self.assertEqual(r["events"], 0)
        self.assertEqual(self.api.get_state()["files"][0]["status"], "رد شد")

    def test_approve_executes_and_logs_timing(self):
        self.core.poll_once()
        res = self.api.approve(CODE_ID)
        self.assertTrue(res["ok"])
        self.wait_runs(1)
        state = self.api.get_state()
        f = state["files"][0]
        self.assertEqual(f["status"], "اجرا شد")
        self.assertEqual(f["runs"], 1)
        self.assertEqual(f["last_exit_code"], 0)
        self.assertIn("hello from code", f["output"])
        self.assertIsInstance(f["last_duration"], int)
        log = state["logs"][0]
        self.assertEqual(log["status"], "اجرا شد")
        self.assertIsInstance(log["duration"], int)
        self.assertFalse(self.runs[0][1].get("capture_output") is False)

    def test_reject_does_not_execute(self):
        self.core.poll_once()
        self.api.reject(CODE_ID)
        self.assertEqual(self.runs, [])
        self.assertEqual(self.api.get_state()["files"][0]["status"], "رد شد")

    def test_failed_execution_is_logged(self):
        self.core.poll_once()

        class Bad:
            returncode = 2
            stdout = b""
            stderr = b"Traceback ..."
        with mock.patch.object(b.subprocess, "run", return_value=Bad()):
            self.api.approve(CODE_ID)
            self.wait_runs(1)
        f = self.api.get_state()["files"][0]
        self.assertEqual(f["status"], "خطا")
        self.assertEqual(f["last_exit_code"], 2)
        self.assertIn("Traceback", f["output"])

    def test_main_py_txt_is_excluded(self):
        self.core.poll_once()
        names = [f["name"] for f in self.api.get_state()["files"]]
        self.assertNotIn("main.py.txt", names)
        self.assertNotIn("config.txt", names)
        self.assertNotIn("dialog.txt", names)


class TestAutoMode(Harness):
    def test_auto_executes_immediately(self):
        self.api.set_auto(True)
        self.core.poll_once()
        self.wait_runs(1)
        state = self.api.get_state()
        self.assertTrue(state["auto"])
        self.assertEqual(state["files"][0]["status"], "اجرا شد")
        self.assertEqual(state["stats"]["pending"], 0)

    def test_auto_executes_edited_code_immediately(self):
        self.api.set_auto(True)
        self.core.poll_once()
        self.wait_runs(1)
        self.code["bytes"] = CODE_V2
        self.core.poll_once()
        self.wait_runs(2)
        state = self.api.get_state()
        self.assertEqual(state["files"][0]["runs"], 2)
        self.assertEqual(state["files"][0]["status"], "اجرا شد")

    def test_switch_to_auto_keeps_old_pending_items(self):
        self.core.poll_once()
        self.assertEqual(self.api.get_state()["stats"]["pending"], 1)
        self.api.set_auto(True)
        self.assertEqual(self.api.get_state()["stats"]["pending"], 1)
        self.assertEqual(self.runs, [])
        # but the NEXT new file is executed automatically
        new_id = "ABCDEFGHIJKLMNOPQRSTUVWX"
        self.entries.append(("new.py.txt", new_id))
        self.html["text"] = folder_html(self.entries)
        with mock.patch.object(b, "download_file", side_effect=lambda fid, timeout=20: (
            DIALOG_TEXT.encode() if fid == DIALOG_ID else
            b"# remote config\n" if fid == CONFIG_ID else
            CODE_V1 if fid == CODE_ID else b"print('new')\n")):
            self.core.poll_once()
        self.wait_runs(1)
        self.assertEqual(len(self.runs), 1)


class TestDialogs(Harness):
    def test_dialog_appears(self):
        self.core.poll_once()
        ds = self.api.get_state()["dialogs"]
        self.assertEqual(len(ds), 1)
        self.assertIn("ارتباط", ds[0]["question"])
        self.assertEqual(ds[0]["answer"], "")

    def test_answer_saved_locally_and_to_synced_drive(self):
        self.core.poll_once()
        res = self.api.answer_dialog("1", "بله", "تست")
        self.assertTrue(res["ok"])
        self.assertTrue(self.answer_file.exists())
        self.assertIn("answer=بله", self.answer_file.read_text(encoding="utf-8"))
        synced = self.local_drive / "dialog-answer.txt"
        self.assertTrue(synced.exists())
        self.assertEqual(self.api.get_state()["dialogs"][0]["answer"], "بله")

    def test_answer_via_webapp_when_configured(self):
        self.core.poll_once()
        self.core.cfg["WEBAPP_URL"] = "https://example.invalid/exec"
        with mock.patch.object(b._OPENER, "open") as opener:
            opener.return_value.__enter__ = mock.Mock()
            opener.return_value.__exit__ = mock.Mock()
            opener.return_value.read = mock.Mock(return_value=b"ok")
            res = self.api.answer_dialog("1", "خیر")
        self.assertIn("WEBAPP_URL", res["saved"])


class TestApiSurface(Harness):
    def test_whitelist(self):
        self.assertIn("get_state", b.API_METHODS)
        self.assertIn("set_auto", b.API_METHODS)
        self.assertNotIn("poll_once", b.API_METHODS)
        self.assertNotIn("shutdown", b.API_METHODS)

    def test_set_poll_clamps(self):
        self.assertEqual(self.api.set_poll(1)["poll_seconds"], 2)
        self.assertEqual(self.api.set_poll(999)["poll_seconds"], 120)

    def test_clear_logs(self):
        self.core.poll_once()
        self.assertTrue(self.api.get_state()["logs"])
        self.api.clear_logs()
        self.assertEqual(self.api.get_state()["logs"], [])

    def test_refresh_is_nonblocking(self):
        self.core.start()
        import time
        time.sleep(0.05)
        self.assertTrue(self.api.refresh()["ok"])

    def test_state_persists(self):
        self.core.poll_once()
        self.core.state["auto"] = True
        b.save_state(self.core.state)
        reloaded = b.load_state()
        self.assertTrue(reloaded["auto"])
        self.assertIn(CODE_ID, reloaded["files"])


class TestHttpFallback(Harness):
    def test_server_serves_ui_and_api(self):
        html = (ROOT / "ui.html").read_text(encoding="utf-8")
        with mock.patch.object(b.webbrowser, "open", return_value=True):
            thread = threading.Thread(
                target=b.run_browser_fallback, args=(self.core, html), daemon=True)
            thread.start()

        port = None
        import time
        for _ in range(100):
            for p in range(18731, 18741):
                try:
                    with urllib.request.urlopen(
                            "http://127.0.0.1:%d/" % p, timeout=0.3) as r:
                        body = r.read().decode("utf-8")
                    if "اجرای خودکار کدهای جدید" in body:
                        port = p
                        break
                except Exception:
                    pass
            if port:
                break
            time.sleep(0.05)
        self.assertIsNotNone(port, "fallback server did not start")

        def post(method, args):
            req = urllib.request.Request(
                "http://127.0.0.1:%d/api/%s" % (port, method),
                data=json.dumps({"args": args}).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status, json.loads(r.read().decode("utf-8"))

        code, state = post("get_state", [])
        self.assertEqual(code, 200)
        self.assertIn("auto", state)
        self.assertIn("files", state)

        code, res = post("set_auto", [True])
        self.assertEqual(code, 200)
        self.assertTrue(res["auto"])
        self.assertTrue(self.api.get_state()["auto"])

        code, res = post("refresh", [])
        self.assertTrue(res["ok"])

        req = urllib.request.Request(
            "http://127.0.0.1:%d/api/poll_once" % port,
            data=b'{"args": []}', headers={"Content-Type": "application/json"})
        with self.assertRaises(Exception):
            urllib.request.urlopen(req, timeout=3)

        self.core.stop_event.set()
        thread.join(timeout=3)


class TestUi(Harness):
    def test_ui_contains_design_system_and_labels(self):
        text = (ROOT / "ui.html").read_text(encoding="utf-8")
        for token in ("--accent", "--danger", "--urgent", "--due", "--done",
                      "html[data-theme='dark']", "Vazirmatn", "dir=\"rtl\"",
                      "اجرای خودکار کدهای جدید", "بله اجرا کن", "نه اجرا نکن",
                      "pywebview.api", "/api/"):
            self.assertIn(token, text, token)

    def test_launchers_exist_and_have_no_console(self):
        bat = (ROOT / "run.bat").read_text(encoding="utf-8")
        vbs = (ROOT / "run.vbs").read_text(encoding="utf-8")
        self.assertIn("run.vbs", bat)
        self.assertIn("sh.Run cmd, 0, False", vbs)
        self.assertIn("started.flag", vbs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
