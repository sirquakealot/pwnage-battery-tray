<p align="center">
  <img src="https://github.com/sirquakealot/pwnage-battery-tray/releases/download/1.1/pwnage.jpg" alt="Logo">
</p>

<h1 align="center">Pwnage Battery Tray</h1>

<p align="center">
  Battery percentage for the Pwnage StormBreaker Max CF, right in the Windows system tray.
</p>

<p align="center">
  <img src="https://github.com/sirquakealot/pwnage-battery-tray/releases/download/1.1/stormbreakermaxcf.jpg" alt="Pwnage StormBreaker Max CF">
</p>

---

Pwnage ships a browser-based Drivers Hub. It shows your battery level, but only while
the tab is open, and it grabs the device while it runs. There's no tray app and no
official API.

So I read the protocol off the device and wrote one.

<p align="center">
  <img src="https://github.com/sirquakealot/pwnage-battery-tray/releases/download/1.1/tray.jpg" alt="Tray icon">
</p>

## What it does

- Battery percentage as the tray icon itself, no hover needed
- Muted green / amber / red, with a grey `?` when the mouse is asleep or the dongle is out
- Right-click: refresh now, toggle "Start with Windows", quit
- Polls every 5 minutes, configurable
- Opens the HID device only for the split second it takes to read, so the Drivers Hub
  still works when you need it

## Run it

```
pip install hidapi pystray pillow
pythonw pwnage_tray.py
```

`pythonw` instead of `python` keeps the console window away.

```
python pwnage_tray.py --once           # print the value and exit
python pwnage_tray.py --interval 120   # poll every 2 minutes
```

## The protocol

This part was reverse engineered — the mouse enumerates five HID collections and only
one of them answers.

| | |
|---|---|
| Device | VID `0x3662` / PID `0x2004`, reports as *Pwnage Wireless Gaming Mouse V3* |
| Interface | `MI_02`, usage page `0xffff`, usage `0x00` |
| Request | feature report `0`: `a1 00 02 02 00 83 00 00` |
| Response | `a1 00 02 02 00 83 00 XX` — byte 7 is the charge level in percent |

The device echoes your request frame back and fills in byte 7. Reading without writing
first returns whatever was left in the buffer, which is how you end up with a number
that looks right and never changes.

Found by dumping every readable feature report, then confirming byte 7 tracked a real
charge cycle. `pwnage_hid_scan.py` and `pwnage_battery.py` in this repo are the two
throwaway tools that got there — kept in the repo so anyone can repeat this on another
model.

## Other Pwnage mice — untested, help wanted

**I only own the StormBreaker Max CF, so that's the only model this is confirmed on.**

That said, there's a reasonable chance it works on more. Pwnage configures the
[Zenblade, Zenblade v2, StormBreaker v2, StormBreaker Max CF, Trinity CF and
Symm 3](https://pwnage.com/pages/drivers) through the same browser-based Drivers Hub —
one app, one JavaScript bundle, so most likely one protocol family behind it. If the
`0x83` command is shared across those models, this tool works on all of them once it
knows the right product ID.

Older models are a different story. The Ultra Custom line, Symm 2 and Alpha use the old
downloadable driver instead of the hub, which points at a different OEM platform and
probably a different protocol. I wouldn't expect those to work.

Right now `pwnage_tray.py` has the IDs hardcoded (`0x3662` / `0x2004`), so a different
model won't even be detected.

**If you own any other Pwnage mouse, I'd really appreciate a quick test:**

```
pip install hidapi
python pwnage_hid_scan.py      # lists your mouse and its interfaces
python pwnage_battery.py       # tries the battery command
```

Open an issue with your model name and the output of both, working or not. Negative
results are just as useful. With a couple of reports I can drop the hardcoded IDs and
make it detect any supported mouse automatically.

## Build a standalone .exe

```
pip install pyinstaller

pyinstaller --noconsole --onedir --name "PwnageBattery" --icon "pwnage.ico" --add-data "pwnage.ico;." --hidden-import "pystray._win32" --collect-binaries "hid" --clean pwnage_tray.py
```

Lands in `dist\PwnageBattery\`. Keep the folder together, or swap `--onedir` for
`--onefile` if you'd rather have a single file and don't mind the slower start.

`--collect-binaries hid` is the one you can't skip. Without it `hidapi.dll` never makes
it into the build and the exe dies silently on launch.

## Notes

- Windows only. The autostart toggle writes to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`,
  no admin rights needed. It also fixes its own path on startup, so you can move or
  rebuild the folder without breaking it.
- Grey `?` while the Drivers Hub is open is expected — it holds the device.
- A sleeping mouse doesn't answer. Move it once.
- Colors live at the top of `pwnage_tray.py` if you want different ones.

## License

MIT
