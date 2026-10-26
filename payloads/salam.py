# -*- coding: utf-8 -*-
"""پیام کوتاهی که توی گوگل درایو قرار میگیرد و از راه دور اجرا میشود.

این فایل فقط از کتابخانه استاندارد پایتون (tkinter) استفاده میکند.
"""

import tkinter as tk
from tkinter import messagebox


def main():
    root = tk.Tk()
    root.withdraw()  # پنجره اصلی مخفی میماند، فقط پیامها دیده میشوند

    messagebox.showinfo("سلام مجید جان", "دوست دارم.")

    answer = messagebox.askyesno(
        "یک سوال",
        "اگه دوستم داری، «بله» رو بزن.\nهمین.",
    )

    if answer:
        messagebox.showinfo("همین", "منم دوستت دارم مجید جان!")
    else:
        messagebox.showinfo("همین", "باشه، دفعه بعد :)")

    root.destroy()


if __name__ == "__main__":
    main()
