#!/usr/bin/env python3
"""Builds the single-file Brochacho program for the OS you run it on.

    pip install pyinstaller certifi
    python build/build.py            ->  dist/Brochacho.exe (Windows) or dist/brochacho (macOS)
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
win = sys.platform == "win32"
cmd = [
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
    "--name", "Brochacho" if win else "brochacho",
    "--add-data", f"{ROOT / 'brochacho.md'}:.",
    "--add-data", f"{ROOT / 'docs' / 'brochacho.ico'}:docs",
    "--collect-data", "certifi",
    "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "work"), "--specpath", str(ROOT / "build" / "work"),
]
if win:
    cmd += ["--icon", str(ROOT / "docs" / "brochacho.ico")]
cmd.append(str(ROOT / "app" / "brochacho.py"))
sys.exit(subprocess.call(cmd))
