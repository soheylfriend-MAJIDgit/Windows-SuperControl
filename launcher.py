# -*- coding: utf-8 -*-
"""
Windows SuperControl - اجراکننده ساده کد پایتون از گوگل درایو
=============================================================

کاری که این برنامه میکند (همهچیز شفاف و جلوی چشم شماست):

  1. با زدن تنها دکمه پنجره، فایل پایتون را مستقیم از اینترنت میگیرد
     (اول گوگل درایو، اگر نشد از گیتهاد، اگر نشد از نسخه آفلاین داخل ریپازتوری).
  2. اثرانگشت SHA-256 فایل را با مقدار پینشده در همین فایل مقایسه میکند؛
     اگر کسی فایل درایو را عوض کرده باشد، اجرا نمیشود.
  3. متن کامل کد دریافتی را قبل از اجرا داخل همان پنجره نشان میدهد.
  4. یک تاییدیه میگیرد، بعد کد را در یک پروسه جداگانه اجرا میکند و
     خروجیاش را نشان میدهد.

هیچ اجرای خودکار، استارتآپ، نصب سرویس یا مخفیکاریای وجود ندارد.
فقط با کلیک خودتان اتفاقی میافتد.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

# ====================== تنظیمات (اینجا تغییر بده) ======================

# شناسه فایل salam.py.txt در پوشه درایو:
# https://drive.google.com/drive/folders/1PmMAu537pzN3mjKf_PYctUOlbOIQCUf1
DRIVE_FILE_ID = "11B1QGU0zuhD53sdNk_y5TAo_Qq-KkEI9"

# منابع اینترنتی، به ترتیب اولویت.
SOURCES = [
    "https://drive.google.com/uc?export=download&id=" + DRIVE_FILE_ID,
    "https://raw.githubusercontent.com/soheylfriend-MAJIDgit/"
    "Windows-SuperControl/arena/96bec320-windows-supercontrol/payloads/salam.py",
]

# نسخه آفلاین (همان فایلی که توی درایو آپلود شده) - فقط اگر نت در دسترس نبود
LOCAL_COPY = Path(__file__).resolve().parent / "payloads" / "salam.py"

# اثرانگشت فایل مجاز. اگر محتوای درایو را عوض کردی، هش جدید را اینجا بگذار.
# (دستور بهدستآوردن هش جدید توی README نوشته شده.)
# گذاشتن None یعنی غیرفعال شدن این چک امنیتی - توصیه نمیشود.
EXPECTED_SHA256 = "f4c8f18d644017429a4aaf0aab28aba28ab6e962c9919413acce89270009213c"

CONFIRM_BEFORE_RUN = True   # قبل از اجرا یک تاییدیه بگیرد
TIMEOUT_SECONDS = 300       # حداکثر زمان اجرای کد دانلودشده (ثانیه)
MAX_BYTES = 2_000_000       # حداکثر حجم فایل دانلودی
CACHE_DIR = Path(tempfile.gettempdir()) / "WindowsSuperControl"

# ======================================================================


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, timeout: int = 20) -> bytes:
    """یک URL را میگیرد و محتوای خامش را برمیگرداند."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows-SuperControl launcher)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(MAX_BYTES + 1)


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
                # درایو گاهی به جای فایل، صفحه «اخطار ویروس» میدهد
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
    """(مجاز بودن، پیام توضیحی)"""
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
    """کد را در یک فایل موقت مینویسد و با همان پایتون، جداگانه اجرا میکند."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target = CACHE_DIR / "downloaded_code.py"
    target.write_bytes(data)

    extra = {}
    if os.name == "nt":
        # فقط جلوی پنجره کنسول اضافه را میگیرد؛ کد اصلی کاملاً قابل دیدن است
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


def main() -> int:
    # حالت کمکیک: python launcher.py --hash [مسیر_فایل]
    if len(sys.argv) > 1 and sys.argv[1] == "--hash":
        path = Path(sys.argv[2]) if len(sys.argv) > 2 else LOCAL_COPY
        print(sha256(path.read_bytes()))
        return 0

    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title("Windows SuperControl")
    root.geometry("760x560")
    root.minsize(560, 400)

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame,
        text="اجراکننده کد پایتون از گوگل درایو",
        font=("Tahoma", 14, "bold"),
    ).pack(anchor="center", pady=(0, 4))

    ttk.Label(
        frame,
        text="منبع: drive.google.com  |  فایل: salam.py.txt  |  قبل از اجرا هش چک میشود",
        font=("Tahoma", 9),
        foreground="#555555",
    ).pack(anchor="center", pady=(0, 10))

    output = scrolledtext.ScrolledText(frame, wrap="word", font=("Consolas", 10))
    output.pack(fill="both", expand=True)

    def log(message) -> None:
        output.insert("end", str(message) + "\n")
        output.see("end")
        root.update_idletasks()

    def on_click() -> None:
        button.config(state="disabled")
        try:
            log("=== شروع ===")
            data, source = get_code(log)

            ok, message = verify(data)
            log(message)
            if not ok:
                messagebox.showerror("توقف امنیتی", message)
                return

            log("\n--- متن کد دریافتی ---")
            log(data.decode("utf-8", "replace"))
            log("--- پایان متن کد ---\n")

            if CONFIRM_BEFORE_RUN:
                confirmed = messagebox.askyesno(
                    "تایید اجرا",
                    "این کد روی کامپیوترتان اجرا شود؟\n\n"
                    "منبع: " + source + "\n"
                    "SHA-256: " + sha256(data)[:24] + "...",
                )
                if not confirmed:
                    log("اجرا توسط شما لغو شد.")
                    return

            log("در حال اجرا ... (تا %d ثانیه)" % TIMEOUT_SECONDS)
            result = run_code(data)
            log("--- خروجی برنامه ---")
            log(result.stdout.strip() or "(بدون خروجی متنی)")
            if result.stderr.strip():
                log("--- خطاها ---")
                log(result.stderr.strip())
            log("=== پایان - کد خروج: %s ===" % result.returncode)

        except subprocess.TimeoutExpired:
            log("مهلت اجرا تمام شد؛ پروسه متوقف شد.")
            messagebox.showwarning("زمان تمام شد", "کد دانلودشده بیش از حد طول کشید و متوقف شد.")
        except Exception as exc:
            log("خطا: " + str(exc))
            messagebox.showerror("خطا", str(exc))
        finally:
            button.config(state="normal")

    button = ttk.Button(frame, text="دریافت و اجرا", command=on_click)
    button.pack(fill="x", pady=(10, 0))

    log("آماده. برای گرفتن کد از اینترنت و اجرای آن، دکمه «دریافت و اجرا» را بزن.")
    log("هیچ کدی بهصورت خودکار اجرا نمیشود.")
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
