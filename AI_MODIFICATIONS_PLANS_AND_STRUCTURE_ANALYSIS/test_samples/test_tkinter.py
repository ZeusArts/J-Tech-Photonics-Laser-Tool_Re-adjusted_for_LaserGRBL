"""Minimal Tkinter availability and dialog test for Inkscape 1.4.2 Python."""

import sys


def check_tkinter(show_window: bool = True) -> int:
    try:
        import tkinter as tk
        from tkinter import ttk
    except Exception as exc:
        print(f"ERROR: Failed to import tkinter: {exc}", file=sys.stderr)
        return 1

    print(f"Python: {sys.version}")
    print(f"TkVersion: {tk.TkVersion}, TclVersion: {tk.TclVersion}")

    if not show_window:
        try:
            root = tk.Tk()
            root.withdraw()
            root.update_idletasks()
            root.destroy()
            print("OK: tkinter Tk() initialization succeeded (headless check).")
            return 0
        except Exception as exc:
            print(f"ERROR: tkinter Tk() initialization failed: {exc}", file=sys.stderr)
            return 2

    root = tk.Tk()
    root.title("Inkscape 1.4.2 Tkinter Test")
    root.geometry("360x140")
    root.attributes("-topmost", True)

    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame,
        text=f"Tkinter is working!\nPython {sys.version_info.major}.{sys.version_info.minor} / Tk {tk.TkVersion}",
        justify="center",
    ).pack(pady=(0, 12))

    ttk.Button(frame, text="OK (Close)", command=root.destroy).pack()

    root.mainloop()
    print("OK: Tkinter test window closed cleanly.")
    return 0


if __name__ == "__main__":
    headless = "--headless" in sys.argv
    sys.exit(check_tkinter(show_window=not headless))

