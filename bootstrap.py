# -*- coding: utf-8 -*-
"""
Windows SuperControl 2.0
========================

هستهٔ برنامه: یک رابط pywebview (با fallback مرورگر) که پوشهٔ گوگل درایو را
**در سطح شبکه** پایش میکند و فایلهای کد پایتونی تازه/ویرایششده را یا بلافاصله
اجرا میکند (حالت خودکار) یا در لیستی با دکمههای «بله اجرا کن / نه اجرا نکن»
نگه میدارد (حالت دستی).

نکتهای مهم: پایش از روی پوشهٔ لوکال (G:\\My Drive\\...) انجام نمیشود، بلکه از
روی لیست عمومی پوشهٔ درایو + دانلود محتوا و محاسبهٔ SHA-256 انجام میشود.

فقط از کتابخانهٔ استاندارد پایتون استفاده میشود، بجز pywebview که اختیاری است.
اگر pywebview نصب نباشد، برنامه بهصورت خودکار نصبش میکند و در صورت شکست،
رابط را با یک سرور محلی و مرورگر پیشفرض ویندوز باز میکند (باز هم بدون کنسول).
"""

from __future__ import annotations

import hashlib
import html as html_module
import http.cookiejar
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

APP_NAME = "Windows SuperControl"
VERSION = "2.0.0"

HERE = Path(__file__).resolve().parent
UI_FILE = HERE / "ui.html"

# شناسههای پوشه و فایلهای درایو (قابل تغییر در config.txt)
DRIVE_FOLDER_ID = "1PmMAu537pzN3mjKf_PYctUOlbOIQCUf1"
CONFIG_FILE_ID = "1nrCZJoXHuLXmQir9xwLrO1dEWV5OdYog"
DIALOG_FILE_ID = "10z2lb0jbThUh8kaWERYUttxudeCzX-Wf"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DEFAULTS = {
    "FOLDER_ID": DRIVE_FOLDER_ID,
    "POLL_SECONDS": "4",
    "CODE_SUFFIX": ".py.txt",
    "EXCLUDE": "main.py.txt",
    "DIALOG_FILE_ID": DIALOG_FILE_ID,
    "CONFIG_FILE_ID": CONFIG_FILE_ID,
    "WEBAPP_URL": "",
    "WEBAPP_SECRET": "",
    "LOCAL_DRIVE_PATH": r"G:\My Drive\Windows-SuperControl",
    "MAX_CODE_BYTES": "200000",
    "RUN_TIMEOUT": "60",
}

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ---------------------------------------------------------------------------
# مسیرها و لاگ
# ---------------------------------------------------------------------------
def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    p = base / "WindowsSuperControl"
    p.mkdir(parents=True, exist_ok=True)
    return p


DATA = data_dir()
STATE_FILE = DATA / "state.json"
CACHE_DIR = DATA / "cache"
LOG_FILE = DATA / "launch.log"
STARTED_FLAG = DATA / "started.flag"
ANSWER_FILE = DATA / "dialog-answer.txt"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_log_lock = threading.Lock()


def log(message: str, level: str = "info") -> None:
    """لاگ روی فایل. با pythonw ممکن است stdout وجود نداشته باشد."""
    line = "[%s] [%s] %s" % (
        datetime.now().isoformat(timespec="seconds"), level, message
    )
    with _log_lock:
        try:
            with LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception:
            pass
        try:
            if sys.stdout is not None:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# تاریخ شمسی
# ---------------------------------------------------------------------------
_MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
           "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def _fa_digits(text: str) -> str:
    return str(text).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _jalali(gy: int, gm: int, gd: int):
    gdm = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    jy = 0 if gy <= 1600 else 979
    gy2 = gy - 621 if gy <= 1600 else gy - 1600
    days = (365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100
            + (gy2 + 399) // 400 - 80 + gd
            + (gdm[gm - 1] + (6 if gm > 7 else 0)))
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm = 1 + days // 31 if days < 186 else 7 + (days - 186) // 30
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return jy, jm, jd


def now_fa(with_date: bool = True) -> str:
    d = datetime.now()
    jy, jm, jd = _jalali(d.year, d.month, d.day)
    clock = "%02d:%02d:%02d" % (d.hour, d.minute, d.second)
    if with_date:
        return _fa_digits("%04d/%02d/%02d %s" % (jy, jm, jd, clock))
    return _fa_digits(clock)


# ---------------------------------------------------------------------------
# HTTP / گوگل درایو
# ---------------------------------------------------------------------------
_COOKIE_JAR = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(
    urllib.request.HTTPRedirectHandler(),
    urllib.request.HTTPCookieProcessor(_COOKIE_JAR),
)


class DriveError(Exception):
    pass


def http_get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.6",
        "Accept": "*/*",
    })
    with _OPENER.open(req, timeout=timeout) as resp:
        return resp.read(), resp.headers.get("Content-Type", ""), resp.geturl()


def _looks_like_html(data: bytes, ctype: str = "") -> bool:
    head = data[:2048].lstrip().lower()
    if ctype.lower().startswith("text/html"):
        return True
    markers = (b"<!doctype html", b"<html", b"download_warning",
               b"virus scan", b"google drive - virus", b"<title>")
    return any(m in head for m in markers)


def _confirm_token(data: bytes) -> str:
    for pattern in (rb'name="confirm"\s+value="([^"]+)"',
                    rb'confirm=([0-9A-Za-z_\-]+)',
                    rb'"uuid"\s*:\s*"([^"]+)"'):
        m = re.search(pattern, data)
        if m:
            return m.group(1).decode("ascii", "ignore")
    return "t"


def download_file(file_id: str, timeout: int = 20) -> bytes:
    """دانلود مستقیم یک فایل از درایو. صفحات هشدار HTML را رد میکند."""
    q = urllib.parse.quote(file_id, safe="")
    url = "https://drive.google.com/uc?export=download&id=" + q
    try:
        data, ctype, _ = http_get(url, timeout)
    except Exception as exc:
        raise DriveError("خطای شبکه: %s" % exc)

    if _looks_like_html(data, ctype):
        token = _confirm_token(data)
        retry = (
            "https://drive.usercontent.google.com/download?id=%s"
            "&export=download&confirm=%s" % (q, urllib.parse.quote(token))
        )
        try:
            data, ctype, _ = http_get(retry, timeout)
        except Exception:
            pass
        if _looks_like_html(data, ctype):
            raise DriveError(
                "درایو به جای فایل، صفحهٔ HTML برگرداند "
                "(محدودیت دانلود یا اسکن ویروس). فایل را بهصورت متنی .txt ذخیره کن."
            )
    return data


def _strip_tags(fragment: str) -> str:
    txt = re.sub(r"<[^>]+>", "\n", fragment)
    return html_module.unescape(txt)


def _clean_name(text: str) -> str:
    lines = [ln.strip().strip("<>").strip() for ln in text.splitlines() if ln.strip()]
    lines = [ln for ln in lines if ln and ln not in ("Plain Text", "PDF", "Image", "Folder")]
    # نام فایل معمولاً آخرین خط داخل لینک است
    for ln in reversed(lines):
        if re.search(r"\.[A-Za-z0-9]{1,8}$", ln) and len(ln) < 200:
            return ln
    return lines[-1] if lines else ""


def parse_folder_html(raw_html: str):
    """
    پارس لیست embeddedfolderview. چند استراتژی مختلف چون گوگل گاهی ساختار
    HTML را عوض میکند. خروجی: [{id, name, modified}]
    """
    found = OrderedDict()

    # استراتژی ۱: لینک /file/d/<id>/view + متن داخل <a>
    for m in re.finditer(
        r'href="[^"]*?/file/d/([A-Za-z0-9_\-]{10,})/view[^"]*"\s*>?', raw_html, re.I
    ):
        fid = m.group(1)
        tail = raw_html[m.end(): m.end() + 4000]
        end = tail.lower().find("</a>")
        inner = tail[:end] if end != -1 else tail[:600]
        name = _clean_name(_strip_tags(inner))
        if name:
            found.setdefault(fid, {"id": fid, "name": name, "modified": ""})

    # استراتژی ۲ و ۳: data-id / data-title (به هر ترتیبی)
    for m in re.finditer(
        r'data-id="([A-Za-z0-9_\-]{10,})"[^>]{0,800}?data-title="([^"]+)"', raw_html, re.I
    ):
        found.setdefault(m.group(1), {
            "id": m.group(1), "name": html_module.unescape(m.group(2)), "modified": ""
        })
    for m in re.finditer(
        r'data-title="([^"]+)"[^>]{0,800}?data-id="([A-Za-z0-9_\-]{10,})"', raw_html, re.I
    ):
        found.setdefault(m.group(2), {
            "id": m.group(2), "name": html_module.unescape(m.group(1)), "modified": ""
        })

    # استراتژی ۴: id="entry-<id>" با title
    for m in re.finditer(
        r'id="entry-([A-Za-z0-9_\-]{10,})"[^>]{0,500}?title="([^"]+)"', raw_html, re.I
    ):
        found.setdefault(m.group(1), {
            "id": m.group(1), "name": html_module.unescape(m.group(2)), "modified": ""
        })

    # استراتژی ۵: فقط لینکها (بدون نام) — نام بعداً از بلوکها پر میشود
    for m in re.finditer(r'/file/d/([A-Za-z0-9_\-]{10,})/view', raw_html, re.I):
        found.setdefault(m.group(1), {"id": m.group(1), "name": "", "modified": ""})
    for m in re.finditer(r'/(?:open|uc)\?id=([A-Za-z0-9_\-]{10,})', raw_html, re.I):
        found.setdefault(m.group(1), {"id": m.group(1), "name": "", "modified": ""})

    # استراتژی ۶: بلوکهای flip-entry. گوگل گاهی نام را داخل
    # <div class="flip-entry-title"> میگذارد نه توی data-title.
    for block in re.split(r'(?i)(?=<div[^>]*class=["\'][^"\']*flip-entry["\'])', raw_html):
        mid = (re.search(r'data-id="([A-Za-z0-9_\-]{10,})"', block, re.I)
               or re.search(r'/file/d/([A-Za-z0-9_\-]{10,})/view', block, re.I)
               or re.search(r'/(?:open|uc)\?id=([A-Za-z0-9_\-]{10,})', block, re.I)
               or re.search(r'id="entry-([A-Za-z0-9_\-]{10,})"', block, re.I))
        if not mid:
            continue
        fid = mid.group(1)
        mt = re.search(
            r'class=["\'][^"\']*flip-entry-title[^"\']*["\'][^>]*>(.*?)</(?:div|span|a)>',
            block, re.I | re.S)
        name = _clean_name(_strip_tags(mt.group(1))) if mt else ""
        if not name:
            ma = re.search(r'<a[^>]+>(.*?)</a>', block, re.I | re.S)
            if ma:
                name = _clean_name(_strip_tags(ma.group(1)))
        if name:
            item = found.setdefault(fid, {"id": fid, "name": "", "modified": ""})
            if not item["name"]:
                item["name"] = name

    # زمانهای کوتاه «3:22 pm» را به ترتیب به ورودیها میچسبانیم (فقط نمایشی)
    times = re.findall(r"(\d{1,2}:\d{2}\s*(?:am|pm)?)", raw_html, re.I)
    for i, entry in enumerate(found.values()):
        if i < len(times):
            entry["modified"] = times[i]

    return [e for e in found.values() if e["name"] or e["id"]]


def list_folder(folder_id: str):
    url = ("https://drive.google.com/embeddedfolderview?id=%s#list"
           % urllib.parse.quote(folder_id, safe=""))
    data, _, _ = http_get(url, 20)
    return parse_folder_html(data.decode("utf-8", "replace"))


# ---------------------------------------------------------------------------
# تنظیمات
# ---------------------------------------------------------------------------
def parse_kv(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip().upper()] = value.strip()
    return out


def load_config() -> dict:
    """اولویت: config.txt لوکال → config.txt درایو → مقادیر پیشفرض."""
    cfg = dict(DEFAULTS)
    local_found = False
    for candidate in (HERE / "config.txt", DATA / "config.txt"):
        try:
            if candidate.exists():
                cfg.update(parse_kv(candidate.read_text(encoding="utf-8", errors="replace")))
                log("config loaded from %s" % candidate)
                local_found = True
                break
        except Exception as exc:
            log("config local read error: %s" % exc, "warn")

    remote_id = cfg.get("CONFIG_FILE_ID", CONFIG_FILE_ID)
    if remote_id and not local_found:
        try:
            remote = parse_kv(download_file(remote_id, 12).decode("utf-8", "replace"))
            for key, value in remote.items():
                if key in DEFAULTS and value:
                    cfg[key] = value
            log("remote config keys: %s" % ", ".join(sorted(remote)))
        except Exception as exc:
            log("remote config unavailable: %s" % exc, "warn")
    return cfg


# ---------------------------------------------------------------------------
# وضعیت پایدار
# ---------------------------------------------------------------------------
DEFAULT_STATE = {
    "version": 2,
    "auto": False,
    "poll_seconds": 4,
    "connected": False,
    "last_check": "",
    "files": {},
    "dialogs": {},
    "logs": [],
}

_state_lock = threading.RLock()


def load_state() -> dict:
    state = json.loads(json.dumps(DEFAULT_STATE))
    try:
        if STATE_FILE.exists():
            saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for key in DEFAULT_STATE:
                    if key in saved:
                        state[key] = saved[key]
    except Exception as exc:
        log("state read error: %s" % exc, "warn")
    return state


def save_state(state: dict) -> None:
    try:
        with _state_lock:
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(STATE_FILE)
    except Exception as exc:
        log("state write error: %s" % exc, "warn")


# ---------------------------------------------------------------------------
# دیالوگها
# ---------------------------------------------------------------------------
_ANSWER_OK = {"بله", "آره", "اره", "yes", "y", "true", "1", "خیر", "نه", "no", "n", "false", "0"}


def parse_dialogs(text: str):
    """چند پیام پشت سر هم را با شروع دوبارهٔ id= جدا میکند."""
    blocks, current = [], None
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or line.startswith("---"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip().lower(), value.strip()
        if key == "id":
            if current:
                blocks.append(current)
            current = {"id": value or str(len(blocks) + 1)}
            continue
        if current is None:
            current = {"id": "1"}
        current[key] = value
    if current:
        blocks.append(current)
    return blocks


def _valid_answer(value: str) -> str:
    v = (value or "").strip()
    if v.lower() in _ANSWER_OK and len(v) <= 12:
        return v
    return ""


# ---------------------------------------------------------------------------
# هستهٔ منطقی
# ---------------------------------------------------------------------------
class Core:
    def __init__(self):
        self.cfg = load_config()
        self.state = load_state()
        try:
            self.state["poll_seconds"] = max(2, int(self.cfg.get("POLL_SECONDS", "4")))
        except ValueError:
            self.state["poll_seconds"] = 4
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="wsc")
        self.monitor_thread = None

    # ---------- چرخهٔ حیات ----------
    def start(self):
        self.monitor_thread = threading.Thread(target=self._loop, daemon=True,
                                               name="wsc-monitor")
        self.monitor_thread.start()
        self.wake.set()   # اولین بررسی بلافاصله

    def shutdown(self):
        self.stop_event.set()
        self.wake.set()
        save_state(self.state)
        try:
            self.pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self.pool.shutdown(wait=False)

    def _loop(self):
        while not self.stop_event.is_set():
            self.wake.clear()
            try:
                self.poll_once()
            except Exception as exc:
                log("poll error: %s" % exc, "error")
                with self.lock:
                    self.state["connected"] = False
                save_state(self.state)
            self.wake.wait(max(2, int(self.state.get("poll_seconds", 4))))
            self.wake.clear()

    # ---------- ابزارها ----------
    def _add_log(self, event, filename, status, detail="", duration=None):
        with self.lock:
            self.state["logs"].append({
                "time": now_fa(), "event": event, "file": filename or "—",
                "status": status, "detail": str(detail)[:800], "duration": duration,
            })
            if len(self.state["logs"]) > 500:
                self.state["logs"] = self.state["logs"][-500:]
        log("%s | %s | %s%s" % (event, filename, status,
                                (" | %sms" % duration) if duration is not None else ""))

    def _cache_path(self, file_id):
        # نام امن: فقط شناسهٔ فایل درایو، بدون نام کاربر
        return CACHE_DIR / ("%s.py" % re.sub(r"[^A-Za-z0-9_\-]", "_", file_id))

    def _python_exe(self):
        exe = sys.executable
        if os.name == "nt" and "pythonw" in exe.lower():
            cand = re.sub(r"pythonw(\.exe)?$", r"python\1", exe, flags=re.I)
            if Path(cand).exists():
                return cand
        return exe

    def _max_bytes(self):
        try:
            return int(self.cfg.get("MAX_CODE_BYTES", "200000"))
        except ValueError:
            return 200000

    def _timeout(self):
        try:
            return max(2, int(self.cfg.get("RUN_TIMEOUT", "60")))
        except ValueError:
            return 60

    # ---------- پایش ----------
    def poll_once(self):
        folder_id = self.cfg.get("FOLDER_ID", DRIVE_FOLDER_ID)
        entries = list_folder(folder_id)
        if not entries:
            raise DriveError("لیست پوشه خالی برگشت (دسترسی پوشه را چک کن)")

        with self.lock:
            self.state["connected"] = True
            self.state["last_check"] = now_fa()

        suffix = self.cfg.get("CODE_SUFFIX", ".py.txt").lower()
        excludes = [x.strip() for x in
                    self.cfg.get("EXCLUDE", "main.py.txt").replace(";", ",").split(",")
                    if x.strip()]

        # فقط فایلهای کد پایتونی؛ config/name/dialog/Code.gs مستثنا هستند
        candidates = []
        for e in entries:
            name = e.get("name") or ""
            if not name.lower().endswith(suffix):
                continue
            if name in excludes:
                continue
            candidates.append(e)

        def fetch(entry):
            try:
                return entry["id"], download_file(entry["id"], 20), None
            except Exception as exc:
                return entry["id"], None, str(exc)

        contents = {}
        if candidates:
            for fid, data, err in self.pool.map(fetch, candidates):
                if data is None:
                    log("download failed %s: %s" % (fid, err), "warn")
                else:
                    contents[fid] = data

        events = []
        by_id = {e["id"]: e for e in candidates}
        with self.lock:
            files = self.state["files"]
            for fid, data in contents.items():
                if len(data) > self._max_bytes():
                    log("skip oversized %s (%d bytes)" % (by_id[fid]["name"], len(data)), "warn")
                    continue
                digest = hashlib.sha256(data).hexdigest()
                name = by_id[fid]["name"]
                prev = files.get(fid)
                if prev is None:
                    entry = self._new_file_entry(fid, name, digest, len(data),
                                                 by_id[fid].get("modified", ""))
                    files[fid] = entry
                    self._cache_path(fid).write_bytes(data)
                    events.append((fid, "جدید"))
                elif prev.get("hash") != digest:
                    prev["hash"] = digest
                    prev["name"] = name
                    prev["size"] = len(data)
                    prev["last_changed"] = now_fa()
                    prev["modified"] = by_id[fid].get("modified", "")
                    prev["deleted"] = False
                    prev["status"] = "تغییر کرده"
                    self._cache_path(fid).write_bytes(data)
                    events.append((fid, "تغییر کرده"))
                elif prev.get("deleted") or prev.get("status") == "حذف شده":
                    # فایل دوباره در پوشه ظاهر شده است
                    prev["name"] = name
                    prev["deleted"] = False
                    prev["status"] = "جدید"
                    events.append((fid, "جدید"))
                else:
                    prev["name"] = name
                    prev["deleted"] = False

            seen = set(by_id)
            for fid, item in files.items():
                if fid not in seen and not item.get("deleted"):
                    item["deleted"] = True
                    item["pending"] = False
                    item["status"] = "حذف شده"
                    self._add_log("حذف فایل", item["name"], "بدون تغییر",
                                  "فایل دیگر در پوشهٔ درایو دیده نشد")

        # دیالوگها (جدا از کدها؛ خرابی آنها نباید پایش کد را متوقف کند)
        try:
            self.poll_dialogs()
        except Exception as exc:
            log("dialog poll error: %s" % exc, "warn")

        auto = bool(self.state.get("auto"))
        for fid, kind in events:
            with self.lock:
                item = self.state["files"].get(fid)
                if item is None:
                    continue
                name = item["name"]
                digest = item["hash"][:16]
                if auto:
                    item["pending"] = False
                else:
                    item["pending"] = True
                    item["status"] = "منتظر تایید"
            self._add_log("تشخیص کد (%s)" % ("خودکار" if auto else "دستی"),
                          name, "در حال اجرا" if auto else "منتظر تایید",
                          "SHA-256: %s…" % digest)
            if auto:
                self.execute(fid)

        save_state(self.state)
        return {"files": len(candidates), "events": len(events)}

    def _new_file_entry(self, fid, name, digest, size, modified):
        stamp = now_fa()
        return {
            "id": fid, "name": name, "hash": digest, "size": size,
            "modified": modified, "first_seen": stamp, "last_changed": stamp,
            "status": "جدید", "pending": False, "running": False, "deleted": False,
            "runs": 0, "last_duration": None, "last_exit_code": None, "output": "",
        }

    # ---------- اجرای کد ----------
    def execute(self, file_id: str):
        path = self._cache_path(file_id)
        with self.lock:
            item = self.state["files"].get(file_id)
            if item is None:
                return {"ok": False, "msg": "فایل پیدا نشد"}
            if item.get("running"):
                return {"ok": False, "msg": "در حال اجراست"}
            if not path.exists():
                return {"ok": False, "msg": "کد کش نشده است"}
            item["running"] = True
            item["pending"] = False
            item["status"] = "در حال اجرا"
            name = item["name"]
        save_state(self.state)

        def task():
            t0 = time.perf_counter()
            ok, code, out = False, None, ""
            try:
                proc = subprocess.run(
                    [self._python_exe(), "-u", str(path)],
                    cwd=str(CACHE_DIR), capture_output=True,
                    timeout=self._timeout(),
                    creationflags=CREATE_NO_WINDOW,
                )
                code = proc.returncode
                out = (proc.stdout + proc.stderr).decode("utf-8", "replace").strip()
                ok = code == 0
                if not out:
                    out = "بدون خروجی متنی (کد با موفقیت پایان یافت)."
            except subprocess.TimeoutExpired:
                out = "مهلت اجرا (%d ثانیه) تمام شد؛ پردازش متوقف شد." % self._timeout()
            except Exception as exc:
                out = "خطای اجرا: %s" % exc
            duration = int((time.perf_counter() - t0) * 1000)
            with self.lock:
                item = self.state["files"].get(file_id)
                if item is not None:
                    item["running"] = False
                    item["runs"] = int(item.get("runs") or 0) + 1
                    item["last_duration"] = duration
                    item["last_exit_code"] = code
                    item["output"] = out[:1200]
                    item["status"] = "اجرا شد" if ok else "خطا"
            self._add_log("اجرای کد", name,
                          "اجرا شد" if ok else "خطا", out[:500], duration)
            save_state(self.state)

        self.pool.submit(task)
        return {"ok": True, "msg": "اجرا شروع شد"}

    # ---------- دیالوگها ----------
    def poll_dialogs(self):
        did = self.cfg.get("DIALOG_FILE_ID", DIALOG_FILE_ID)
        if not did:
            return
        text = download_file(did, 15).decode("utf-8", "replace")
        blocks = parse_dialogs(text)
        changed = False
        with self.lock:
            known = self.state["dialogs"]
            for block in blocks:
                key = block.get("id") or "1"
                cur = known.get(key)
                answer = _valid_answer(block.get("answer", ""))
                if cur is None:
                    known[key] = {
                        "id": key,
                        "question": block.get("question", "پیام جدید"),
                        "from": block.get("from", "Arena Agent"),
                        "type": block.get("type", "yesno"),
                        "note": block.get("note", ""),
                        "answer": answer,
                        "time": block.get("time") or now_fa(),
                        "answer_time": "",
                    }
                    changed = True
                else:
                    for field in ("question", "from", "type", "note"):
                        if block.get(field) and cur.get(field) != block[field]:
                            cur[field] = block[field]
                            changed = True
                    if answer and not cur.get("answer"):
                        cur["answer"] = answer
                        changed = True
        if changed:
            self._add_log("پیام جدید درایو", "dialog.txt", "منتظر تایید",
                          "%d پیام" % len(blocks))
            save_state(self.state)

    def answer_dialog(self, dialog_id: str, answer: str, note: str = ""):
        with self.lock:
            dlg = self.state["dialogs"].get(str(dialog_id))
            if dlg is None:
                return {"ok": False, "msg": "پیام پیدا نشد"}
            dlg["answer"] = answer
            dlg["answer_time"] = now_fa()
            dlg["answer_note"] = note
            question = dlg.get("question", "")

        payload = (
            "id=%s\nfrom=Windows SuperControl (pywebview)\n"
            "question=%s\nanswer=%s\nnote=%s\ntime=%s\n"
            % (dialog_id, question, answer, note or "—", now_fa())
        )
        saved = []
        try:
            ANSWER_FILE.write_text(payload, encoding="utf-8")
            saved.append(str(ANSWER_FILE))
        except Exception as exc:
            log("answer local write error: %s" % exc, "warn")

        # اگر پوشهٔ همگامسازی Drive for Desktop وجود داشته باشد، پاسخ آنجا
        # هم نوشته میشود تا مستقیماً به درایو برسد (بدون نیاز به Apps Script).
        local = self.cfg.get("LOCAL_DRIVE_PATH", "")
        if local:
            try:
                folder = Path(local)
                if folder.is_dir():
                    target = folder / "dialog-answer.txt"
                    target.write_text(payload, encoding="utf-8")
                    saved.append(str(target))
            except Exception as exc:
                log("answer drive write error: %s" % exc, "warn")

        webapp = self.cfg.get("WEBAPP_URL", "").strip()
        if webapp:
            try:
                body = json.dumps({
                    "secret": self.cfg.get("WEBAPP_SECRET", ""),
                    "action": "write_dialog_answer",
                    "id": str(dialog_id), "answer": answer, "note": note,
                }).encode("utf-8")
                req = urllib.request.Request(
                    webapp, data=body,
                    headers={"Content-Type": "application/json", "User-Agent": UA},
                )
                with _OPENER.open(req, timeout=15) as resp:
                    resp.read()
                saved.append("WEBAPP_URL")
            except Exception as exc:
                log("answer webapp error: %s" % exc, "warn")

        self._add_log("پاسخ دیالوگ", "dialog.txt", "اجرا شد",
                      "پاسخ «%s» ذخیره شد در: %s" % (answer, " | ".join(saved) or "هیچکجا"))
        save_state(self.state)
        return {"ok": True, "saved": saved,
                "msg": "پاسخ ذخیره شد" if saved else "پاسخ ذخیره نشد!"}

    # ---------- API ----------
    def get_state(self):
        with self.lock:
            files = [dict(v) for v in self.state["files"].values()]
            dialogs = [dict(v) for v in self.state["dialogs"].values()]
            logs = list(reversed(self.state["logs"]))[:200]
            auto = bool(self.state.get("auto"))
            connected = bool(self.state.get("connected"))
            last_check = self.state.get("last_check", "")
            poll_seconds = int(self.state.get("poll_seconds", 4))
        files.sort(key=lambda f: f.get("first_seen", ""), reverse=True)
        dialogs.sort(key=lambda d: str(d.get("id", "")))

        for f in files:
            try:
                path = self._cache_path(f["id"])
                if path.exists():
                    f["preview"] = path.read_text(encoding="utf-8", errors="replace")[:2500]
                else:
                    f["preview"] = "(کد کش نشده است)"
            except Exception as exc:
                f["preview"] = "(خطا در خواندن کد: %s)" % exc

        return {
            "version": VERSION,
            "auto": auto,
            "poll_seconds": poll_seconds,
            "connected": connected,
            "last_check": last_check,
            "webapp_configured": bool(self.cfg.get("WEBAPP_URL", "").strip()),
            "folder_id": self.cfg.get("FOLDER_ID", DRIVE_FOLDER_ID),
            "stats": {
                "files": len([f for f in files if not f.get("deleted")]),
                "pending": len([f for f in files if f.get("pending")]),
                "runs": sum(int(f.get("runs") or 0) for f in files),
                "errors": len([l for l in logs if l.get("status") == "خطا"]),
            },
            "files": files,
            "dialogs": dialogs,
            "logs": logs,
        }

    def set_auto(self, value):
        value = bool(value)
        with self.lock:
            old = bool(self.state.get("auto"))
            self.state["auto"] = value
            pending = len([f for f in self.state["files"].values() if f.get("pending")])
        self._add_log("تغییر حالت", "—", "اجرا شد",
                      "حالت %s فعال شد. %d مورد قبلی همچنان منتظر تأییدند."
                      % ("خودکار" if value else "دستی", pending))
        save_state(self.state)
        return {"ok": True, "auto": value, "was": old}

    def set_poll(self, seconds):
        seconds = max(2, min(120, int(seconds)))
        with self.lock:
            self.state["poll_seconds"] = seconds
        self.wake.set()
        save_state(self.state)
        return {"ok": True, "poll_seconds": seconds}

    def refresh(self):
        self.wake.set()
        return {"ok": True, "msg": "بررسی درایو شروع شد"}

    def approve(self, file_id):
        return self.execute(file_id)

    def reject(self, file_id):
        with self.lock:
            item = self.state["files"].get(file_id)
            if item is None:
                return {"ok": False, "msg": "فایل پیدا نشد"}
            item["pending"] = False
            item["status"] = "رد شد"
            name = item["name"]
        self._add_log("رد اجرا", name, "رد شد", "کاربر دکمهٔ «نه اجرا نکن» را زد")
        save_state(self.state)
        return {"ok": True}

    def run_again(self, file_id):
        return self.execute(file_id)

    def open_folder(self):
        url = "https://drive.google.com/drive/folders/%s" % self.cfg.get(
            "FOLDER_ID", DRIVE_FOLDER_ID)
        try:
            webbrowser.open(url)
        except Exception as exc:
            log("browser open error: %s" % exc, "warn")
        return {"ok": True, "url": url}

    def clear_logs(self):
        with self.lock:
            self.state["logs"] = []
        save_state(self.state)
        return {"ok": True}


# ---------------------------------------------------------------------------
# لایهٔ API (فقط متدهای مجاز در معرض جاوااسکریپت قرار میگیرند)
# ---------------------------------------------------------------------------
class Api:
    def __init__(self, core: Core):
        self.core = core

    def get_state(self):        return self.core.get_state()
    def set_auto(self, value):  return self.core.set_auto(value)
    def set_poll(self, n):      return self.core.set_poll(n)
    def refresh(self):          return self.core.refresh()
    def approve(self, fid):     return self.core.approve(fid)
    def reject(self, fid):      return self.core.reject(fid)
    def run_again(self, fid):   return self.core.run_again(fid)
    def answer_dialog(self, did, answer, note=""):
        return self.core.answer_dialog(did, answer, note)
    def open_folder(self):      return self.core.open_folder()
    def clear_logs(self):       return self.core.clear_logs()


API_METHODS = {name for name in dir(Api) if not name.startswith("_")
               and callable(getattr(Api, name))}


# ---------------------------------------------------------------------------
# fallback: سرور محلی + مرورگر (وقتی pywebview در دسترس نباشد)
# ---------------------------------------------------------------------------
def run_browser_fallback(core: Core, html: str):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    api = Api(core)
    # ضربان قلب: رابط هر ثانیه get_state میگیرد. اگر ۴۵ ثانیه هیچ تماسی
    # نیامد یعنی تب مرورگر بسته شده → برنامه تمیز خارج میشود.
    heartbeat = {"last": time.time()}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, code, body: bytes, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            heartbeat["last"] = time.time()
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html", "/ui.html"):
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/favicon.ico":
                self._send(204, b"", "image/x-icon")
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

        def do_POST(self):
            heartbeat["last"] = time.time()
            if not self.path.startswith("/api/"):
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            method = self.path[5:].split("?", 1)[0]
            if method not in API_METHODS:
                self._send(404, b"unknown method", "text/plain; charset=utf-8")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                args = payload.get("args", [])
                result = getattr(api, method)(*args)
                body = json.dumps(result, ensure_ascii=False,
                                  default=str).encode("utf-8")
                self._send(200, body, "application/json; charset=utf-8")
            except Exception as exc:
                log("api %s error: %s" % (method, exc), "error")
                body = json.dumps({"ok": False, "error": str(exc)},
                                  ensure_ascii=False).encode("utf-8")
                self._send(500, body, "application/json; charset=utf-8")

    for port in range(18731, 18741):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    else:
        log("no free port for browser fallback", "error")
        return

    url = "http://127.0.0.1:%d/" % port
    log("browser fallback at %s" % url)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        webbrowser.open(url)
    except Exception as exc:
        log("webbrowser error: %s" % exc, "warn")
    try:
        while (not core.stop_event.is_set()
               and time.time() - heartbeat["last"] < 45):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        log("browser fallback stopping (tab closed or shutdown)")
        server.shutdown()


# ---------------------------------------------------------------------------
# pywebview
# ---------------------------------------------------------------------------
def ensure_pywebview():
    try:
        import webview
        return webview
    except Exception as exc:
        log("pywebview import failed: %s" % exc, "warn")

    if os.environ.get("WSC_SKIP_PIP") == "1":
        return None
    try:
        log("trying to install pywebview ...")
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--user",
             "--disable-pip-version-check", "--quiet", "pywebview"],
            capture_output=True, timeout=240, creationflags=CREATE_NO_WINDOW,
        )
        log("pip exit=%s stderr=%s" % (
            proc.returncode,
            (proc.stderr or b"").decode("utf-8", "replace")[-500:]))
    except Exception as exc:
        log("pip install failed: %s" % exc, "warn")

    import importlib
    importlib.invalidate_caches()
    try:
        import webview
        return webview
    except Exception as exc:
        log("pywebview still unavailable: %s" % exc, "warn")
        return None


def diagnose(core: Core):
    """چاپ وضعیت شبکه/درایو برای حالت diagnose در run.bat."""
    print("Windows SuperControl %s — diagnose" % VERSION)
    print("data dir:", DATA)
    print("log file:", LOG_FILE)
    print("folder id:", core.cfg.get("FOLDER_ID"))
    try:
        entries = list_folder(core.cfg.get("FOLDER_ID", DRIVE_FOLDER_ID))
        print("folder entries:", len(entries))
        for e in entries:
            print("  -", e["name"] or "(unnamed)", e["id"], e.get("modified", ""))
    except Exception as exc:
        print("FOLDER LIST ERROR:", exc)
    try:
        b = download_file(core.cfg.get("CONFIG_FILE_ID", CONFIG_FILE_ID))
        print("config download: OK (%d bytes)" % len(b))
    except Exception as exc:
        print("CONFIG ERROR:", exc)
    import importlib.util
    print("pywebview:", "OK" if importlib.util.find_spec("webview")
          else "MISSING (browser fallback / auto-install on next run)")
    print("API methods:", ", ".join(sorted(API_METHODS)))
    print("done. full log:", LOG_FILE)


def main():
    try:
        STARTED_FLAG.write_text(datetime.now().isoformat(), encoding="utf-8")
    except Exception:
        pass
    log("=== %s %s starting (pid=%s) ===" % (APP_NAME, VERSION, os.getpid()))

    core = Core()
    if "--diagnose" in sys.argv:
        diagnose(core)
        return
    core.start()

    try:
        html = UI_FILE.read_text(encoding="utf-8")
    except Exception as exc:
        log("ui.html missing: %s" % exc, "error")
        html = ("<html dir=rtl><body style='font-family:tahoma;padding:30px'>"
                "<h2>ui.html پیدا نشد</h2><p>فایل ui.html کنار bootstrap.py بگذار.</p>"
                "</body></html>")

    wv = ensure_pywebview()
    if wv is not None:
        try:
            wv.create_window(
                APP_NAME, html=html, js_api=Api(core),
                width=1120, height=780, min_size=(720, 520),
                background_color="#161511", text_select=True,
            )
            log("pywebview window created")
            wv.start()           # بلاک میشود تا پنجره بسته شود
            log("pywebview window closed")
            core.shutdown()
            return
        except Exception as exc:
            log("pywebview failed, switching to browser: %s" % exc, "error")

    run_browser_fallback(core, html)
    core.shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("FATAL: %s" % exc, "error")
        import traceback
        log(traceback.format_exc(), "error")
        if os.name == "nt":
            try:
                import ctypes
                ctypes.windll.user32.MessageBoxW(
                    0, "خطا در اجرای Windows SuperControl:\n%s\n\nلاگ:\n%s"
                    % (exc, LOG_FILE), "Windows SuperControl", 0x10)
            except Exception:
                pass
