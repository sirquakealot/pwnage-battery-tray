#!/usr/bin/env python3
"""
pwnage_tray.py -- battery level of the Pwnage StormBreaker Max CF in the Windows tray.

    pip install hidapi pystray pillow

    pythonw pwnage_tray.py            run in the tray, no console window
    python  pwnage_tray.py --once     print the value and exit
    python  pwnage_tray.py --interval 120

Protocol (reverse engineered, see README):
    Interface : VID 0x3662 / PID 0x2004, MI_02, usage page 0xffff, usage 0x00
    Request   : feature report 0, payload  a1 00 02 02 00 83 00 00
    Response  : a1 00 02 02 00 83 CC XX
                CC = 01 while charging, 00 otherwise
                XX = charge level in percent
"""

import argparse
import os
import sys
import threading
import time
import traceback

try:
    import winreg
except ImportError:
    winreg = None


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


LOG_PATH = os.path.join(app_dir(), "pwnage_tray_error.log")


def log_crash(exc):
    """A --noconsole build has no stderr, so errors would vanish silently."""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write("\n" + "=" * 60 + "\n")
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
            fh.write("".join(traceback.format_exception(
                type(exc), exc, exc.__traceback__)))
    except Exception:
        pass


# Frozen without a console, sys.stdout and sys.stderr are None. Libraries that
# write to them anyway will take the whole process down without a trace.
if getattr(sys, "frozen", False):
    for _name in ("stdout", "stderr"):
        if getattr(sys, _name, None) is None:
            setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))

try:
    import hid
except Exception as _e:
    log_crash(_e)
    sys.exit("Cannot load hid. Run 'pip install hidapi'. In a PyInstaller build "
             "this usually means hidapi.dll is missing -- see --collect-all hid")

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except Exception as _e:
    log_crash(_e)
    sys.exit("Missing dependency: pip install pystray pillow")


VID, PID = 0x3662, 0x2004
REQUEST = [0xA1, 0x00, 0x02, 0x02, 0x00, 0x83, 0x00, 0x00]
CHARGING_OFFSET = 6
BATTERY_OFFSET = 7
REPORT_SIZE = 65

# A sleeping mouse doesn't answer, so after a failed read poll again soon
# instead of sitting on "?" for the full interval.
RETRY_INTERVAL = 15

ICON_PX = 64
COLOR_OK = (150, 190, 158)      # green   above 60
COLOR_MID = (206, 174, 120)     # amber   30-60
COLOR_LOW = (200, 130, 125)     # red     below 30
COLOR_CHARGE = (135, 175, 205)  # blue    charging
COLOR_NONE = (110, 110, 110)    # grey    disconnected


# ------------------------------------------------------------------ device

def read_battery():
    """Return (percent, charging). (None, False) if the mouse can't be reached."""
    handle = None
    try:
        path = None
        for d in hid.enumerate(VID, PID):
            if d.get("usage_page") == 0xFFFF and d.get("usage") == 0x00:
                path = d["path"]
                break
        if path is None:
            return None, False

        handle = hid.device()
        handle.open_path(path)

        # The device only refreshes its response buffer when asked. Reading
        # without writing first returns a stale value that never changes.
        buf = [0x00] + REQUEST
        buf += [0x00] * (REPORT_SIZE - len(buf))
        handle.send_feature_report(bytes(buf))
        time.sleep(0.06)

        raw = bytes(handle.get_feature_report(0, REPORT_SIZE))
        frame = raw[1:] if raw and raw[0] == 0 else raw

        if len(frame) <= BATTERY_OFFSET:
            return None, False
        pct = frame[BATTERY_OFFSET]
        charging = frame[CHARGING_OFFSET] == 0x01
        return (pct if 0 < pct <= 100 else None), charging
    except Exception:
        return None, False
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass


# ------------------------------------------------------------------ icon

def pick_color(pct, charging=False):
    if pct is None:
        return COLOR_NONE
    if charging:
        return COLOR_CHARGE
    if pct > 60:
        return COLOR_OK
    if pct >= 30:
        return COLOR_MID
    return COLOR_LOW


def load_font(size):
    for name in ("segoeuib.ttf", "arialbd.ttf", "seguisb.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def make_icon(pct, charging=False):
    """Bare number, tinted. Only the disconnected state gets a filled tile."""
    img = Image.new("RGBA", (ICON_PX, ICON_PX), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if pct is None:
        d.rounded_rectangle([0, 0, ICON_PX - 1, ICON_PX - 1], radius=14, fill=COLOR_NONE)
        text, fill, stroke = "?", (255, 255, 255, 255), None
        size = 44
    else:
        text = str(pct)
        fill = pick_color(pct, charging) + (255,)
        stroke = (0, 0, 0, 110)
        size = 42 if len(text) >= 3 else 54

    sw = 0 if stroke is None else 2

    # Shrink until it fits, so "100" doesn't run off the edge.
    while True:
        font = load_font(size)
        box = d.textbbox((0, 0), text, font=font, stroke_width=sw)
        w, h = box[2] - box[0], box[3] - box[1]
        if (w <= ICON_PX - 2 and h <= ICON_PX - 2) or size <= 12:
            break
        size -= 2

    pos = ((ICON_PX - w) / 2 - box[0], (ICON_PX - h) / 2 - box[1])
    # The dark outline keeps the muted colors readable on a light taskbar.
    d.text(pos, text, font=font, fill=fill, stroke_width=sw, stroke_fill=stroke)
    return img


# ------------------------------------------------------------------ autostart

APP_NAME = "PwnageBattery"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    return f'"{pythonw}" "{os.path.abspath(__file__)}"'


def autostart_get():
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except OSError:
        return False


def autostart_set(enabled):
    if winreg is None:
        return
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def autostart_repair():
    """Silently repoint the registry entry after the folder moved or was rebuilt."""
    if winreg is None or not autostart_get():
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            current, _ = winreg.QueryValueEx(key, APP_NAME)
        if current != autostart_command():
            autostart_set(True)
    except OSError:
        pass


# ------------------------------------------------------------------ tray

class Tray:
    def __init__(self, interval):
        self.interval = interval
        self.pct = None
        self.charging = False
        self.updated = None
        self.stop = threading.Event()
        self.wake = threading.Event()

        self.icon = pystray.Icon(
            "pwnage_battery",
            make_icon(None),
            "Pwnage - reading...",
            menu=pystray.Menu(
                pystray.MenuItem(self._status_text, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Refresh now", self._on_refresh),
                pystray.MenuItem("Start with Windows", self._on_autostart,
                                 checked=lambda _: autostart_get()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._on_quit),
            ),
        )

    def _status_text(self, _=None):
        if self.pct is None:
            return "Mouse not connected"
        state = " - charging" if self.charging else ""
        return f"StormBreaker Max CF: {self.pct}%{state}  (as of {self.updated})"

    def _on_refresh(self, *_):
        self.wake.set()

    def _on_autostart(self, *_):
        autostart_set(not autostart_get())
        self.icon.update_menu()

    def _on_quit(self, *_):
        self.stop.set()
        self.wake.set()
        self.icon.stop()

    def _refresh(self):
        pct, charging = read_battery()
        self.pct, self.charging = pct, charging
        self.updated = time.strftime("%H:%M")
        self.icon.icon = make_icon(pct, charging)
        if pct is None:
            self.icon.title = "Pwnage StormBreaker Max CF\nMouse not connected"
        else:
            state = "  (charging)" if charging else ""
            self.icon.title = (f"Pwnage StormBreaker Max CF\n"
                               f"Battery: {pct}%{state}\nAs of {self.updated}")
        self.icon.update_menu()

    def _loop(self, icon):
        # pystray runs setup on its own thread and swallows exceptions,
        # so anything failing in here would be invisible without this.
        try:
            icon.visible = True
            while not self.stop.is_set():
                self._refresh()
                delay = self.interval if self.pct is not None else RETRY_INTERVAL
                self.wake.wait(timeout=delay)
                self.wake.clear()
        except Exception as exc:
            log_crash(exc)
            icon.stop()

    def run(self):
        self.icon.run(setup=self._loop)


# ------------------------------------------------------------------ main

def main():
    p = argparse.ArgumentParser(description="Pwnage StormBreaker Max CF battery tray")
    p.add_argument("--interval", type=int, default=300,
                   help="seconds between reads (default 300)")
    p.add_argument("--once", action="store_true",
                   help="print the value once and exit")
    a = p.parse_args()

    if a.once:
        pct, charging = read_battery()
        if pct is None:
            print("Mouse not connected")
        else:
            print(f"Battery: {pct}%" + ("  (charging)" if charging else ""))
        return

    autostart_repair()
    Tray(max(30, a.interval)).run()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as _exc:
        log_crash(_exc)
        raise