# -*- coding: utf-8 -*-
"""
Windows SuperControl
====================

دو گزینه (دو تب):

  1) «دریافت و اجرا» - کد پایتون را مستقیم از گوگل درایو میگیرد، هش SHA-256
     آن را چک میکند، متن کامل کد را نشان میدهد، تایید میگیرد و در یک پروسه
     جداگانه اجرا میکند.

  2) «ارسال نامه» - یک فیلد متنی. هر چه بنویسید بهصورت زنده (آنی) در فایل
     name.txt ذخیره میشود. سه مسیر پشت سر هم امتحان میشوند:
        الف) همیشه: فایل محلی letters/name.txt
        ب) اگر Google Drive for Desktop نصب باشد: پوشه همگامسازی شده
        ج) اگر WEBAPP_URL تنظیم شده باشد: وب اپ Apps Script -> همان پوشه درایو

هیچ اجرای خودکار، استارتآپ، سرویس یا مخفیکاریای وجود ندارد.
"""

from __future__ import annotations

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
# مثال: "https://script.google.com/macros/s/AKfycb..../exec"
WEBAPP_URL = ""
WEBAPP_SECRET = ""          # اختیاری؛ باید با SECRET توی Code.gs یکی باشد

LETTER_FILE_NAME = "name.txt"
DRIVE_FOLDER_NAME = "Windows-SuperControl"
LOCAL_LETTERS_DIR = Path(__file__).resolve().parent / "letters"
DRIVE_SYNC_FOLDER = os.environ.get("GOOGLE_DRIVE_SYNC_FOLDER")  # اختیاری
AUTO_SAVE_MS = 1200         # ذخیره خودکار، ۱.۲ ثانیه بعد از توقف تایپ
MAX_LETTER_CHARS = 10000
NETWORK_TIMEOUT = 15

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


# ===================== گزینه ۱: دریافت و اجرا =====================

def looks_like_html(data: bytes) -> bool:
    head = data[:1500].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head[:400]


def get_code(log=print):
    """اولین منبع سالم را برمیگرداند: (بایتهای کد، آدرس منبع)."""
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
        log("  SHA-256  : " + sha256(data))
        return data, "file://" + str(LOCAL_COPY)

    raise RuntimeError("هیچ منبعی در دسترس نبود:\n" + "\n".join(errors))


def verify(data: bytes):
    actual = sha256(data)
    if EXPECTED_SHA256 is None:
        return True, "چک هش غیرفعال است. SHA-256 = " + actual
    if actual.lower() == EXPECTED_SHA256.lower():
        return True, "هش تایید شد: " + actual
    return False, (
        "هش مطابقت نکرد!\n"
        "  دریافتی: " + actual + "\n"
        "  مورد انتظار: " + EXPECTED_SHA256 + "\n"
        "اجرا متوقف شد. اگر خودت فایل درایو را عوض کردهای، هش جدید را "
        "در EXPECTED_SHA256 بگذار."
    )


def run_code(data: bytes) -> subprocess.CompletedProcess:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / "downloaded_code.py"
    target.write_bytes(data)

    extra = {}
    if os.name == "nt":
        # فقط جلوی کنسول اضافه را میگیرد؛ خود کد کاملاً قابل دیدن است
        extra["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    return subprocess.run(
        [sys.executable, str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_SECONDS,
        cwd=str(CACHE_DIR),
        **extra
    )


# ===================== گزینه ۲: ارسال نامه =====================

class _KeepPostRedirect(urllib.request.HTTPRedirectHandler):
    """وب اپهای گوگل ۳۰۲ میدهند؛ urllib معمولاً POST را به GET تبدیل میکند.

    این هندلر متد و بدنه درخواست را بعد از ریدایرکت حفظ میکند.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None or req.get_method() != "POST":
            return new
        return urllib.request.Request(
            newurl,
            data=req.data,
            headers={"User-Agent": USER_AGENT,
                     "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )


def _parse_webapp_reply(body: str):
    try:
        obj = json.loads(body)
    except ValueError:
        return False, "پاسخ نامعتبر: " + body[:160].replace("\n", " ")
    if obj.get("ok"):
        extra = (" + بایگانی " + obj["archive"]) if obj.get("archive") else ""
        return True, "فایل %s توی درایو آپدیت شد (%s نویسه)%s" % (
            obj.get("file"), obj.get("chars"), extra)
    return False, "خطا از وب اپ: " + str(obj.get("error"))


def call_webapp(text: str, archive: bool = False) -> str:
    """متن را به وب اپ Apps Script میفرستد. خروجی: پیام موفقیت."""
    if not WEBAPP_URL:
        raise RuntimeError("WEBAPP_URL خالی است")

    form = urllib.parse.urlencode({
        "text": text,
        "secret": WEBAPP_SECRET,
        "archive": "1" if archive else "0",
        "t": str(int(time.time())),
    })

    errors = []

    # ۱) POST (بدون از دست دادن بدنه هنگام ریدایرکت)
    try:
        request = urllib.request.Request(
            WEBAPP_URL,
            data=form.encode("utf-8"),
            headers={"User-Agent": USER_AGENT,
                     "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        opener = urllib.request.build_opener(_KeepPostRedirect())
        with opener.open(request, timeout=NETWORK_TIMEOUT) as response:
            body = response.read(20000).decode("utf-8", "replace")
        ok, info = _parse_webapp_reply(body)
        if ok:
            return info
        errors.append("POST: " + info)
    except Exception as exc:
        errors.append("POST: " + str(exc))

    # ۲) پشتیبان: GET (ریدایرکت گوگل معمولاً با GET خوب کار میکند)
    try:
        separator = "&" if "?" in WEBAPP_URL else "?"
        request = urllib.request.Request(WEBAPP_URL + separator + form,
                                         headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response:
            body = response.read(20000).decode("utf-8", "replace")
        ok, info = _parse_webapp_reply(body)
        if ok:
            return info
        errors.append("GET: " + info)
    except Exception as exc:
        errors.append("GET: " + str(exc))

    raise RuntimeError(" | ".join(errors))


def find_drive_sync_folder():
    """اگر Google Drive for Desktop نصب باشد، پوشه همگامشده را پیدا میکند."""
    candidates = []
    if DRIVE_SYNC_FOLDER:
        candidates += [Path(DRIVE_SYNC_FOLDER), Path(DRIVE_SYNC_FOLDER) / DRIVE_FOLDER_NAME]
    home = Path.home()
    for base in (home / "My Drive", home / "Google Drive", home / "Drive"):
        candidates += [base / DRIVE_FOLDER_NAME, base]
    if os.name == "nt":
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            candidates += [Path("%s:\\My Drive" % letter) / DRIVE_FOLDER_NAME,
                           Path("%s:\\" % letter) / DRIVE_FOLDER_NAME]

    # فقط جایی را قبول میکنیم که نشانه پوشه ما (salam.py.txt / name.txt) آنجا باشد
    markers = ("salam.py.txt", LETTER_FILE_NAME)
    for candidate in candidates:
        try:
            if candidate.is_dir() and any((candidate / m).exists() for m in markers):
                return candidate
        except OSError:
            continue
    return None


def save_local_letter(text: str) -> Path:
    LOCAL_LETTERS_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCAL_LETTERS_DIR / LETTER_FILE_NAME
    path.write_text(text, encoding="utf-8")
    return path


def send_letter(text: str, archive: bool = False):
    """نامه را تا جایی که ممکن است ذخیره میکند و نتیجه هر مسیر را برمیگرداند."""
    if len(text) > MAX_LETTER_CHARS:
        text = text[:MAX_LETTER_CHARS]

    results = ["[محلی] " + str(save_local_letter(text))]

    sync = find_drive_sync_folder()
    if sync:
        try:
            destination = sync / LETTER_FILE_NAME
            destination.write_text(text, encoding="utf-8")
            results.append("[همگامساز درایو] " + str(destination))
        except Exception as exc:
            results.append("[همگامساز درایو] خطا: " + str(exc))

    if WEBAPP_URL:
        try:
            results.append("[گوگل درایو] " + call_webapp(text, archive=archive))
        except Exception as exc:
            results.append("[گوگل درایو] خطا: " + str(exc))
    else:
        results.append("[گوگل درایو] وب اپ تنظیم نشده - قسمت «ارسال نامه» در README را ببین.")

    return results


# ===================== رابط کاربری =====================

def main() -> int:
    args = sys.argv[1:]

    # حالتهای بدون پنجره (برای تست و خط فرمان)
    if args and args[0] == "--hash":
        path = Path(args[1]) if len(args) > 1 else LOCAL_COPY
        print(sha256(path.read_bytes()))
        return 0

    if args and args[0] == "--send":
        text = " ".join(args[1:]) if len(args) > 1 else sys.stdin.read()
        for line in send_letter(text, archive=True):
            print(line)
        return 0

    start_on_letter = any(a in ("--tab=letter", "--letter", "-l") for a in args)

    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title("Windows SuperControl")
    root.geometry("780x620")
    root.minsize(600, 460)

    book = ttk.Notebook(root)
    book.pack(fill="both", expand=True, padx=8, pady=8)
    tab_run = ttk.Frame(book, padding=10)
    tab_letter = ttk.Frame(book, padding=10)
    book.add(tab_run, text="دریافت و اجرا")
    book.add(tab_letter, text="ارسال نامه")
    if start_on_letter:
        book.select(tab_letter)

    # ---------------- تب ۱: دریافت و اجرا ----------------
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
                    "این کد روی کامپیوترتان اجرا شود؟\n\n"
                    "منبع: " + source + "\n"
                    "SHA-256: " + sha256(data)[:24] + "...",
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
            messagebox.showwarning("زمان تمام شد", "کد دانلودشده بیش از حد طول کشید و متوقف شد.")
        except Exception as exc:
            run_log("خطا: " + str(exc))
            messagebox.showerror("خطا", str(exc))
        finally:
            run_button.config(state="normal")

    run_button = ttk.Button(tab_run, text="دریافت و اجرا", command=on_run)
    run_button.pack(fill="x", pady=(10, 0))

    # ---------------- تب ۲: ارسال نامه ----------------
    ttk.Label(tab_letter, text="ارسال نامه",
              font=("Tahoma", 13, "bold")).pack(anchor="center")
    ttk.Label(tab_letter,
              text="هر چه اینجا بنویسی، همان لحظه توی name.txt ذخیره میشه (محلی + درایو).",
              font=("Tahoma", 9), foreground="#555555").pack(anchor="center", pady=(0, 8))

    letter_box = scrolledtext.ScrolledText(tab_letter, wrap="word", height=9,
                                           font=("Tahoma", 11))
    letter_box.pack(fill="both", expand=True)

    status_var = tk.StringVar(value="آماده. شروع کن به نوشتن ...")
    ttk.Label(tab_letter, textvariable=status_var, foreground="#0a7a3a",
              wraplength=700).pack(fill="x", pady=(4, 0))

    letter_log = scrolledtext.ScrolledText(tab_letter, wrap="word", height=5,
                                           font=("Consolas", 9))
    letter_log.pack(fill="x", pady=(8, 0))

    results_q = queue.Queue()

    def apply_result(lines, error) -> None:
        stamp = time.strftime("%H:%M:%S")
        for line in lines:
            letter_log.insert("end", "[%s] %s\n" % (stamp, line))
        if error:
            letter_log.insert("end", "[%s] خطا: %s\n" % (stamp, error))
            status_var.set("خطا توی ارسال - جزئیات پایین")
        else:
            status_var.set("آخرین ذخیره: %s ✅" % stamp)
        letter_log.see("end")

    def poll_results() -> None:
        # فقط از ترد اصلی صدا زده میشود (امن برای tkinter)
        try:
            while True:
                lines, error = results_q.get_nowait()
                apply_result(lines, error)
        except queue.Empty:
            pass
        root.after(200, poll_results)

    def do_send(archive: bool = False) -> None:
        text = letter_box.get("1.0", "end-1c")
        status_var.set("در حال ذخیره ...")

        def worker():
            try:
                results_q.put((send_letter(text, archive=archive), None))
            except Exception as exc:
                results_q.put(([], str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    pending = {"job": None}

    def schedule_auto_save(event=None) -> None:
        if pending["job"] is not None:
            try:
                root.after_cancel(pending["job"])
            except Exception:
                pass
        status_var.set("نوشتن ... ذخیره خودکار تا %.1f ثانیه دیگه" % (AUTO_SAVE_MS / 1000.0))
        pending["job"] = root.after(AUTO_SAVE_MS, lambda: do_send(False))

    controls = ttk.Frame(tab_letter)
    controls.pack(fill="x", pady=(8, 0))
    ttk.Button(controls, text="ارسال و بایگانی",
               command=lambda: do_send(True)).pack(side="right", padx=3)
    ttk.Button(controls, text="حالا ذخیره کن",
               command=lambda: do_send(False)).pack(side="right", padx=3)

    letter_box.bind("<KeyRelease>", schedule_auto_save)

    run_log("آماده. برای گرفتن کد از اینترنت و اجرای آن، دکمه «دریافت و اجرا» را بزن.")
    run_log("هیچ کدی بهصورت خودکار اجرا نمیشود.")
    letter_log.insert("end", "آماده. تب «ارسال نامه» همینجاست.\n")
    root.after(200, poll_results)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
