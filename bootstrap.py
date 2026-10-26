# -*- coding: utf-8 -*-
"""
Windows SuperControl - bootstrap (تنها فایل پایتونی توی گیت هاب)
================================================================

کاری که میکند خیلی ساده است:

  * یک پنجره کوچک با **فقط یک دکمه**: «شروع» / «توقف».
  * با زدن «شروع»، آخرین نسخه «برنامه اصلی» را مستقیم از گوگل درایو
    (main.py.txt) دانلود میکند، هش آن را چک میکند، کش میکند و اجرا میکند.
  * با زدن «توقف»، همان برنامه را (همراه زیردستهایش) میبندد.
  * خروجی و خطاهای برنامه اصلی توی همین پنجره نمایش داده میشود تا اگر
    چیزی کار نکرد، دلیلش معلوم باشد.

پس هر تغییری توی فایلهای درایو بدیم، دفعه بعد که «شروع» را بزنی اعمال میشود؛
نیازی به آپدیت گیت هاب نیست. گیت هاب فقط همین فایل و run.bat را نگه میدارد.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

# ============ آیدی فایلهای برنامه توی گوگل درایو (ثابت) ============
DRIVE_MAIN_FILE_ID = "1GtCEP0gcIKR2xQ_lBc1WrTdT1VEw6vTW"      # main.py.txt
DRIVE_CONFIG_FILE_ID = "1nrCZJoXHuLXmQir9xwLrO1dEWV5OdYog"   # config.txt
# ====================================================================

MARKER = "# WSC-MAIN-PROGRAM"
MAX_BYTES = 500_000
TIMEOUT = 20
POLL_MS = 300
USER_AGENT = "Mozilla/5.0 (Windows-SuperControl bootstrap)"

MAIN_URL = "https://drive.google.com/uc?export=download&id=" + DRIVE_MAIN_FILE_ID
CONFIG_URL = "https://drive.google.com/uc?export=download&id=" + DRIVE_CONFIG_FILE_ID
LOCAL_CONFIG = Path(__file__).resolve().parent / "config.txt"   # اختیاری، دستی


def app_dir() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "WindowsSuperControl"
    return Path.home() / ".windows_supercontrol"


APP_DIR = app_dir()
MAIN_CACHE = APP_DIR / "main.py"
CONFIG_CACHE = APP_DIR / "config.txt"
TRUST_FILE = APP_DIR / "trusted.json"
PID_FILE = APP_DIR / "main.pid"


# ===================== توابع =====================

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str, label: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise RuntimeError(label + ": فایل بیش از حد بزرگ است")
    head = data[:1200].lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in head[:500]:
        raise RuntimeError(label + ": درایو صفحه HTML برگرداند به جای فایل")
    if not data.strip():
        raise RuntimeError(label + ": فایل خالی است")
    return data


def parse_config(data: bytes) -> dict:
    result = {}
    for line in data.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip().upper()] = value.strip()
    return result


def fetch_program(log):
    APP_DIR.mkdir(parents=True, exist_ok=True)

    log("[1/2] دریافت برنامه اصلی (main.py.txt) از گوگل درایو ...")
    data = download(MAIN_URL, "main.py.txt")
    text = data.decode("utf-8")       # اگر UTF-8 نباشد خطا میدهد
    if MARKER not in text[:2000]:
        raise RuntimeError("فایل دریافتی برنامه اصلی نیست (نشانگر پیدا نشد)")
    log("      %d بایت | SHA-256: %s" % (len(data), sha256(data)))

    log("[2/2] دریافت تنظیمات (config.txt) ...")
    cfg = {}
    try:
        raw = download(CONFIG_URL, "config.txt")
        CONFIG_CACHE.write_bytes(raw)
        cfg = parse_config(raw)
        log("      %d تنظیم خوانده شد" % len(cfg))
    except Exception as exc:
        log("      کانفیگ درایو نیامد: " + str(exc))
        if CONFIG_CACHE.exists():
            cfg = parse_config(CONFIG_CACHE.read_bytes())
            log("      از نسخه کششده استفاده شد")

    if LOCAL_CONFIG.exists():       # کانفیگ دستی کنار bootstrap، اولویت دارد
        local = parse_config(LOCAL_CONFIG.read_bytes())
        cfg.update({k: v for k, v in local.items() if v})
        log("      کانفیگ محلی اعمال شد: " + str(LOCAL_CONFIG))

    return data, text, cfg


def load_trust() -> dict:
    try:
        return json.loads(TRUST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_trust(digest: str) -> None:
    TRUST_FILE.write_text(
        json.dumps({"hash": digest, "time": time.strftime("%Y-%m-%d %H:%M:%S")},
                   ensure_ascii=False), encoding="utf-8")


def spawn(cfg: dict, output_q: queue.Queue):
    env = os.environ.copy()
    if cfg.get("WEBAPP_URL"):
        env["WSC_WEBAPP_URL"] = cfg["WEBAPP_URL"]
    if cfg.get("WEBAPP_SECRET"):
        env["WSC_WEBAPP_SECRET"] = cfg["WEBAPP_SECRET"]
    env["WSC_BOOTSTRAP"] = "1"
    env["WSC_APP_DIR"] = str(APP_DIR)

    kwargs = {}
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        kwargs["creationflags"] = flags

    proc = subprocess.Popen(
        [sys.executable, "-u", str(MAIN_CACHE)],
        cwd=str(APP_DIR), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        **kwargs
    )
    try:
        PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    except OSError:
        pass

    def reader():
        try:
            for line in proc.stdout:
                output_q.put(line.rstrip())
        except Exception as exc:
            output_q.put("[bootstrap] خطا در خواندن خروجی: " + str(exc))
        output_q.put(None)

    threading.Thread(target=reader, daemon=True).start()
    return proc


def terminate(proc) -> None:
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, text=True, timeout=6)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    else:
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        PID_FILE.unlink()
    except OSError:
        pass


def diagnose() -> int:
    """حالت خط فرمان: بدون پنجره، فقط وضعیت درایو و کش را چاپ میکند."""
    print("Windows SuperControl - diagnose")
    print("APP_DIR     :", APP_DIR)
    print("main URL    :", MAIN_URL)
    print("config URL  :", CONFIG_URL)
    try:
        data, text, cfg = fetch_program(print)
        print("OK          : main.py.txt معتبر است |", len(data), "بایت |", sha256(data))
        print("config keys :", sorted(k for k in cfg if k.startswith("WEBAPP")))
    except Exception as exc:
        print("ERROR       :", exc)
        if MAIN_CACHE.exists():
            print("CACHED      : موجود است -", MAIN_CACHE)
        return 1
    print("trusted     :", load_trust())
    return 0


# ===================== پنجره (یک دکمه) =====================

def gui() -> int:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title("Windows SuperControl")
    root.geometry("600x420")
    root.minsize(480, 340)

    ttk.Label(root, text="Windows SuperControl",
              font=("Tahoma", 15, "bold")).pack(pady=(12, 2))
    ttk.Label(root,
              text="همه کدها توی گوگل درایواند. هر بار «شروع» آخرین نسخه را میگیرد.",
              font=("Tahoma", 9), foreground="#555555").pack(pady=(0, 8))

    output = scrolledtext.ScrolledText(root, wrap="word", font=("Consolas", 9))
    output.pack(fill="both", expand=True, padx=12)

    status = tk.StringVar(value="آماده ✅")
    ttk.Label(root, textvariable=status, foreground="#0a7a3a",
              wraplength=560).pack(fill="x", padx=12, pady=(4, 0))

    def log(message) -> None:
        output.insert("end", str(message) + "\n")
        output.see("end")
        root.update_idletasks()

    state = {"proc": None}
    output_q = queue.Queue()

    def set_idle(message: str) -> None:
        state["proc"] = None
        button.config(text="▶ شروع", state="normal")
        status.set(message)

    def stop() -> None:
        proc = state["proc"]
        if proc is not None and proc.poll() is None:
            terminate(proc)
            log("■ برنامه متوقف شد.")
        set_idle("متوقف - برای اجرا «شروع» را بزن")

    def start() -> None:
        button.config(state="disabled")
        status.set("در حال دریافت از گوگل درایو ...")

        try:
            data, text, cfg = fetch_program(log)
        except Exception as exc:
            log("❌ خطا در دریافت از درایو: " + str(exc))
            if MAIN_CACHE.exists():
                data = MAIN_CACHE.read_bytes()
                text = data.decode("utf-8", "replace")
                cfg = parse_config(CONFIG_CACHE.read_bytes()) if CONFIG_CACHE.exists() else {}
                if LOCAL_CONFIG.exists():
                    cfg.update({k: v for k, v in
                                parse_config(LOCAL_CONFIG.read_bytes()).items() if v})
                log("⚠ از آخرین نسخه کششده استفاده میشود.")
            else:
                messagebox.showerror("خطا", "برنامه از درایو نیامد و نسخه کششدهای هم نیست:\n\n" + str(exc))
                status.set("خطا ❌")
                button.config(state="normal")
                return

        digest = sha256(data)
        trust = load_trust()
        auto_trust = str(cfg.get("AUTO_TRUST", "")).lower() in ("1", "yes", "true")

        if trust.get("hash") != digest:
            preview = "\n".join(text.splitlines()[:8])[:500]
            if auto_trust:
                log("نسخه جدید (هش عوض شد) - AUTO_TRUST فعال است، بدون پرسش اجرا شد.")
            else:
                answer = messagebox.askyesno(
                    "تایید نسخه جدید",
                    "نسخه برنامه توی درایو تغییر کرده است.\n\n"
                    "هش قبلی: %s\nهش جدید: %s\nحجم: %d بایت\n\n"
                    "--- چند خط اول کد ---\n%s\n\nاجرا شود؟"
                    % (trust.get("hash", "(اولین اجرا)")[:24], digest[:24],
                       len(data), preview),
                )
                if not answer:
                    log("اجرای نسخه جدید توسط شما لغو شد.")
                    status.set("لغو شد")
                    button.config(state="normal")
                    return
            save_trust(digest)
        else:
            log("هش تایید شد: " + digest[:24])

        try:
            temporary = MAIN_CACHE.with_name("main.py.tmp")
            temporary.write_bytes(data)
            temporary.replace(MAIN_CACHE)
        except Exception as exc:
            messagebox.showerror("خطا", "نتوانستم فایل را کش کنم:\n" + str(exc))
            status.set("خطا ❌")
            button.config(state="normal")
            return

        log("--- پیشنمایش کد ---")
        for line in text.splitlines()[:5]:
            log("   " + line)
        log("--------------------")

        try:
            state["proc"] = spawn(cfg, output_q)
        except Exception as exc:
            messagebox.showerror("خطا", "برنامه اجرا نشد:\n" + str(exc))
            log("❌ " + str(exc))
            status.set("خطا ❌")
            button.config(state="normal")
            return

        button.config(text="■ توقف", state="normal")
        status.set("در حال اجرا ✅ | نسخه %s" % digest[:8])
        log("▶ برنامه اصلی اجرا شد. خروجیاش اینجا نمایش داده میشود.")

    def toggle() -> None:
        proc = state["proc"]
        if proc is not None and proc.poll() is None:
            stop()
        else:
            start()

    def poll() -> None:
        # خروجی برنامه اصلی
        shown = 0
        try:
            while shown < 40:
                line = output_q.get_nowait()
                if line is None:
                    continue
                log("› " + line)
                shown += 1
        except queue.Empty:
            pass

        proc = state["proc"]
        if proc is not None and proc.poll() is not None:
            log("برنامه اصلی بسته شد. کد خروج: %s" % proc.returncode)
            try:
                PID_FILE.unlink()
            except OSError:
                pass
            set_idle("متوقف - برای اجرای دوباره «شروع» را بزن")
        root.after(POLL_MS, poll)

    def on_close() -> None:
        stop()
        root.destroy()

    button = ttk.Button(root, text="▶ شروع", command=toggle)
    button.pack(fill="x", padx=12, pady=12)
    root.protocol("WM_DELETE_WINDOW", on_close)

    log("آماده. فقط یک دکمه: «شروع» / «توقف».")
    log("منبع کد: گوگل درایو → main.py.txt")
    log("محل کش و دادهها: " + str(APP_DIR))
    root.after(POLL_MS, poll)
    root.mainloop()
    return 0


def main() -> int:
    if "--diagnose" in sys.argv or "--check" in sys.argv:
        return diagnose()
    return gui()


if __name__ == "__main__":
    raise SystemExit(main())
