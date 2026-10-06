#!/usr/bin/env python3
"""Send a Wake-on-LAN magic packet (macOS/Linux; standard library only).

    wake.py pc                   # name from ~/.brochacho/machines.json
    wake.py A8:A1:59:39:A0:AF    # or a MAC address
    wake.py --list
"""
import json
import re
import socket
import sys
from pathlib import Path

CFG = Path.home() / ".brochacho" / "machines.json"
MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:-]?){5}[0-9A-Fa-f]{2}$")


def load():
    return json.loads(CFG.read_text()) if CFG.exists() else {}


def main(argv):
    machines = load()
    if len(argv) < 2 or argv[1] == "--list":
        for name, m in machines.items():
            aka = f" aka {', '.join(m['aliases'])}" if m.get("aliases") else ""
            print(f"{name:<12} {m.get('mac')}  ({m.get('os', '?')}){aka}")
        if not machines:
            print(f"No machines yet in {CFG}")
        return 0

    target = argv[1]
    # Match a machine by name or by one of its "aliases".
    key = target.lower()
    entry = machines.get(key) or next((m for m in machines.values() if key in m.get("aliases", [])), None)
    if entry:
        mac, broadcast = entry["mac"], entry.get("broadcast", "255.255.255.255")
    elif MAC_RE.match(target):
        mac, broadcast = target, "255.255.255.255"
    else:
        print(f"Unknown machine '{target}'. Known: {', '.join(machines) or 'none'}", file=sys.stderr)
        return 1

    # Magic packet: 6 x 0xFF, then the MAC 16 times.
    packet = b"\xff" * 6 + bytes.fromhex(re.sub(r"[:-]", "", mac)) * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for addr in dict.fromkeys([broadcast, "255.255.255.255"]):
            for port in (9, 7):
                s.sendto(packet, (addr, port))
    print(f"Sent magic packet to {mac} via {broadcast}. Give it ~20 s to wake.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
