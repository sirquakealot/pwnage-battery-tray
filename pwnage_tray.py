#!/usr/bin/env python3
"""
pwnage_tray.py  --  Batteriestand der Pwnage StormBreaker Max CF in der Windows-Taskleiste

Setup:
    pip install hidapi pystray pillow

Start:
    pythonw pwnage_tray.py              (ohne Konsolenfenster)
    python  pwnage_tray.py --once       (einmal abfragen und ausgeben)
    python  pwnage_tray.py --interval 120

Protokoll (selbst ermittelt):
    Interface : VID 0x3662 / PID 0x2004, MI_02, usage_page 0xffff, usage 0x00
    Anfrage   : Feature-Report 0 mit  a1 00 02 02 00 83 00 00
    Antwort   : a1 00 02 02 00 83 00 <XX>   ->  XX = Ladestand in Prozent
"""

import argparse
import os
import sys
import threading
import time
import traceback

try:
    import winreg  # nur unter Windows vorhanden
except ImportError:
    winreg = None


# --------------------------------------------------- Absturzprotokoll

def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


LOG_PATH = os.path.join(app_dir(), "pwnage_tray_error.log")


def log_crash(exc):
    """Ohne Konsole gibt es kein stderr - Fehler landen sonst im Nichts."""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write("\n" + "=" * 60 + "\n")
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
            fh.write("".join(traceback.format_exception(
                type(exc), exc, exc.__traceback__)))
    except Exception:
        pass


# Unter --noconsole sind stdout/stderr None. Manche Bibliotheken schreiben
# trotzdem hinein und reissen den Prozess kommentarlos mit.
if getattr(sys, "frozen", False):
    for _name in ("stdout", "stderr"):
        if getattr(sys, _name, None) is None:
            setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))

try:
    import hid
except Exception as _e:          # ImportError, aber auch fehlende hidapi.dll
    log_crash(_e)
    sys.exit("hid nicht ladbar. 'pip install hidapi' - im exe-Build fehlt sonst "
             "die hidapi.dll, siehe --collect-all hid")

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except Exception as _e:
    log_crash(_e)
    sys.exit("Fehlt: pip install pystray pillow")


VID, PID = 0x3662, 0x2004
REQUEST = [0xA1, 0x00, 0x02, 0x02, 0x00, 0x83, 0x00, 0x00]
BATTERY_OFFSET = 7
REPORT_SIZE = 65

ICON_PX = 64
COLOR_OK = (150, 190, 158)    # gedaempftes gruen   > 60
COLOR_MID = (206, 174, 120)   # gedaempftes ocker   30-60
COLOR_LOW = (200, 130, 125)   # gedaempftes rot     < 30
COLOR_NONE = (110, 110, 110)  # grau, nur fuer das Fragezeichen-Feld


# ------------------------------------------------------------------ HID

def read_battery():
    """Ladestand in Prozent, oder None wenn die Maus nicht erreichbar ist."""
    handle = None
    try:
        path = None
        for d in hid.enumerate(VID, PID):
            if d.get("usage_page") == 0xFFFF and d.get("usage") == 0x00:
                path = d["path"]
                break
        if path is None:
            return None

        handle = hid.device()
        handle.open_path(path)

        buf = [0x00] + REQUEST
        buf += [0x00] * (REPORT_SIZE - len(buf))
        handle.send_feature_report(bytes(buf))
        time.sleep(0.06)

        raw = bytes(handle.get_feature_report(0, REPORT_SIZE))
        frame = raw[1:] if raw and raw[0] == 0 else raw

        if len(frame) <= BATTERY_OFFSET:
            return None
        pct = frame[BATTERY_OFFSET]
        return pct if 0 < pct <= 100 else None
    except Exception:
        return None
    finally:
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass


# ------------------------------------------------------------------ Icon

def pick_color(pct):
    if pct is None:
        return COLOR_NONE
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


def make_icon(pct):
    """Nur die Zahl, gedaempft eingefaerbt. Nur der Nicht-verbunden-Zustand
    bekommt weiterhin das graue Feld mit Fragezeichen."""
    img = Image.new("RGBA", (ICON_PX, ICON_PX), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    if pct is None:
        d.rounded_rectangle([0, 0, ICON_PX - 1, ICON_PX - 1], radius=14, fill=COLOR_NONE)
        text, fill, stroke = "?", (255, 255, 255, 255), None
        size = 44
    else:
        text, fill, stroke = str(pct), pick_color(pct) + (255,), (0, 0, 0, 110)
        size = 42 if len(text) >= 3 else 54

    sw = 0 if stroke is None else 2

    # Schrift so weit verkleinern, dass sie sicher ins Icon passt ("100").
    while True:
        font = load_font(size)
        box = d.textbbox((0, 0), text, font=font, stroke_width=sw)
        w, h = box[2] - box[0], box[3] - box[1]
        if (w <= ICON_PX - 2 and h <= ICON_PX - 2) or size <= 12:
            break
        size -= 2

    pos = ((ICON_PX - w) / 2 - box[0], (ICON_PX - h) / 2 - box[1])

    # Der dunkle Rand haelt die Zahl auch auf heller Taskleiste lesbar.
    d.text(pos, text, font=font, fill=fill, stroke_width=sw, stroke_fill=stroke)
    return img


# ------------------------------------------------------------------ Autostart

APP_NAME = "PwnageBattery"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_command():
    """Befehlszeile, die Windows beim Anmelden ausfuehren soll."""
    if getattr(sys, "frozen", False):          # als .exe gebaut
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
    """Wenn der Eintrag existiert, aber auf einen alten Pfad zeigt (Ordner
    verschoben, neu gebaut), still auf den aktuellen Pfad umbiegen."""
    if winreg is None or not autostart_get():
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            current, _ = winreg.QueryValueEx(key, APP_NAME)
        if current != autostart_command():
            autostart_set(True)
    except OSError:
        pass


# ------------------------------------------------------------------ Tray

class Tray:
    def __init__(self, interval):
        self.interval = interval
        self.pct = None
        self.updated = None
        self.stop = threading.Event()
        self.wake = threading.Event()

        self.icon = pystray.Icon(
            "pwnage_battery",
            make_icon(None),
            "Pwnage - wird abgefragt...",
            menu=pystray.Menu(
                pystray.MenuItem(self._status_text, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Jetzt aktualisieren", self._on_refresh),
                pystray.MenuItem("Mit Windows starten", self._on_autostart,
                                 checked=lambda _: autostart_get()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Beenden", self._on_quit),
            ),
        )

    def _status_text(self, _=None):
        if self.pct is None:
            return "Maus nicht verbunden"
        return f"StormBreaker Max CF: {self.pct}%  (Stand {self.updated})"

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
        pct = read_battery()
        self.pct = pct
        self.updated = time.strftime("%H:%M")
        self.icon.icon = make_icon(pct)
        self.icon.title = ("Pwnage StormBreaker Max CF\nMaus nicht verbunden"
                           if pct is None else
                           f"Pwnage StormBreaker Max CF\nAkku: {pct}%  (Stand {self.updated})")
        self.icon.update_menu()

    def _loop(self, icon):
        # pystray fuehrt setup in einem eigenen Thread aus und schluckt
        # Ausnahmen - ohne dieses try bleibt ein Fehler hier unsichtbar.
        try:
            icon.visible = True
            while not self.stop.is_set():
                self._refresh()
                # frueh aufwachen, wenn "Jetzt aktualisieren" geklickt wurde
                self.wake.wait(timeout=self.interval)
                self.wake.clear()
        except Exception as exc:
            log_crash(exc)
            icon.stop()

    def run(self):
        self.icon.run(setup=self._loop)


# ------------------------------------------------------------------ main

def main():
    p = argparse.ArgumentParser(description="Pwnage StormBreaker Max CF Akku-Anzeige")
    p.add_argument("--interval", type=int, default=300,
                   help="Sekunden zwischen Abfragen (Standard 300)")
    p.add_argument("--once", action="store_true",
                   help="einmal abfragen, ausgeben, beenden")
    a = p.parse_args()

    if a.once:
        pct = read_battery()
        print("Maus nicht verbunden" if pct is None else f"Akku: {pct}%")
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
