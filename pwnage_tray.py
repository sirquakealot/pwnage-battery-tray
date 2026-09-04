#!/usr/bin/env python3
"""
pwnage_battery.py  --  Batterie-Kommando der Pwnage StormBreaker Max CF finden

    python pwnage_battery.py            -> Kandidaten durchprobieren
    python pwnage_battery.py --sweep    -> alle Opcodes 0x80..0x8f abklopfen

Maus per Dongle verbunden, Drivers-Hub-Tab geschlossen.
"""

import argparse
import sys
import time

try:
    import hid
except ImportError:
    sys.exit("Fehlt: pip install hidapi")

VID, PID = 0x3662, 0x2004


def open_config():
    for d in hid.enumerate(VID, PID):
        if d.get("usage_page") == 0xFFFF and d.get("usage") == 0x00:
            h = hid.device()
            h.open_path(d["path"])
            return h
    sys.exit("Config-Interface nicht gefunden. Maus per Dongle verbunden? Hub-Tab zu?")


def exchange(h, payload, size=65):
    """payload (ohne Report-ID) senden, danach Antwort lesen."""
    buf = [0x00] + list(payload)
    buf += [0x00] * (size - len(buf))
    buf = buf[:size]
    try:
        h.send_feature_report(bytes(buf))
    except Exception as e:
        return None, f"send fehlgeschlagen: {e}"
    time.sleep(0.06)
    try:
        raw = bytes(h.get_feature_report(0, size))
    except Exception as e:
        return None, f"read fehlgeschlagen: {e}"
    return (raw[1:] if raw and raw[0] == 0 else raw), None


def show(label, sent, got, err):
    print(f"\n--- {label}")
    print(f"  gesendet : {bytes(sent).hex(' ')}")
    if err:
        print(f"  {err}")
        return None
    if not any(got):
        print("  Antwort  : (nur Nullen)")
        return None
    print(f"  Antwort  : {got[:16].hex(' ')}")
    hits = [(i, b) for i, b in enumerate(got[:16]) if 1 <= b <= 100]
    if hits:
        print("  Prozent-Kandidaten: " + ", ".join(f"Byte{i}={b}" for i, b in hits))
    return got


CANDIDATES = [
    ("Echo des beobachteten Frames, Datenbyte genullt", [0xA1, 0x00, 0x02, 0x02, 0x00, 0x83, 0x00, 0x00]),
    ("Exakt der beobachtete Frame",                     [0xA1, 0x00, 0x02, 0x02, 0x00, 0x83, 0x00, 0x34]),
    ("Kurzform ohne Datenbytes",                        [0xA1, 0x00, 0x02, 0x02, 0x00, 0x83]),
    ("Ohne fuehrendes a1",                              [0x02, 0x02, 0x00, 0x83, 0x00, 0x00]),
    ("Header a1 mit Laenge 02",                         [0xA1, 0x02, 0x83, 0x00]),
]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sweep", action="store_true", help="Opcodes 0x80..0x8f durchprobieren")
    a = p.parse_args()

    h = open_config()
    print(f"Config-Interface offen ({VID:#06x}:{PID:#06x})")

    try:
        if a.sweep:
            print("\nSweep ueber Opcode-Position 5 (0x80..0x8f):")
            for op in range(0x80, 0x90):
                frame = [0xA1, 0x00, 0x02, 0x02, 0x00, op, 0x00, 0x00]
                got, err = exchange(h, frame)
                show(f"Opcode {op:#04x}", frame, got, err)
        else:
            for label, frame in CANDIDATES:
                for size in (65, 33, 17):
                    got, err = exchange(h, frame, size)
                    if got is not None and any(got):
                        show(f"{label}  (Reportgroesse {size})", frame, got, err)
                        break
                else:
                    show(label, frame, b"", "keine Antwort bei 65/33/17 Byte")
    finally:
        h.close()

    print("\n" + "=" * 70)
    print("Gesucht: eine Antwort, in der ein Byte plausibel deinem Ladestand entspricht.")
    print("Schick mir den kompletten Output.")


if __name__ == "__main__":
    main()