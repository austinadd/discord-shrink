"""Discord-style window for Discord Shrink. Started from discord_shrink.py with no arguments."""

import ctypes
import os
import queue
import subprocess
import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog

C = {
    "bg": "#313338", "panel": "#2b2d31", "panel_hi": "#32343a", "deep": "#1e1f22",
    "field": "#383a40", "hover": "#404249", "divider": "#3f4147", "line": "#4e5058",
    "blurple": "#5865f2", "green": "#23a55a", "red": "#f23f43", "yellow": "#f0b232",
    "text": "#f2f3f5", "muted": "#b5bac1", "faint": "#949ba4", "white": "#ffffff",
}
FONT = "Segoe UI"
LIMITS = [(10, "Free"), (20, "Default"), (50, "Nitro Basic"), (500, "Nitro")]


def rrect(c, x1, y1, x2, y2, r, **kw):
    """Rounded rectangle on a canvas (smoothed polygon with doubled corner points)."""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y1 + r,
           x2, y2 - r, x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2, x1 + r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1]
    kw.setdefault("outline", "")
    return c.create_polygon(pts, smooth=True, **kw)


def blend(a, b, t):
    a, b = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def fit(font, text, width):
    """Shorten text with an ellipsis so it fits in width pixels."""
    if font.measure(text) <= width:
        return text
    while text and font.measure(text + "…") > width:
        text = text[:-1]
    return text + "…"


class Toggle(tk.Canvas):
    def __init__(self, parent, S, value=False, bg=C["panel"]):
        self.S, self.w, self.h = S, S(40), S(24)
        super().__init__(parent, width=self.w, height=self.h, bg=bg, highlightthickness=0, cursor="hand2")
        self.value, self.pos = value, float(value)
        self.bind("<Button-1>", self.flip)
        self.draw()

    def flip(self, _=None):
        self.value = not self.value
        self.slide()

    def slide(self):
        target = float(self.value)
        self.pos += max(-0.2, min(0.2, target - self.pos))
        self.draw()
        if self.pos != target:
            self.after(12, self.slide)

    def draw(self):
        self.delete("all")
        rrect(self, 0, 0, self.w, self.h, self.h / 2, fill=blend(C["line"], C["green"], self.pos))
        pad, d = self.S(3), self.h - self.S(6)
        x = pad + self.pos * (self.w - self.h)
        self.create_oval(x, pad, x + d, pad + d, fill=C["white"], outline="")


class Settings(tk.Canvas):
    def __init__(self, parent, app, limit):
        S = self.S = app.S
        self.H = S(156)
        super().__init__(parent, height=self.H, bg=C["bg"], highlightthickness=0)
        values = [v for v, _ in LIMITS]
        self.selected = limit if limit in values else None
        self.pill_bg, self.pill_sub = {}, {}
        self.entry_var = tk.StringVar(value="" if self.selected else f"{limit:g}")
        self.entry = tk.Entry(self, textvariable=self.entry_var, bg=C["field"], fg=C["text"],
                              insertbackground=C["text"], relief="flat", font=(FONT, 11, "bold"),
                              width=5, highlightthickness=0, justify="center")
        self.entry.bind("<KeyRelease>", self.on_entry)
        self.toggle = Toggle(self, S)
        self.bind("<Configure>", lambda e: self.draw())

    def draw(self):
        S, w = self.S, self.winfo_width()
        self.delete("all")
        rrect(self, 0, 0, w, self.H, S(12), fill=C["panel"])
        self.create_text(S(20), S(20), text="UPLOAD LIMIT", anchor="w", fill=C["faint"], font=(FONT, 8, "bold"))
        x, y1, y2 = S(20), S(34), S(84)
        for value, label in LIMITS:
            tag = f"pill{value}"
            self.pill_bg[value] = rrect(self, x, y1, x + S(96), y2, S(8), tags=tag)
            self.create_text(x + S(48), S(52), text=f"{value} MB", fill=C["white"], font=(FONT, 11, "bold"), tags=tag)
            self.pill_sub[value] = self.create_text(x + S(48), S(70), text=label, font=(FONT, 8), tags=tag)
            self.tag_bind(tag, "<Button-1>", lambda e, v=value: self.pick(v))
            self.tag_bind(tag, "<Enter>", lambda e, v=value: self.hover(v, True))
            self.tag_bind(tag, "<Leave>", lambda e, v=value: self.hover(v, False))
            x += S(104)
        self.custom_bg = rrect(self, x, y1, x + S(116), y2, S(8), fill=C["field"], width=2, tags="custom")
        self.create_window(x + S(44), S(53), window=self.entry, width=S(52))
        self.create_text(x + S(84), S(53), text="MB", fill=C["muted"], font=(FONT, 11, "bold"), tags="custom")
        self.create_text(x + S(58), S(71), text="Custom", fill=C["faint"], font=(FONT, 8), tags="custom")
        self.tag_bind("custom", "<Button-1>", lambda e: self.entry.focus_set())

        self.create_line(S(20), S(100), w - S(20), S(100), fill=C["divider"])
        self.create_text(S(20), S(120), text="Lower video resolution if needed", anchor="w",
                         fill=C["text"], font=(FONT, 10, "bold"))
        self.create_text(S(20), S(139), anchor="w", fill=C["faint"], font=(FONT, 9),
                         text="Frame rate is always kept. Turn on to keep long clips sharper.")
        self.create_window(w - S(20), S(128), anchor="e", window=self.toggle)
        self.paint()

    def paint(self, hovered=None):
        for value, item in self.pill_bg.items():
            sel = value == self.selected
            self.itemconfigure(item, fill=C["blurple"] if sel else C["hover"] if value == hovered else C["field"])
            self.itemconfigure(self.pill_sub[value], fill="#dfe2ff" if sel else C["faint"])
        self.itemconfigure(self.custom_bg, outline=C["blurple"] if self.selected is None else "")

    def hover(self, value, on):
        self.configure(cursor="hand2" if on else "")
        self.paint(value if on else None)

    def pick(self, value):
        self.selected = value
        self.entry_var.set("")
        self.focus_set()
        self.paint(value)

    def on_entry(self, _=None):
        if self.entry_var.get().strip():
            self.selected = None
            self.paint()

    def limit(self):
        if self.selected is not None:
            return self.selected
        try:
            v = float(self.entry_var.get())
            return v if v > 0 else None
        except ValueError:
            return None


class DropZone(tk.Canvas):
    def __init__(self, parent, app):
        self.S, self.app, self.hot = app.S, app, False
        self.H = self.S(150)
        super().__init__(parent, height=self.H, bg=C["bg"], highlightthickness=0, cursor="hand2")
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Enter>", lambda e: self.set_hot(True))
        self.bind("<Leave>", lambda e: self.set_hot(False))
        self.bind("<Button-1>", lambda e: app.browse())

    def set_hot(self, hot):
        self.hot = hot
        self.draw()

    def draw(self):
        S, w, hot = self.S, self.winfo_width(), self.hot
        self.delete("all")
        rrect(self, 1, 1, w - 1, self.H - 1, S(12), fill=C["panel_hi"] if hot else C["panel"],
              outline=C["blurple"] if hot else C["line"], width=2, dash=(6, 4))
        cx = w / 2
        self.create_oval(cx - S(26), S(18), cx + S(26), S(70), fill=C["blurple"] if hot else C["field"], outline="")
        arrow = C["white"] if hot else C["muted"]
        self.create_polygon(cx, S(29), cx - S(11), S(42), cx + S(11), S(42), fill=arrow)
        self.create_rectangle(cx - S(3), S(41), cx + S(3), S(53), fill=arrow, outline="")
        rrect(self, cx - S(12), S(56), cx + S(12), S(60), S(2), fill=arrow)
        self.create_text(cx, S(94), text="Drop files here", fill=C["text"], font=(FONT, 13, "bold"))
        self.create_text(cx, S(120), fill=C["muted"], font=(FONT, 9),
                         text="or click to browse  ·  videos, images, zips, folders, anything")


class FileCard(tk.Canvas):
    def __init__(self, parent, app, path, limit, downscale):
        self.S, self.app = app.S, app
        self.H = self.S(68)
        super().__init__(parent, height=self.H, bg=C["bg"], highlightthickness=0)
        self.path, self.limit, self.downscale = path, limit, downscale
        self.state, self.status, self.progress, self.spin = "queued", "Waiting in line…", 0.0, 0.0
        self.result, self.btn_bg = None, None
        self.orig = folder_size(path) if path.is_dir() else path.stat().st_size
        self.size_text = app.core.mb(self.orig)
        core = app.core
        ext = path.suffix.lower()
        if path.is_dir():
            self.badge, self.color = "DIR", C["yellow"]
        elif ext in core.VIDEO_EXTS:
            self.badge, self.color = ext[1:5].upper(), C["blurple"]
        elif ext in core.IMAGE_EXTS:
            self.badge, self.color = ext[1:5].upper(), "#eb459e"
        elif ext in core.ZIP_EXTS:
            self.badge, self.color = "ZIP", C["yellow"]
        else:
            self.badge, self.color = (ext[1:5].upper() or "FILE"), C["line"]
        self.bind("<Configure>", lambda e: self.draw())

    # state changes (always called on the UI thread)
    def start(self):
        self.state, self.status, self.progress = "working", "Starting…", None
        self.draw()

    def set_status(self, text):
        self.status = text[:1].upper() + text[1:]
        self.draw()

    def set_progress(self, p):
        self.progress = p
        self.draw()

    def finish(self, out):
        mb = self.app.core.mb
        self.result, self.progress = out, 1.0
        if out == self.path:
            self.state, self.status = "skipped", "Already under the limit — nothing to do"
        elif out.is_dir():
            parts = [p for p in out.iterdir() if p.suffix != ".bat"]
            self.state = "done"
            self.status = f"Split into {len(parts)} parts, nothing lost — rejoin with JOIN.bat"
            self.size_text = f"{mb(self.orig)}  →  {len(parts)} × ≤{self.limit:g} MB"
        else:
            new = out.stat().st_size
            self.state = "done"
            self.status = f"Saved as {out.name}  ·  {100 - new * 100 / self.orig:.0f}% smaller"
            self.size_text = f"{mb(self.orig)}  →  {mb(new)}"
        self.draw()

    def fail(self, msg):
        self.state, self.progress = "error", 1.0
        self.status = " ".join(msg.split())
        self.draw()

    def open(self, _=None):
        if self.result:
            subprocess.Popen(f'explorer /select,"{self.result}"')

    def draw(self):
        S, w = self.S, self.winfo_width()
        if w < S(200):
            return
        self.delete("all")
        rrect(self, 0, 0, w, self.H, S(10), fill=C["panel"])
        rrect(self, S(12), S(12), S(56), S(56), S(10), fill=self.color)
        self.create_text(S(34), S(34), text=self.badge, font=(FONT, 9, "bold"),
                         fill=C["deep"] if self.color == C["yellow"] else C["white"])

        right = w - S(16)
        if self.result is not None:
            self.btn_bg = rrect(self, right - S(86), S(20), right, S(48), S(6), fill=C["field"], tags="btn")
            self.create_text(right - S(43), S(34), text="Show file", fill=C["text"], font=(FONT, 9, "bold"), tags="btn")
            self.tag_bind("btn", "<Button-1>", self.open)
            self.tag_bind("btn", "<Enter>", lambda e: self.btn_hover(True))
            self.tag_bind("btn", "<Leave>", lambda e: self.btn_hover(False))
            right -= S(100)

        f_small = self.app.font_small
        size_color = C["green"] if self.state == "done" else C["faint"]
        self.create_text(right, S(22), text=self.size_text, anchor="e", fill=size_color, font=f_small)
        name_w = right - S(70) - f_small.measure(self.size_text) - S(14)
        self.create_text(S(70), S(22), anchor="w", fill=C["text"], font=self.app.font_bold,
                         text=fit(self.app.font_bold, self.path.name, name_w))
        status = self.status
        if self.state == "working" and self.progress is not None:
            status += f"  ·  {self.progress * 100:.0f}%"
        self.create_text(S(70), S(40), anchor="w", font=f_small,
                         fill=C["red"] if self.state == "error" else C["muted"],
                         text=fit(f_small, status, right - S(70)))

        x1, x2, y1, y2 = S(70), right, S(51), S(56)
        rrect(self, x1, y1, x2, y2, S(3), fill=C["deep"])
        color = {"working": C["blurple"], "done": C["green"], "skipped": C["green"], "error": C["red"]}.get(self.state)
        if self.state == "working" and self.progress is None:  # unknown length: sliding stripe
            seg = (x2 - x1) * 0.25
            a = x1 + (x2 - x1 + seg) * self.spin - seg
            rrect(self, max(x1, a), y1, min(x2, a + seg), y2, S(3), fill=color)
        elif color and self.progress:
            rrect(self, x1, y1, x1 + max(S(6), (x2 - x1) * self.progress), y2, S(3), fill=color)

    def btn_hover(self, on):
        self.configure(cursor="hand2" if on else "")
        if self.btn_bg:
            self.itemconfigure(self.btn_bg, fill=C["hover"] if on else C["field"])


def folder_size(path):
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


class App:
    def __init__(self, root, core, limit):
        self.root, self.core = root, core
        self.k = root.winfo_fpixels("1i") / 96
        S = self.S
        self.q, self.cards = queue.Queue(), []
        self.font_bold = tkfont.Font(family=FONT, size=10, weight="bold")
        self.font_small = tkfont.Font(family=FONT, size=9)

        root.title("Discord Shrink")
        root.configure(bg=C["bg"])
        root.geometry(f"{S(720)}x{S(780)}")
        root.minsize(S(660), S(620))
        self.set_icon()

        outer = tk.Frame(root, bg=C["bg"])
        outer.pack(fill="both", expand=True, padx=S(24), pady=(S(20), S(14)))

        # header
        hdr = tk.Frame(outer, bg=C["bg"])
        hdr.pack(fill="x", pady=(0, S(16)))
        logo = tk.Canvas(hdr, width=S(48), height=S(48), bg=C["bg"], highlightthickness=0)
        logo.pack(side="left")
        rrect(logo, 0, 0, S(48), S(48), S(14), fill=C["blurple"])
        logo.create_polygon(S(24), S(36), S(13), S(23), S(35), S(23), fill=C["white"])
        logo.create_rectangle(S(21), S(11), S(27), S(24), fill=C["white"], outline="")
        logo.create_rectangle(S(12), S(38), S(36), S(41), fill=C["white"], outline="")
        titles = tk.Frame(hdr, bg=C["bg"])
        titles.pack(side="left", padx=S(14))
        tk.Label(titles, text="Discord Shrink", bg=C["bg"], fg=C["text"], font=(FONT, 17, "bold")).pack(anchor="w")
        tk.Label(titles, text="Fit videos, images and files under Discord's upload limit",
                 bg=C["bg"], fg=C["muted"], font=(FONT, 10)).pack(anchor="w")

        self.settings = Settings(outer, self, limit)
        self.settings.pack(fill="x", pady=(0, S(14)))
        DropZone(outer, self).pack(fill="x", pady=(0, S(18)))

        # file list header
        bar = tk.Frame(outer, bg=C["bg"])
        bar.pack(fill="x", pady=(0, S(8)))
        self.count = tk.Label(bar, text="FILES — 0", bg=C["bg"], fg=C["faint"], font=(FONT, 8, "bold"))
        self.count.pack(side="left")
        clear = tk.Label(bar, text="Clear finished", bg=C["bg"], fg=C["muted"], font=(FONT, 9), cursor="hand2")
        clear.pack(side="right")
        clear.bind("<Button-1>", lambda e: self.clear_finished())
        clear.bind("<Enter>", lambda e: clear.configure(fg=C["text"], font=(FONT, 9, "underline")))
        clear.bind("<Leave>", lambda e: clear.configure(fg=C["muted"], font=(FONT, 9)))

        # scrollable list (wheel-scrolled, no scrollbar)
        self.list = tk.Canvas(outer, bg=C["bg"], highlightthickness=0)
        self.list.pack(fill="both", expand=True)
        self.inner = tk.Frame(self.list, bg=C["bg"])
        win = self.list.create_window(0, 0, window=self.inner, anchor="nw")
        self.list.bind("<Configure>", lambda e: self.list.itemconfigure(win, width=e.width))
        self.inner.bind("<Configure>", lambda e: self.list.configure(scrollregion=self.list.bbox("all")))
        root.bind_all("<MouseWheel>", self.on_wheel)
        self.empty = tk.Label(self.inner, text="Nothing here yet. Drop something in to get started.",
                              bg=C["bg"], fg=C["faint"], font=(FONT, 10))
        self.empty.pack(pady=S(28))

        if core.find_tool("ffmpeg"):
            foot, color = "Saved next to the original as name_discord  ·  ffmpeg ready", C["faint"]
        else:
            foot, color = "ffmpeg not found: run Setup.bat once so videos can be compressed", C["yellow"]
        self.footer = tk.Label(outer, text=foot, bg=C["bg"], fg=color, font=(FONT, 8), anchor="w")
        self.footer.pack(fill="x", pady=(S(8), 0))

        threading.Thread(target=self.worker, daemon=True).start()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.animate()

    def close(self):
        """Stop a running encode and remove its half-written output before quitting."""
        proc = self.core.ACTIVE.get("proc")
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait()
            for card in self.cards:
                if card.state == "working":
                    partial = card.path.with_name(card.path.stem + "_discord.mp4")
                    if partial.is_file():
                        partial.unlink()
        self.root.destroy()

    def S(self, v):
        return int(round(v * self.k))

    def set_icon(self):
        try:
            from PIL import Image, ImageDraw, ImageTk
            im = Image.new("RGBA", (64, 64))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle((0, 0, 63, 63), 18, fill=C["blurple"])
            d.polygon([(32, 48), (17, 31), (47, 31)], fill="white")
            d.rectangle((28, 14, 36, 32), fill="white")
            d.rectangle((16, 51, 48, 55), fill="white")
            self.icon = ImageTk.PhotoImage(im)
            self.root.iconphoto(True, self.icon)
        except Exception:
            pass

    def ui(self, fn, *args):
        self.root.after(0, fn, *args)

    def browse(self):
        files = filedialog.askopenfilenames(parent=self.root, title="Pick files to shrink")
        if files:
            self.add_files(files)

    def add_files(self, paths):
        limit = self.settings.limit()
        if not limit:
            self.footer.configure(text="Pick an upload limit first (or type a number in Custom).", fg=C["red"])
            return
        for p in paths:
            p = Path(p)
            if not p.exists():
                continue
            card = FileCard(self.inner, self, p, limit, self.settings.toggle.value)
            card.pack(fill="x", pady=(0, self.S(8)))
            self.cards.append(card)
            self.q.put(card)
        self.refresh_count()

    def clear_finished(self):
        for card in [c for c in self.cards if c.state in ("done", "skipped", "error")]:
            card.destroy()
            self.cards.remove(card)
        self.refresh_count()

    def refresh_count(self):
        self.count.configure(text=f"FILES — {len(self.cards)}")
        if self.cards:
            self.empty.pack_forget()
        else:
            self.empty.pack(pady=self.S(28))

    def on_wheel(self, e):
        if self.inner.winfo_height() > self.list.winfo_height():
            self.list.yview_scroll(-int(e.delta / 120), "units")

    def animate(self):
        for card in self.cards:
            if card.state == "working" and card.progress is None:
                card.spin = (card.spin + 0.015) % 1.0
                card.draw()
        self.root.after(30, self.animate)

    def worker(self):
        while True:
            card = self.q.get()
            self.ui(card.start)
            log = lambda m, c=card: m.startswith("  ") and self.ui(c.set_status, m.strip())
            progress = lambda p, c=card: self.ui(c.set_progress, p)
            try:
                out = self.core.shrink(card.path, card.limit, log, card.downscale, progress)
                self.ui(card.finish, Path(out))
            except Exception as e:
                self.ui(card.fail, str(e))


def enable_drop(root, callback):
    """Let files be dragged from Explorer onto the window (plain Win32, no extra packages)."""
    from ctypes import wintypes
    user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user32.GetParent.argtypes, user32.GetParent.restype = [wintypes.HWND], wintypes.HWND
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_wchar_p, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT
    shell32.DragFinish.argtypes = [ctypes.c_void_p]
    shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]

    hwnd = user32.GetParent(root.winfo_id())
    old = None

    def proc(h, msg, wp, lp):
        if msg == 0x0233:  # WM_DROPFILES
            files = []
            for i in range(shell32.DragQueryFileW(wp, 0xFFFFFFFF, None, 0)):
                n = shell32.DragQueryFileW(wp, i, None, 0) + 1
                buf = ctypes.create_unicode_buffer(n)
                shell32.DragQueryFileW(wp, i, buf, n)
                files.append(buf.value)
            shell32.DragFinish(wp)
            root.after(0, callback, files)
            return 0
        return user32.CallWindowProcW(old, h, msg, wp, lp)

    root._drop_proc = WNDPROC(proc)  # keep a reference so it isn't garbage-collected
    old = user32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(root._drop_proc, ctypes.c_void_p))
    shell32.DragAcceptFiles(hwnd, True)


def style_titlebar(root):
    """Dark Windows 11 title bar to match the app."""
    hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
    dwm = ctypes.windll.dwmapi
    dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(1)), 4)  # immersive dark mode
    r, g, b = (int(C["deep"][i:i + 2], 16) for i in (1, 3, 5))
    dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(ctypes.c_int(b << 16 | g << 8 | r)), 4)  # caption colour


def build(core, limit):
    if os.name == "nt":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    app = App(root, core, limit)
    root.update_idletasks()
    if os.name == "nt":
        for setup in (style_titlebar, lambda r: enable_drop(r, app.add_files)):
            try:
                setup(root)
            except Exception:
                pass
    return root, app


def run(core, limit):
    root, _ = build(core, limit)
    root.mainloop()
