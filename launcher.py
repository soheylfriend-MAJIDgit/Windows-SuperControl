# -*- coding: utf-8 -*-
"""
Windows SuperControl
====================

دو گزینه (دو تب):

  1) «دریافت و اجرا» - کد پایتون را مستقیم از گوگل درایو میگیرد، هش SHA-256
     آن را چک میکند، متن کامل کد را نشان میدهد، تایید میگیرد و جداگانه اجرا میکند.

  2) «ارسال نامه» - یک فیلد متنی. بعد از ذخیره، «استعلام» میگیرد یعنی همان
     فایل را دوباره میخواند و مقایسه میکند که درست ذخیره شده یا نه. زمان نوشتن،
     زمان استعلام، کل رفتوبرگشت و اختلافشان را اندازهگیری و گزارش میکند
     (هم توی پنجره، هم توی letters/report.csv).

هیچ اجرای خودکار، استارتآپ، سرویس یا مخفیکاریای وجود ندارد.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

# ======================== تنظیمات (اینجا تغییر بده) ========================

# --- گزینه ۱: دریافت و اجرا ---
DRIVE_FILE_ID = "11B1QGU0zuhD53sdNk_y5TAo_Qq-KkEI9"  # شناسه salam.py.txt

SOURCES = [
    "https://drive.google.com/uc?export=download&id=" + DRIVE_FILE_ID,
    "https://raw.githubusercontent.com/soheylfriend-MAJIDgit/"
    "Windows-SuperControl/arena/96bec320-windows-supercontrol/payloads/salam.py",
]
LOCAL_COPY = Path(__file__).resolve().parent / "payloads" / "salam.py"
EXPECTED_SHA256 = "f4c8f18d644017429a4aaf0aab28aba28ab6e962c9919413acce89270009213c"
CONFIRM_BEFORE_RUN = True
TIMEOUT_SECONDS = 300
MAX_BYTES = 2_000_000

# --- گزینه ۲: ارسال نامه ---
# آدرس وب اپ Apps Script را بعد از دیپلوی اینجا بچسبان (دستورش در README است)
WEBAPP_URL = ""
WEBAPP_SECRET = ""          # اختیاری؛ باید با SECRET توی Code.gs یکی باشد

LETTER_FILE_NAME = "name.txt"
DRIVE_FOLDER_NAME = "Windows-SuperControl"
# آیدی همان name.txt (برای استعلام مستقل از لینک عمومی درایو)
DRIVE_LETTER_FILE_ID = "1fzI9jceihjTmeJ4wYguWYA0EGMV3EcMP"
DRIVE_LETTER_URL = "https://drive.google.com/uc?export=download&id=" + DRIVE_LETTER_FILE_ID

LOCAL_LETTERS_DIR = Path(__file__).resolve().parent / "letters"
DRIVE_SYNC_FOLDER = os.environ.get("GOOGLE_DRIVE_SYNC_FOLDER")  # اختیاری

AUTO_SAVE_MS = 800          # ذخیره خودکار، ۰.۸ ثانیه بعد از توقف تایپ (قبلاً ۱.۲)
MAX_LETTER_CHARS = 10000
NETWORK_TIMEOUT = 8         # قبلاً ۱۵ ثانیه بود
DIRECT_CHECK_MAX_WAIT = 2.5  # حداکثر انتظار تا لینک عمومی درایو بروز شود (ثانیه)
DIRECT_CHECK_STEP = 0.35     # فاصله تلاشهای مجدد
POLL_MS = 100               # فاصله بروزرسانی وضعیت پنجره (قبلاً ۲۰۰)

# ---------------------------------------------------------------------------
USER_AGENT = "Mozilla/5.0 (Windows-SuperControl launcher)"
CACHE_DIR = Path(tempfile.gettempdir()) / "WindowsSuperControl"


# ===================== توابع مشترک =====================

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(MAX_BYTES + 1)


def _norm(text) -> str:
    """CRLF و BOM را یکدست میکند تا مقایسه درست باشد."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")


def same_text(a, b) -> bool:
    """مقایسه محتوا با چشمپوشی از CRLF و فاصلههای انتهایی."""
    return _norm(a).rstrip() == _norm(b).rstrip()


# ===================== گزینه ۱: دریافت و اجرا =====================

def looks_like_html(data: bytes) -> bool:
    head = data[:1500].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head[:400]


def get_code(log=print):
    errors = []
    for url in SOURCES:
        try:
            log("دریافت از: " + url)
            data = fetch(url)
            if not data.strip():
                raise ValueError("فایل خالی است")
            if len(data) > MAX_BYTES:
                raise ValueError("فایل بیش از حد بزرگ است")
            if looks_like_html(data):
                raise ValueError("به جای فایل، صفحه HTML دریافت شد")
            log("  تعداد بایت: %d" % len(data))
            log("  SHA-256  : " + sha256(data))
            return data, url
        except Exception as exc:
            errors.append("%s -> %s" % (url, exc))
            log("  خطا: " + str(exc))

    if LOCAL_COPY.exists():
        data = LOCAL_COPY.read_bytes()
        log("نت در دسترس نبود؛ استفاده از نسخه آفلاین: " + str(LOCAL_COPY))
        return data, "file://" + str(LOCAL_COPY)

    raise RuntimeError("هیچ منبعی در دسترس نبود:\n" + "\n".join(errors))


def verify(data: bytes):
    actual = sha256(data)
    if EXPECTED_SHA256 is None:
        return True, "چک هش غیرفعال است. SHA-256 = " + actual
    if actual.lower() == EXPECTED_SHA256.lower():
        return True, "هش تایید شد: " + actual
    return False, (
        "هش مطابقت نکرد!\n  دریافتی: " + actual +
        "\n  مورد انتظار: " + EXPECTED_SHA256 +
        "\nاجرا متوقف شد. اگر خودت فایل درایو را عوض کردهای، هش جدید را بگذار."
    )


def run_code(data: bytes) -> subprocess.CompletedProcess:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / "downloaded_code.py"
    target.write_bytes(data)
    extra = {}
    if os.name == "nt":
        extra["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        [sys.executable, str(target)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=TIMEOUT_SECONDS, cwd=str(CACHE_DIR), **extra
    )


# ===================== گزینه ۲: ذخیره + استعلام =====================

class _KeepPostRedirect(urllib.request.HTTPRedirectHandler):
    """وب اپهای گوگل ۳۰۲ میدهند؛ urllib معمولاً POST را تبدیل به GET میکند."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None or req.get_method() != "POST":
            return new
        return urllib.request.Request(
            newurl, data=req.data,
            headers={"User-Agent": USER_AGENT,
                     "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )


def _webapp_request(form: str, method: str) -> str:
    if method == "POST":
        request = urllib.request.Request(
            WEBAPP_URL, data=form.encode("utf-8"),
            headers={"User-Agent": USER_AGENT,
                     "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        opener = urllib.request.build_opener(_KeepPostRedirect())
        with opener.open(request, timeout=NETWORK_TIMEOUT) as response:
            return response.read(100000).decode("utf-8", "replace")
    separator = "&" if "?" in WEBAPP_URL else "?"
    request = urllib.request.Request(WEBAPP_URL + separator + form,
                                     headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response:
        return response.read(100000).decode("utf-8", "replace")


def check_drive_direct(expected: str, max_wait=None):
    """استعلام مستقل: فایل name.txt را مستقیم از لینک عمومی درایو میخواند.

    مدت زمانی را هم اندازه میگیرد تا مشخص شود چقدر طول کشیده محتوای جدید
    توی لینک عمومی درایو ظاهر شود (تاخیر انتشار).
    """
    if max_wait is None:
        max_wait = DIRECT_CHECK_MAX_WAIT
    started = time.perf_counter()
    deadline = started + max_wait
    attempts = 0
    last = ""
    while True:
        attempts += 1
        try:
            raw = fetch(DRIVE_LETTER_URL, timeout=min(NETWORK_TIMEOUT, 6))
            last = raw.decode("utf-8", "replace")
            if same_text(last, expected):
                return {
                    "name": "استعلام مستقیم از لینک درایو",
                    "ok": True,
                    "detail": "فایل عمومی درایو برابر شد (تلاش %d، تاخیر انتشار %.0f ms)"
                              % (attempts, (time.perf_counter() - started) * 1000),
                    "ms": (time.perf_counter() - started) * 1000,
                }
        except Exception as exc:
            last = "خطا: " + str(exc)
        if time.perf_counter() >= deadline:
            break
        time.sleep(min(DIRECT_CHECK_STEP, max(0.0, deadline - time.perf_counter())))
    return {
        "name": "استعلام مستقیم از لینک درایو",
        "ok": False,
        "detail": "محتوای درایو فرق دارد | " + _norm(last)[:90].replace("\n", " "),
        "ms": (time.perf_counter() - started) * 1000,
    }


def check_webapp_action(expected: str):
    """استعلام جداگانه از خود وب اپ (action=check) بدون اینکه چیزی بنویسد."""
    if not WEBAPP_URL:
        return {"name": "استعلام جداگانه وب اپ", "ok": False,
                "detail": "وب اپ تنظیم نشده", "ms": 0.0}
    started = time.perf_counter()
    form = urllib.parse.urlencode({
        "action": "check", "text": expected, "secret": WEBAPP_SECRET,
        "t": str(int(time.time())),
    })
    errors = []
    # POST ترجیح دارد: متنهای بلند توی URL جا نمیشوند.
    # (text همراهش فرستاده میشود تا روی نسخه قدیمی وب اپ هم بیخطر باشد.)
    for method in ("POST", "GET"):
        try:
            body = _webapp_request(form, method)
            obj = json.loads(body)
            ms = (time.perf_counter() - started) * 1000
            if obj.get("ok") and obj.get("action") == "check":
                ok = same_text(obj.get("text", ""), expected)
                return {"name": "استعلام جداگانه وب اپ", "ok": ok,
                        "detail": ("فایل درایو برابر بود" if ok else "محتوای درایو متفاوت است")
                                  + " | سرور %s ms، %s" % (obj.get("server_ms", "?"), method),
                        "ms": ms}
            if obj.get("ok"):
                # پاسخ وب اپ نسخه قدیمی: action=check را نمیشناسد
                return {"name": "استعلام جداگانه وب اپ", "ok": True, "skip": True,
                        "detail": "وب اپ نسخه قدیمی؛ action=check پشتیبانی نمیشود "
                                  "(استعلام مستقل انجام شد) - New version بده", "ms": ms}
            errors.append(method + ": " + str(obj.get("error"))[:100])
        except Exception as exc:
            errors.append(method + ": " + str(exc))
    # این استعلام تکمیلی است؛ اگر در دسترس نبود، نباید کل گزارش رو قرمز کند،
    # چون استعلام مستقل از لینک درایو جداگانه انجام شده است.
    return {"name": "استعلام جداگانه وب اپ", "ok": False, "skip": True,
            "detail": "انجام نشد (تکمیلی) : " + " | ".join(errors)[:160],
            "ms": (time.perf_counter() - started) * 1000}


def call_webapp(text: str, archive: bool = False) -> dict:
    """مینویسد و استعلام سروری میگیرد. خروجی یک دیکشنری با جزئیات زمانی."""
    if not WEBAPP_URL:
        raise RuntimeError("WEBAPP_URL خالی است")

    form = urllib.parse.urlencode({
        "text": text, "secret": WEBAPP_SECRET,
        "archive": "1" if archive else "0", "t": str(int(time.time())),
    })
    errors = []
    for method in ("POST", "GET"):
        try:
            body = _webapp_request(form, method)
            try:
                obj = json.loads(body)
            except ValueError:
                errors.append(method + ": پاسخ نامعتبر: " + body[:120].replace("\n", " "))
                continue
            if not obj.get("ok"):
                errors.append(method + ": " + str(obj.get("error")))
                continue

            legacy = obj.get("verified") is None or obj.get("echo") is None
            if legacy:
                # وب اپ نسخه قدیمی است؛ استعلام مستقل توی فاز ۲ انجام میشود
                # (اینجا انجامش نمیدهیم که دوبار کاری نشود)
                verified = None
                read_ms = 0.0
            else:
                verified = bool(obj["verified"]) and same_text(obj["echo"], text)
                read_ms = obj.get("server_read_ms", 0)

            return {
                "ok": True,
                "verified": verified,
                "legacy": legacy,
                "transport": method,
                "server_write_ms": obj.get("server_write_ms", 0),
                "server_read_ms": read_ms,
                "message": "فایل %s آپدیت شد (%s نویسه) [%s] | سرور: نوشتن %s ms / خواندن %s ms"
                           % (obj.get("file", LETTER_FILE_NAME), obj.get("chars", len(text)),
                              method, obj.get("server_write_ms", "?"),
                              obj.get("server_read_ms", "?")),
            }
        except Exception as exc:
            errors.append(method + ": " + str(exc))
    raise RuntimeError(" | ".join(errors))


_SYNC_CACHE = {"done": False, "value": None}


def find_drive_sync_folder():
    """اگر Google Drive for Desktop نصب باشد پوشه همگامشده را پیدا میکند."""
    candidates = []
    if DRIVE_SYNC_FOLDER:
        candidates += [Path(DRIVE_SYNC_FOLDER), Path(DRIVE_SYNC_FOLDER) / DRIVE_FOLDER_NAME]
    home = Path.home()
    for base in (home / "My Drive", home / "Google Drive", home / "Drive"):
        candidates += [base / DRIVE_FOLDER_NAME, base]
    if os.name == "nt":
        for letter in "GHIJKL":   # محدود شد تا اسکن درایوها کند نکند
            candidates += [Path("%s:\\My Drive" % letter) / DRIVE_FOLDER_NAME,
                           Path("%s:\\" % letter) / DRIVE_FOLDER_NAME]
    markers = ("salam.py.txt", LETTER_FILE_NAME)
    for candidate in candidates:
        try:
            if candidate.is_dir() and any((candidate / m).exists() for m in markers):
                return candidate
        except OSError:
            continue
    return None


def find_drive_sync_folder_cached():
    """نتیجه جستجو کش میشود تا هر بار ذخیره، درایوها اسکن نشوند (رفع کندی)."""
    if not _SYNC_CACHE["done"]:
        _SYNC_CACHE["value"] = find_drive_sync_folder()
        _SYNC_CACHE["done"] = True
    return _SYNC_CACHE["value"]


def save_local_letter(text: str) -> Path:
    LOCAL_LETTERS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCAL_LETTERS_DIR / LETTER_FILE_NAME
    path.write_text(text, encoding="utf-8")
    return path


def check_file(path, expected: str, name: str):
    started = time.perf_counter()
    try:
        got = path.read_text(encoding="utf-8")
        ok = same_text(got, expected)
        detail = "خوانده شد و دقیقاً برابر بود" if ok else "متفاوت است (%d نویسه)" % len(got)
    except Exception as exc:
        ok, detail = False, "خطا: " + str(exc)
    return {"name": name, "ok": ok, "detail": detail,
            "ms": (time.perf_counter() - started) * 1000}


def build_report(text, write_ms, verify_ms, total_ms, checks, deep, web) -> dict:
    effective = [c for c in checks if not c.get("skip")]
    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ok": bool(effective) and all(c["ok"] for c in effective),
        "chars": len(text),
        "write_ms": write_ms, "verify_ms": verify_ms,
        "total_ms": total_ms, "delta_ms": verify_ms - write_ms,
        "checks": checks, "deep": deep,
        "transport": web["transport"] if web else "-",
        "server_write_ms": float(web.get("server_write_ms") or 0) if web else 0.0,
        "server_read_ms": float(web.get("server_read_ms") or 0) if web else 0.0,
    }


def format_report(report: dict):
    """گزارش خوانا: زمان نوشتن، زمان استعلام، کل، و تفاوت آنها."""
    mark = "✅" if report["ok"] else "⚠️"
    head = ("%s %s | نوشتن %.0f ms | استعلام %.0f ms | کل %.0f ms | تفاوت %+.0f ms"
            % (mark, "ذخیره تایید شد" if report["ok"] else "تایید نشد",
               report["write_ms"], report["verify_ms"],
               report["total_ms"], report["delta_ms"]))
    lines = [head]
    for check in report["checks"]:
        symbol = "✅" if check["ok"] else ("➖" if check.get("skip") else "❌")
        lines.append("   %s %s: %s (%.1f ms)"
                     % (symbol, check["name"], check["detail"], check["ms"]))
    return lines


def write_report_csv(report: dict):
    """گزارشها را توی letters/report.csv ذخیره میکند (قابل باز شدن در اکسل)."""
    try:
        LOCAL_LETTERS_DIR.mkdir(parents=True, exist_ok=True)
        path = LOCAL_LETTERS_DIR / "report.csv"
        is_new = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if is_new:
                writer.writerow(["timestamp", "ok", "chars", "write_ms", "verify_ms",
                                 "total_ms", "delta_ms", "server_write_ms",
                                 "server_read_ms", "deep", "transport", "checks"])
            writer.writerow([
                report["timestamp"], int(report["ok"]), report["chars"],
                round(report["write_ms"], 2), round(report["verify_ms"], 2),
                round(report["total_ms"], 2), round(report["delta_ms"], 2),
                round(report["server_write_ms"], 2), round(report["server_read_ms"], 2),
                int(report["deep"]), report["transport"],
                " | ".join("%s=%s" % (c["name"], "OK" if c["ok"] else "FAIL")
                           for c in report["checks"]),
            ])
        return path
    except Exception:
        return None


def send_letter(text: str, archive: bool = False, deep: bool = False, progress=None):
    """ذخیره میکند، استعلام میگیرد، زمانها را حساب میکند.

    خروجی: (خطوط مربوط به نوشتن، دیکشنری گزارش)
    progress(write_ms, write_lines) بلافاصله بعد از نوشتن صدا زده میشود تا
    پنجره همان لحظه واکنش نشان بدهد (استعلام در پسزمینه ادامه پیدا میکند).
    """
    text = text[:MAX_LETTER_CHARS]
    t0 = time.perf_counter()
    write_lines = []

    # ---------- فاز ۱: نوشتن ----------
    local_path = None
    try:
        local_path = save_local_letter(text)
        write_lines.append("[نوشتن] محلی: " + str(local_path))
    except Exception as exc:
        write_lines.append("[نوشتن] محلی خطا: " + str(exc))

    sync_path = None
    sync = find_drive_sync_folder_cached()
    if sync:
        try:
            sync_path = sync / LETTER_FILE_NAME
            sync_path.write_text(text, encoding="utf-8")
            write_lines.append("[نوشتن] همگامساز: " + str(sync_path))
        except Exception as exc:
            write_lines.append("[نوشتن] همگامساز خطا: " + str(exc))

    web = None
    if WEBAPP_URL:
        try:
            web = call_webapp(text, archive=archive)
            write_lines.append("[نوشتن] درایو: " + web["message"])
        except Exception as exc:
            web = {"ok": False, "verified": False, "legacy": True, "transport": "-",
                   "server_write_ms": 0, "server_read_ms": 0,
                   "message": "خطا: " + str(exc)}
            write_lines.append("[نوشتن] درایو خطا: " + str(exc))
    else:
        write_lines.append("[نوشتن] درایو: وب اپ تنظیم نشده.")

    write_ms = (time.perf_counter() - t0) * 1000
    if progress:
        progress(write_ms, list(write_lines))

    # ---------- فاز ۲: استعلام ----------
    v0 = time.perf_counter()
    checks = []

    checks.append(check_file(local_path, text, "فایل محلی")
                  if local_path else
                  {"name": "فایل محلی", "ok": False, "detail": "نوشته نشد", "ms": 0.0})
    if sync_path:
        checks.append(check_file(sync_path, text, "همگامساز درایو"))

    # استعلام مستقل: اگر وب اپ نسخه جدید و سالم است و deep نیست،
    # همان بازخوانی سرور (داخل همان درخواست) کافی است و درخواست اضافه نمیرود.
    fast_ok = (web is not None and web.get("ok")
               and web.get("verified") is True and not web.get("legacy"))
    if deep or not fast_ok:
        direct_check = check_drive_direct(
            text, max_wait=DIRECT_CHECK_MAX_WAIT if deep else 1.2)
    else:
        direct_check = {
            "name": "استعلام مستقیم از لینک درایو", "ok": True, "skip": True,
            "detail": "انجام نشد (بازخوانی سرور کافی بود؛ برای استعلام مستقل دکمه مخصوص را بزن)",
            "ms": 0.0,
        }

    if web is not None:
        if web.get("legacy"):
            ok = bool(direct_check["ok"])
            detail = ("وب اپ نسخه قدیمی؛ استعلام مستقل از لینک درایو انجام شد. "
                      "برای سرعت بیشتر Code.gs جدید را New version کن.")
            ms = direct_check["ms"]
        else:
            ok = bool(web.get("ok") and web.get("verified"))
            detail = ("بازخوانی سرور توی همان درخواست | نوشتن %s ms، خواندن %s ms، %s"
                      % (web.get("server_write_ms"), web.get("server_read_ms"),
                         web.get("transport")))
            ms = float(web.get("server_read_ms") or 0)
        checks.append({
            "name": "استعلام درایو (وب اپ)", "ok": ok,
            "detail": ("تایید شد. " if ok else "تایید نشد! ") + detail, "ms": ms,
        })
    else:
        checks.append({"name": "استعلام درایو (وب اپ)", "ok": False,
                       "detail": "وب اپ تنظیم نشده؛ فایل درایو بروز نشد", "ms": 0.0})

    checks.append(direct_check)

    if deep:
        checks.append(check_webapp_action(text))

    verify_ms = (time.perf_counter() - v0) * 1000
    total_ms = (time.perf_counter() - t0) * 1000
    report = build_report(text, write_ms, verify_ms, total_ms, checks, deep, web)
    return write_lines, report


def verify_only() -> dict:
    """فقط استعلام میگیرد (بدون نوشتن) - برای دکمه «استعلام کامل» و --check."""
    path = LOCAL_LETTERS_DIR / LETTER_FILE_NAME
    expected = path.read_text(encoding="utf-8") if path.exists() else ""
    started = time.perf_counter()
    checks = [check_file(path, expected, "فایل محلی")] if path.exists() else [
        {"name": "فایل محلی", "ok": False, "detail": "وجود ندارد", "ms": 0.0}]
    checks.append(check_drive_direct(expected))
    checks.append(check_webapp_action(expected))
    elapsed = (time.perf_counter() - started) * 1000
    return build_report(expected, 0.0, elapsed, elapsed, checks, True, None)


# ===================== رابط کاربری =====================

def main() -> int:
    args = sys.argv[1:]

    # حالتهای بدون پنجره
    if args and args[0] == "--hash":
        path = Path(args[1]) if len(args) > 1 else LOCAL_COPY
        print(sha256(path.read_bytes()))
        return 0

    if args and args[0] == "--send":
        text = " ".join(args[1:]) if len(args) > 1 else sys.stdin.read()
        written, report = send_letter(
            text, archive=True, deep=True,
            progress=lambda ms, ls: [print("  " + line) for line in ls],
        )
        for line in format_report(report):
            print(line)
        report_path = write_report_csv(report)
        print("[گزارش] " + str(report_path))
        return 0

    if args and args[0] == "--check":
        report = verify_only()
        for line in format_report(report):
            print(line)
        print("[گزارش] " + str(write_report_csv(report)))
        return 0

    start_on_letter = any(a in ("--tab=letter", "--letter", "-l") for a in args)

    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title("Windows SuperControl")
    root.geometry("800x650")
    root.minsize(620, 480)

    book = ttk.Notebook(root)
    book.pack(fill="both", expand=True, padx=8, pady=8)
    tab_run = ttk.Frame(book, padding=10)
    tab_letter = ttk.Frame(book, padding=10)
    book.add(tab_run, text="دریافت و اجرا")
    book.add(tab_letter, text="ارسال نامه")
    if start_on_letter:
        book.select(tab_letter)

    # ---------------- تب ۱ ----------------
    ttk.Label(tab_run, text="اجراکننده کد پایتون از گوگل درایو",
              font=("Tahoma", 13, "bold")).pack(anchor="center", pady=(0, 4))
    ttk.Label(tab_run,
              text="منبع: drive.google.com  |  فایل: salam.py.txt  |  قبل از اجرا هش چک میشود",
              font=("Tahoma", 9), foreground="#555555").pack(anchor="center", pady=(0, 8))
    run_output = scrolledtext.ScrolledText(tab_run, wrap="word", font=("Consolas", 10))
    run_output.pack(fill="both", expand=True)

    def run_log(message) -> None:
        run_output.insert("end", str(message) + "\n")
        run_output.see("end")
        root.update_idletasks()

    def on_run() -> None:
        run_button.config(state="disabled")
        try:
            run_log("=== شروع ===")
            data, source = get_code(run_log)
            ok, message = verify(data)
            run_log(message)
            if not ok:
                messagebox.showerror("توقف امنیتی", message)
                return
            run_log("\n--- متن کد دریافتی ---")
            run_log(data.decode("utf-8", "replace"))
            run_log("--- پایان متن کد ---\n")
            if CONFIRM_BEFORE_RUN:
                confirmed = messagebox.askyesno(
                    "تایید اجرا",
                    "این کد روی کامپیوترتان اجرا شود؟\n\nمنبع: " + source +
                    "\nSHA-256: " + sha256(data)[:24] + "...",
                )
                if not confirmed:
                    run_log("اجرا توسط شما لغو شد.")
                    return
            run_log("در حال اجرا ... (تا %d ثانیه)" % TIMEOUT_SECONDS)
            result = run_code(data)
            run_log("--- خروجی برنامه ---")
            run_log(result.stdout.strip() or "(بدون خروجی متنی)")
            if result.stderr.strip():
                run_log("--- خطاها ---")
                run_log(result.stderr.strip())
            run_log("=== پایان - کد خروج: %s ===" % result.returncode)
        except subprocess.TimeoutExpired:
            run_log("مهلت اجرا تمام شد؛ پروسه متوقف شد.")
            messagebox.showwarning("زمان تمام شد", "کد دانلودشده بیش از حد طول کشید.")
        except Exception as exc:
            run_log("خطا: " + str(exc))
            messagebox.showerror("خطا", str(exc))
        finally:
            run_button.config(state="normal")

    run_button = ttk.Button(tab_run, text="دریافت و اجرا", command=on_run)
    run_button.pack(fill="x", pady=(10, 0))

    # ---------------- تب ۲ ----------------
    ttk.Label(tab_letter, text="ارسال نامه",
              font=("Tahoma", 13, "bold")).pack(anchor="center")
    ttk.Label(tab_letter,
              text="بعد از ذخیره، استعلام گرفته میشود و زمان نوشتن / استعلام / کل گزارش میشود.",
              font=("Tahoma", 9), foreground="#555555").pack(anchor="center", pady=(0, 8))

    letter_box = scrolledtext.ScrolledText(tab_letter, wrap="word", height=9,
                                           font=("Tahoma", 11))
    letter_box.pack(fill="both", expand=True)

    status_var = tk.StringVar(value="آماده. شروع کن به نوشتن ...")
    ttk.Label(tab_letter, textvariable=status_var, foreground="#0a7a3a",
              wraplength=720).pack(fill="x", pady=(4, 0))

    letter_log = scrolledtext.ScrolledText(tab_letter, wrap="word", height=6,
                                           font=("Consolas", 9))
    letter_log.pack(fill="x", pady=(8, 0))

    results_q = queue.Queue()
    state = {"last_text": None, "last_ok": False}

    def apply_result(item) -> None:
        kind = item[0]
        if kind == "progress":
            write_ms, write_lines = item[1], item[2]
            for line in write_lines:
                letter_log.insert("end", "  " + line + "\n")
            letter_log.see("end")
            status_var.set("نوشتن انجام شد (%.0f ms) - در حال استعلام ..." % write_ms)
        elif kind == "done":
            report, text = item[1], item[2]
            for line in format_report(report):
                letter_log.insert("end", line + "\n")
            letter_log.see("end")
            status_var.set(format_report(report)[0])
            write_report_csv(report)
            state["last_text"] = text
            state["last_ok"] = report["ok"]
        elif kind == "error":
            letter_log.insert("end", "❌ خطا: " + str(item[1]) + "\n")
            letter_log.see("end")
            status_var.set("خطا توی ارسال - جزئیات پایین ❌")
            state["last_ok"] = False

    def poll_results() -> None:
        try:
            while True:
                apply_result(results_q.get_nowait())
        except queue.Empty:
            pass
        root.after(POLL_MS, poll_results)

    def run_in_background(fn) -> None:
        def worker():
            try:
                fn()
            except Exception as exc:
                results_q.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def do_send(archive: bool = False, deep: bool = False) -> None:
        text = letter_box.get("1.0", "end-1c")
        status_var.set("در حال ذخیره ...")

        def task():
            written, report = send_letter(
                text, archive=archive, deep=deep,
                progress=lambda ms, ls: results_q.put(("progress", ms, ls)),
            )
            results_q.put(("done", report, text))

        run_in_background(task)

    def do_verify_only() -> None:
        status_var.set("در حال استعلام کامل ...")

        def task():
            report = verify_only()
            results_q.put(("done", report, letter_box.get("1.0", "end-1c")))

        run_in_background(task)

    pending = {"job": None}

    def schedule_auto_save(event=None) -> None:
        if pending["job"] is not None:
            try:
                root.after_cancel(pending["job"])
            except Exception:
                pass
        status_var.set("نوشتن ... ذخیره خودکار تا %.1f ثانیه دیگه" % (AUTO_SAVE_MS / 1000.0))

        def maybe_save():
            text = letter_box.get("1.0", "end-1c")
            # اگر متنی عوض نشده و آخرین بار تایید شده، ذخیره دوباره لازم نیست
            if text == state["last_text"] and state["last_ok"]:
                status_var.set("بدون تغییر - نیازی به ذخیره مجدد نیست ✅")
                return
            do_send(False, False)

        pending["job"] = root.after(AUTO_SAVE_MS, maybe_save)

    controls = ttk.Frame(tab_letter)
    controls.pack(fill="x", pady=(8, 0))
    ttk.Button(controls, text="استعلام کامل + گزارش",
               command=do_verify_only).pack(side="right", padx=3)
    ttk.Button(controls, text="ارسال و بایگانی",
               command=lambda: do_send(True, False)).pack(side="right", padx=3)
    ttk.Button(controls, text="حالا ذخیره کن",
               command=lambda: do_send(False, False)).pack(side="right", padx=3)

    letter_box.bind("<KeyRelease>", schedule_auto_save)

    run_log("آماده. برای گرفتن کد از اینترنت و اجرای آن، دکمه «دریافت و اجرا» را بزن.")
    run_log("هیچ کدی بهصورت خودکار اجرا نمیشود.")
    letter_log.insert("end", "آماده. بعد از هر ذخیره، استعلام + گزارش زمانی نمایش داده میشود.\n")
    root.after(POLL_MS, poll_results)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
