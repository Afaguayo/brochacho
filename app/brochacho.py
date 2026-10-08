#!/usr/bin/env python3
"""Brochacho: text your computer from Discord, it texts back.

One program for Windows and macOS. Double-click it (Brochacho.exe / brochacho) and it walks you
through setup the first time, then starts Brochacho every time after that.

    brochacho                  first run: setup wizard; afterwards: a small menu (Enter = start)
    brochacho start            start Brochacho (what the Desktop shortcut runs)
    brochacho setup            run the setup wizard again (your answers are kept as defaults)
    brochacho doctor           check every requirement and say what to fix
    brochacho pair             approve your Discord account with the code the bot sends you
    brochacho wake NAME        Wake-on-LAN another machine (brochacho wake --list)
    brochacho transcribe FILE  turn a voice message into text (used by Claude)
    brochacho uninstall        remove shortcuts and auto-start (keeps your token and settings)

Standard library only, Python 3.9+. Built into a single file with PyInstaller (see build/).
"""
from __future__ import annotations

import argparse
import base64
import getpass
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import wave
import webbrowser
from pathlib import Path

VERSION = "2.0.0"
IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
FROZEN = getattr(sys, "frozen", False)
RES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))  # bundled data files

HOME = Path.home()
CFG_DIR = HOME / ".brochacho"
CONFIG = CFG_DIR / "config.json"
MACHINES = CFG_DIR / "machines.json"
SETTINGS_FILE = CFG_DIR / "brochacho.settings.json"
PERSONA_FILE = CFG_DIR / "persona.md"
DISCORD_DIR = HOME / ".claude" / "channels" / "discord"
ENV_FILE = DISCORD_DIR / ".env"
ACCESS_FILE = DISCORD_DIR / "access.json"
INBOX = DISCORD_DIR / "inbox"

PLUGIN = "discord@claude-plugins-official"
MARKETPLACE = "anthropics/claude-plugins-official"
MCP_PREFIX = "mcp__plugin_discord_discord"   # tools of the Discord plugin's MCP server
# View Channels, Send Messages, Send in Threads, Read History, Attach Files, Add Reactions.
INVITE_PERMS = 274878008384
INTENT_MESSAGE_CONTENT = (1 << 18) | (1 << 19)   # GATEWAY_MESSAGE_CONTENT(_LIMITED)
WHISPER = "whisper-ctranslate2==0.5.8"            # local speech-to-text, run through uvx
WHISPER_PYTHON = "3.12"

MODES = {
    # key: (label, claude flags, explanation)
    "auto": ("Hands-free (recommended)", ["--permission-mode", "auto"],
             "Claude just does the work. A built-in safety check still stops risky actions\n"
             "     (deleting lots of files, leaking secrets, force-pushing) and asks you in Discord."),
    "ask": ("Ask before commands", ["--permission-mode", "acceptEdits"],
            "File edits and everyday commands (git, ls, ...) run on their own;\n"
            "     anything else sends an Allow / Deny button to your Discord."),
    "full": ("Full trust (no prompts at all)", ["--dangerously-skip-permissions"],
             "Never asks. Anyone who gets into your Discord account can run anything on this\n"
             "     computer. Only pick this if your Discord has 2FA and the bot is locked to you."),
}


# ----------------------------------------------------------------------------------------- output
def _enable_console():
    if IS_WIN:
        os.system("")  # turns on ANSI colors in the Windows console
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            if FROZEN:  # don't let the .exe's bundled DLL folder leak into claude/uvx/bun
                ctypes.windll.kernel32.SetDllDirectoryW(None)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def c(text, color):
    codes = {"red": 31, "green": 32, "yellow": 33, "blue": 34, "cyan": 36, "bold": 1, "dim": 2}
    if not sys.stdout.isatty():
        return text
    return f"\033[{codes[color]}m{text}\033[0m"


def say(text="", color=None):
    print(c(text, color) if color else text, flush=True)


def ok(text):
    say(f"  {c('OK', 'green')}   {text}")


def warn(text):
    say(f"  {c('!!', 'yellow')}   {text}")


def bad(text):
    say(f"  {c('NO', 'red')}   {text}")


def ask(prompt, default=""):
    hint = f" [{default}]" if default else ""
    try:
        answer = input(f"  > {prompt}{hint}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def yes(prompt, default=True):
    hint = "Y/n" if default else "y/N"
    while True:
        try:
            answer = input(f"  > {prompt} [{hint}]: ").strip().lower()
        except EOFError:
            return default
        if not answer:
            return default
        if answer in ("y", "yes", "s", "si"):
            return True
        if answer in ("n", "no"):
            return False


def pause(msg="Press Enter to continue"):
    try:
        input(f"  {c(msg, 'dim')} ")
    except EOFError:
        pass


def banner(title):
    say()
    say("  " + "=" * 62, "cyan")
    say(f"  {title}", "bold")
    say("  " + "=" * 62, "cyan")


# ------------------------------------------------------------------------------------- state/io
def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def load_cfg():
    return read_json(CONFIG, {})


def save_cfg(cfg):
    write_json(CONFIG, cfg)


def read_token():
    if os.environ.get("DISCORD_BOT_TOKEN"):
        return os.environ["DISCORD_BOT_TOKEN"].strip()
    try:
        for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("DISCORD_BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


# ------------------------------------------------------------------------------- tools and PATH
def install_dir():
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA", HOME / "AppData" / "Local")) / "Programs" / "Brochacho"
    return CFG_DIR / "bin"


def installed_exe():
    return install_dir() / ("Brochacho.exe" if IS_WIN else "brochacho")


def refresh_path():
    """Tools installed a minute ago aren't on this process's PATH yet; add their usual homes."""
    extra = [HOME / ".local" / "bin", HOME / ".bun" / "bin", HOME / ".cargo" / "bin", install_dir()]
    if IS_WIN:
        pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        extra += [pf / "Git" / "cmd", Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"]
        try:  # pick up PATH changes installers wrote to the registry
            import winreg
            for root, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                              (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
                with winreg.OpenKey(root, key) as k:
                    for p in os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]).split(";"):
                        if p:
                            extra.append(Path(p))
        except Exception:
            pass
    if IS_MAC:
        extra += [Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    parts = os.environ.get("PATH", "").split(os.pathsep)
    for p in reversed(extra):
        if str(p) not in parts and p.is_dir():
            parts.insert(0, str(p))
    os.environ["PATH"] = os.pathsep.join(parts)


def which(tool):
    return shutil.which(tool)


def resolve(cmd):
    """Full path for the program, so Windows finds claude.cmd / bun.exe the way a shell would."""
    exe = which(cmd[0])
    return [exe, *cmd[1:]] if exe else list(cmd)


def run(cmd, timeout=None, capture=True):
    """Run a command; returns (exit code, combined output). Never raises for a missing tool."""
    cmd = resolve(cmd)
    try:
        r = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace")
        return r.returncode, ((r.stdout or "") + (r.stderr or "")) if capture else ""
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def shell_install(win_ps, mac_sh):
    if IS_WIN:
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", win_ps]
    else:
        cmd = ["/bin/bash", "-c", mac_sh]
    code = subprocess.call(cmd)
    refresh_path()
    return code == 0


def self_cmd():
    """How Claude should call this program from its shell."""
    if FROZEN:
        return "brochacho"  # install dir is on the session's PATH
    return f'"{sys.executable}" "{Path(__file__).resolve()}"'


# ---------------------------------------------------------------------------------- requirements
def has_git():
    return which("git") is not None and run(["git", "--version"], 20)[0] == 0


def has_claude():
    return which("claude") is not None


def has_bun():
    return which("bun") is not None


def has_uv():
    return which("uvx") is not None


def install_git():
    if IS_WIN:
        if not which("winget"):
            return False
        subprocess.call(["winget", "install", "--id", "Git.Git", "-e", "--source", "winget",
                         "--accept-package-agreements", "--accept-source-agreements"])
        refresh_path()
        return has_git()
    subprocess.call(["xcode-select", "--install"])
    say("  A macOS window asks to install the Command Line Tools. Click Install and wait.")
    for _ in range(120):  # up to 20 minutes
        if run(["xcode-select", "-p"], 10)[0] == 0 and has_git():
            return True
        time.sleep(10)
    return has_git()


REQUIREMENTS = [
    # name, check, installer, why, manual link
    ("git", has_git, install_git,
     "downloads the Discord plugin and syncs your folder between machines",
     "https://git-scm.com/downloads"),
    ("Claude Code", has_claude,
     lambda: shell_install("irm https://claude.ai/install.ps1 | iex", "curl -fsSL https://claude.ai/install.sh | bash"),
     "the AI that does the work", "https://code.claude.com/docs/en/quickstart"),
    ("Bun", has_bun,
     lambda: shell_install("irm bun.sh/install.ps1 | iex", "curl -fsSL https://bun.sh/install | bash"),
     "runs the Discord plugin", "https://bun.sh"),
    ("uv (for voice messages)", has_uv,
     lambda: shell_install("irm https://astral.sh/uv/install.ps1 | iex", "curl -LsSf https://astral.sh/uv/install.sh | sh"),
     "runs the free, offline speech-to-text for voice messages", "https://docs.astral.sh/uv/"),
]


def claude_logged_in():
    code, out = run(["claude", "auth", "status"], 30)
    m = re.search(r"\{.*\}", out, re.S)
    if m:
        try:
            return bool(json.loads(m.group(0)).get("loggedIn"))
        except ValueError:
            pass
    return code == 0


def plugin_installed():
    return PLUGIN in run(["claude", "plugin", "list"], 60)[1]


# ------------------------------------------------------------------------------------- Discord
def _ssl_context():
    try:
        import certifi  # bundled in the .exe/.app builds
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def discord_get(path, token):
    req = urllib.request.Request(
        "https://discord.com/api/v10" + path,
        headers={"Authorization": f"Bot {token}",
                 "User-Agent": f"DiscordBot (https://github.com/Afaguayo/brochacho, {VERSION})"})
    with urllib.request.urlopen(req, timeout=20, context=_ssl_context()) as r:
        return json.load(r)


def app_id_from_token(token):
    part = token.split(".")[0]
    part += "=" * (-len(part) % 4)
    try:
        return base64.urlsafe_b64decode(part).decode("ascii")
    except Exception:
        return ""


def check_token(token):
    """Returns (status, info): status is ok | bad | intent | offline."""
    try:
        me = discord_get("/users/@me", token)
        app = discord_get("/applications/@me", token)
    except urllib.error.HTTPError as e:
        return ("bad", {}) if e.code == 401 else ("offline", {"error": f"HTTP {e.code}"})
    except Exception as e:
        return "offline", {"error": str(e)}
    info = {"bot": me.get("username", "your bot"), "app_id": app.get("id") or me.get("id")}
    if not (app.get("flags", 0) & INTENT_MESSAGE_CONTENT):
        return "intent", info
    return "ok", info


def invite_url(app_id):
    return f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot&permissions={INVITE_PERMS}"


def access():
    return read_json(ACCESS_FILE, {"dmPolicy": "pairing", "allowFrom": [], "groups": {}, "pending": {}})


def paired():
    a = access()
    return bool(a.get("allowFrom"))


def approve_code(code):
    """Same steps as the plugin's `/discord:access pair <code>`."""
    a = access()
    code = code.strip().lower()
    entry = a.get("pending", {}).get(code)
    if not entry or entry.get("expiresAt", 0) < time.time() * 1000:
        return None
    a.setdefault("allowFrom", [])
    if entry["senderId"] not in a["allowFrom"]:
        a["allowFrom"].append(entry["senderId"])
    del a["pending"][code]
    write_json(ACCESS_FILE, a)
    approved = DISCORD_DIR / "approved"
    approved.mkdir(parents=True, exist_ok=True)
    (approved / entry["senderId"]).write_text(entry["chatId"], encoding="utf-8")
    return entry["senderId"]


def lock_to_allowlist():
    a = access()
    a["dmPolicy"] = "allowlist"
    a["pending"] = {}
    write_json(ACCESS_FILE, a)


# ------------------------------------------------------------------------------- settings/persona
def build_settings(cfg):
    me = self_cmd()
    allow = [
        MCP_PREFIX,                                      # reply, react, edit, download_attachment, fetch
        "Read(~/.claude/channels/discord/inbox/**)",    # photos and voice messages you send
        "Bash(git status:*)", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git add:*)",
        "Bash(git commit:*)", "Bash(git pull:*)", "Bash(git push:*)", "Bash(git fetch:*)",
        "Bash(ls:*)", "Bash(pwd)", "Bash(date)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)",
        "Bash(wc:*)", "Bash(grep:*)", "Bash(rg:*)", "Bash(find:*)", "Bash(mkdir:*)",
    ]
    if FROZEN:
        allow += [f"Bash({me} transcribe:*)", f"Bash({me} wake:*)"]
    secrets = ["~/.claude/channels/discord/.env", "~/.claude/channels/discord/access.json"]
    deny = [f"{tool}({p})" for p in secrets for tool in ("Read", "Edit")]
    return {"enabledPlugins": {PLUGIN: True}, "permissions": {"allow": allow, "deny": deny}}


def build_persona(cfg):
    base = (RES / "brochacho.md").read_text(encoding="utf-8")
    me = self_cmd()
    machine = socket.gethostname().split(".")[0]
    lines = [
        "",
        "This setup:",
        f"- This machine: {machine} ({'Windows' if IS_WIN else 'macOS'}).",
        f"- Attachments are downloaded to {INBOX}.",
        f"- Wake tool: {me} wake <machine-name>   (list machines: {me} wake --list)",
    ]
    if cfg.get("voice"):
        lines.append(f"- Voice transcription: {me} transcribe <audio-file>   (prints the text)")
    else:
        lines.append("- Voice messages are turned off on this machine. If one arrives, say so and suggest "
                     "running 'brochacho setup' on the computer to turn them on.")
    return base.rstrip() + "\n" + "\n".join(lines) + "\n"


def claude_command(cfg):
    mode = MODES.get(cfg.get("mode", "auto"), MODES["auto"])
    return ["claude", "--settings", str(SETTINGS_FILE),
            "--channels", f"plugin:{PLUGIN}",
            *mode[1],
            "--add-dir", str(INBOX),
            "--append-system-prompt-file", str(PERSONA_FILE)]


# ------------------------------------------------------------------------------------ shortcuts
def install_self():
    """Copy the program somewhere permanent so shortcuts keep working if Downloads is cleaned."""
    if not FROZEN:
        return Path(sys.executable)
    src, dst = Path(sys.executable).resolve(), installed_exe()
    if not dst.exists() or src != dst.resolve():
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(src, dst)
        except OSError as e:
            warn(f"Couldn't copy to {dst} ({e}). Is Brochacho running? Close it and run setup again.")
            return src
        if not IS_WIN:
            dst.chmod(0o755)
            run(["xattr", "-d", "com.apple.quarantine", str(dst)], 10)
    return dst


def launch_target(exe):
    """(program, arguments) that start Brochacho."""
    if FROZEN:
        return str(exe), ["start"]
    return sys.executable, [str(Path(__file__).resolve()), "start"]


def win_shortcut(lnk, exe, minimized=False):
    prog, args = launch_target(exe)
    icon = f"{prog},0" if FROZEN else str(RES / "docs" / "brochacho.ico")
    q = lambda s: str(s).replace("'", "''")
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(lnk)}');"
          f"$s.TargetPath='{q(prog)}';"
          f"$s.Arguments='{q(subprocess.list2cmdline(args))}';"
          f"$s.WorkingDirectory='{q(HOME)}';$s.IconLocation='{q(icon)}';"
          f"$s.WindowStyle={7 if minimized else 1};$s.Description='Turn on Brochacho (Claude on Discord)';$s.Save()")
    Path(lnk).parent.mkdir(parents=True, exist_ok=True)
    return run(["powershell", "-NoProfile", "-Command", ps], 60)[0] == 0


def win_folder(name):
    code, out = run(["powershell", "-NoProfile", "-Command", f"[Environment]::GetFolderPath('{name}')"], 30)
    return Path(out.strip()) if code == 0 and out.strip() else None


def mac_command_file(exe):
    prog, args = launch_target(exe)
    cmd = CFG_DIR / "Brochacho.command"
    cmd.write_text("#!/bin/bash\nexec " + " ".join(f'"{a}"' for a in [prog, *args]) + "\n", encoding="utf-8")
    cmd.chmod(0o755)
    return cmd


LAUNCH_AGENT = HOME / "Library" / "LaunchAgents" / "com.brochacho.autostart.plist"


def shortcut_paths():
    if IS_WIN:
        desk, start, menu = win_folder("Desktop"), win_folder("Startup"), win_folder("Programs")
        return {"desktop": desk / "Brochacho.lnk" if desk else None,
                "startup": start / "Brochacho.lnk" if start else None,
                "menu": menu / "Brochacho.lnk" if menu else None}
    return {"desktop": HOME / "Desktop" / "Brochacho.command", "startup": LAUNCH_AGENT, "menu": None}


def make_shortcuts(exe, autostart):
    p = shortcut_paths()
    if IS_WIN:
        for key in ("desktop", "menu"):
            if p[key] and win_shortcut(p[key], exe):
                ok(f"Shortcut: {p[key]}")
        if p["startup"]:
            if autostart and win_shortcut(p["startup"], exe, minimized=True):
                ok("Starts by itself when you log in.")
            elif not autostart and p["startup"].exists():
                p["startup"].unlink()
        return
    cmd = mac_command_file(exe)
    desk = p["desktop"]
    desk.parent.mkdir(exist_ok=True)
    shutil.copy2(cmd, desk)
    ok(f"Desktop launcher: {desk}")
    if autostart:
        LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
        LAUNCH_AGENT.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.brochacho.autostart</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/open</string><string>-a</string><string>Terminal</string><string>{cmd}</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict></plist>
""", encoding="utf-8")
        ok("Starts by itself when you log in (opens a Terminal window).")
    elif LAUNCH_AGENT.exists():
        LAUNCH_AGENT.unlink()


def open_new_window(exe):
    """Start Brochacho in its own window so the wizard can keep talking to you."""
    prog, args = launch_target(exe)
    if IS_WIN:
        subprocess.Popen([prog, *args], creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        subprocess.Popen(["open", "-a", "Terminal", str(mac_command_file(exe))])


# --------------------------------------------------------------------------------- wake-on-lan
def detect_nic():
    """(mac, broadcast, note) for this machine's main network adapter, or None."""
    if IS_WIN:
        ps = ("$n=Get-NetAdapter -Physical|?{$_.Status -eq 'Up'}|Sort-Object {$_.MediaType -ne '802.3'}|Select -First 1;"
              "if($n){$ip=Get-NetIPAddress -InterfaceIndex $n.ifIndex -AddressFamily IPv4|Select -First 1;"
              "$w=Get-NetAdapterAdvancedProperty -Name $n.Name -DisplayName 'Wake on Magic Packet' -EA SilentlyContinue;"
              "@{mac=$n.MacAddress;ip=$ip.IPAddress;prefix=$ip.PrefixLength;wol=$w.DisplayValue;name=$n.Name}|ConvertTo-Json}")
        code, out = run(["powershell", "-NoProfile", "-Command", ps], 60)
        try:
            d = json.loads(out)
        except ValueError:
            return None
        bcast = str(ipaddress.ip_network(f"{d['ip']}/{d['prefix']}", strict=False).broadcast_address)
        note = None
        if d.get("wol") and d["wol"] != "Enabled":
            note = f"'Wake on Magic Packet' is off for {d['name']}: turn it on in Device Manager to wake this PC remotely."
        return d["mac"], bcast, note
    code, out = run(["route", "-n", "get", "default"], 10)
    m = re.search(r"interface:\s*(\S+)", out)
    if not m:
        return None
    _, ifc = run(["ifconfig", m.group(1)], 10)
    mac = re.search(r"ether\s+(\S+)", ifc)
    bc = re.search(r"broadcast\s+(\S+)", ifc)
    if not mac:
        return None
    return mac.group(1), bc.group(1) if bc else "255.255.255.255", \
        "To be woken by another machine: System Settings > Battery/Energy > Options > Wake for network access."


def register_machine():
    nic = detect_nic()
    if not nic:
        warn("Couldn't find this machine's network adapter; skipping Wake-on-LAN registration.")
        return
    mac, bcast, note = nic
    machines = read_json(MACHINES, {})
    name = socket.gethostname().split(".")[0].lower()
    alias = "pc" if IS_WIN else "mac"
    taken = any(alias in m.get("aliases", []) for n, m in machines.items() if n != name)
    old = machines.get(name, {})
    machines[name] = {"mac": mac, "broadcast": bcast, "os": "windows" if IS_WIN else "macos",
                      "aliases": old.get("aliases") or ([] if taken else [alias])}
    write_json(MACHINES, machines)
    ok(f"Registered '{name}' for Wake-on-LAN ({mac}).")
    if note:
        warn(note)


def cmd_wake(args):
    machines = read_json(MACHINES, {})
    target = args.target
    if not target or target == "--list":
        for name, m in machines.items():
            aka = f" aka {', '.join(m['aliases'])}" if m.get("aliases") else ""
            print(f"{name:<14} {m.get('mac')}  ({m.get('os', '?')}){aka}")
        if not machines:
            print(f"No machines yet. Run 'brochacho setup' on each computer to register it ({MACHINES}).")
        return 0
    key = target.lower()
    entry = machines.get(key) or next((m for m in machines.values() if key in m.get("aliases", [])), None)
    if entry:
        mac, bcast = entry["mac"], entry.get("broadcast", "255.255.255.255")
    elif re.match(r"^([0-9A-Fa-f]{2}[:-]?){5}[0-9A-Fa-f]{2}$", target):
        mac, bcast = target, "255.255.255.255"
    else:
        print(f"Unknown machine '{target}'. Known: {', '.join(machines) or 'none'}", file=sys.stderr)
        return 1
    packet = b"\xff" * 6 + bytes.fromhex(re.sub(r"[:-]", "", mac)) * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for addr in dict.fromkeys([bcast, "255.255.255.255"]):
            for port in (9, 7):
                s.sendto(packet, (addr, port))
    print(f"Sent magic packet to {mac} via {bcast}. Give it ~20 s to wake.")
    return 0


# ---------------------------------------------------------------------------------- transcribe
def transcribe(path, model="base", language=None):
    """Returns (text, error)."""
    refresh_path()
    uvx = which("uvx")
    if not uvx:
        return None, "uv is not installed. Run 'brochacho setup' and turn on voice messages."
    out = Path(tempfile.mkdtemp(prefix="brochacho-voice-"))
    cmd = [uvx, "--quiet", "--python", WHISPER_PYTHON, "--from", WHISPER, "whisper-ctranslate2", str(path),
           "--model", model, "--output_format", "txt", "--output_dir", str(out), "--verbose", "False",
           "--initial_prompt", "Brochacho."]
    if language:
        cmd += ["--language", language]
    env = dict(os.environ, HF_HUB_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_PROGRESS_BARS="1",
               PYTHONWARNINGS="ignore", TQDM_DISABLE="1")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, encoding="utf-8", errors="replace")
    except OSError as e:
        return None, str(e)
    txt = next(out.glob("*.txt"), None)
    text = txt.read_text(encoding="utf-8").strip() if txt else ""
    shutil.rmtree(out, ignore_errors=True)
    if r.returncode != 0 or not txt:
        tail = "\n".join((r.stderr or r.stdout).strip().splitlines()[-5:])
        return None, f"transcription failed (exit {r.returncode}): {tail}"
    return text, None


def cmd_transcribe(args):
    cfg = load_cfg()
    path = Path(args.file)
    if not path.is_file():
        print(f"No such file: {path}", file=sys.stderr)
        return 1
    text, err = transcribe(path, cfg.get("voice_model", "base"), cfg.get("voice_language") or None)
    if err:
        print(err, file=sys.stderr)
        return 1
    print(text or "(no speech found)")
    return 0


def warm_up_voice(model):
    """Downloads the speech engine and model once, so the first real voice message is fast."""
    sample = Path(tempfile.mkdtemp()) / "silence.wav"
    with wave.open(str(sample), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    _, err = transcribe(sample, model)
    shutil.rmtree(sample.parent, ignore_errors=True)
    return err


# ----------------------------------------------------------------------------------- the wizard
def step_requirements(cfg):
    say("  Brochacho needs a few free programs. Anything missing can be installed for you.\n")
    for name, check, install, why, link in REQUIREMENTS:
        optional = name.startswith("uv")
        if check():
            ok(f"{name}: installed  {c('(' + why + ')', 'dim')}")
            continue
        warn(f"{name}: missing  {c('(' + why + ')', 'dim')}")
        if optional:
            say("       (optional; you can install it in the voice step)")
            continue
        while not check():
            if yes(f"Install {name} now?"):
                install()
                if check():
                    ok(f"{name}: installed")
                    break
                bad(f"{name} didn't install automatically. Install it from {link}")
            else:
                say(f"       Install it yourself from {link}")
                webbrowser.open(link)
            pause("Press Enter when it's installed to check again")
            refresh_path()
    return True


def step_login(cfg):
    if claude_logged_in():
        ok("Claude Code is signed in.")
        return True
    say("  Claude Code needs to sign in to your Claude account (Pro/Max, or a Console API key).")
    say("  A browser window opens; approve it and come back here.\n")
    pause("Press Enter to sign in")
    subprocess.call(resolve(["claude", "auth", "login"]))
    while not claude_logged_in():
        bad("Not signed in yet.")
        if not yes("Try signing in again?"):
            say("  You can also run 'claude' in a terminal and type /login.")
            pause("Press Enter once you're signed in")
            if claude_logged_in():
                break
            continue
        subprocess.call(resolve(["claude", "auth", "login"]))
    ok("Claude Code is signed in.")
    return True


def step_folder(cfg):
    say("  Which folder should Claude work in? Your notes vault, a project, anything.")
    say("  Claude can read and edit everything inside it.\n")
    default = cfg.get("vault")
    if not default:
        for guess in (HOME / "Documents" / "SecondBrain", HOME / "Documents" / "Obsidian"):
            if guess.is_dir():
                default = str(guess)
                break
        else:
            default = str(HOME / "Documents" / "Brochacho")
    while True:
        folder = Path(os.path.expandvars(ask("Folder", default).strip('"').strip("'"))).expanduser()
        if folder.is_dir():
            break
        if yes(f"{folder} doesn't exist. Create it?"):
            folder.mkdir(parents=True, exist_ok=True)
            break
    cfg["vault"] = str(folder.resolve())
    ok(f"Brochacho will work in {cfg['vault']}")
    if not (folder / ".git").is_dir():
        say(c("       Tip: make it a git repo with a remote to sync it between your computers.", "dim"))
    return True


def step_bot(cfg):
    token = read_token()
    if token:
        status, info = check_token(token)
        if status == "ok":
            ok(f"Bot token saved and working (bot: {info['bot']}).")
            if not yes("Keep using this bot?"):
                token = ""
            else:
                cfg["app_id"] = info["app_id"]
                return _invite(cfg, already=True)
        elif status == "offline":
            warn(f"Bot token saved, but Discord couldn't be reached to check it ({info.get('error')}).")
            if yes("Keep it?"):
                return True
            token = ""
        else:
            token = ""
    say("  Make your own Discord bot (about 2 minutes). The page opens in your browser:\n")
    say("    1. Click  New Application  (top right), give it a name like Brochacho, Create.")
    say("    2. In the left menu click  Bot.")
    say("    3. Scroll to  Privileged Gateway Intents  and turn on  MESSAGE CONTENT INTENT.  Save Changes.")
    say("    4. Still on Bot, click  Reset Token  > Yes, and  Copy  the token.")
    say("    5. Recommended: turn off  Public Bot  so nobody else can add your bot to a server.\n")
    if yes("Open the Discord Developer Portal?"):
        webbrowser.open("https://discord.com/developers/applications")
    while True:
        token = getpass.getpass("  > Paste the bot token here (it stays hidden, right-click or Ctrl+V to paste): ").strip()
        if not re.fullmatch(r"[\w-]+\.[\w-]+\.[\w-]+", token):
            bad("That doesn't look like a bot token (three parts separated by dots). Try again.")
            continue
        status, info = check_token(token)
        if status == "bad":
            bad("Discord says that token is wrong. Click Reset Token again and copy the new one.")
            continue
        if status == "intent":
            warn(f"Bot '{info['bot']}' works, but MESSAGE CONTENT INTENT is off, so it can't read your messages.")
            say("       Bot page > Privileged Gateway Intents > turn on MESSAGE CONTENT INTENT > Save Changes.")
            pause("Press Enter after you've saved it")
            status, info = check_token(token)
            if status == "intent":
                warn("Still looks off (Discord can take a minute). Continuing; fix it before you test.")
        if status == "offline":
            warn(f"Couldn't reach Discord to check the token ({info.get('error')}); saving it anyway.")
            info = {"bot": "your bot", "app_id": app_id_from_token(token)}
        break
    DISCORD_DIR.mkdir(parents=True, exist_ok=True)
    # UTF-8 without BOM, or the plugin misreads line 1.
    ENV_FILE.write_bytes(f"DISCORD_BOT_TOKEN={token}\n".encode("utf-8"))
    if not IS_WIN:
        DISCORD_DIR.chmod(0o700)
        ENV_FILE.chmod(0o600)
    ok(f"Token saved for bot '{info['bot']}' (in {ENV_FILE}, never in your folder).")
    cfg["app_id"] = info["app_id"]
    return _invite(cfg)


def _invite(cfg, already=False):
    if already and cfg.get("invited") and not yes("Open the invite page again (to add the bot to another server)?", False):
        return True
    say("\n  Discord only lets you DM a bot you share a server with. Next page: pick a server")
    say("  (make a private one if you like: + in the server list > Create My Own) and click Authorize.\n")
    pause("Press Enter to open the invite page")
    webbrowser.open(invite_url(cfg["app_id"]))
    say(c(f"       If it didn't open: {invite_url(cfg['app_id'])}", "dim"))
    pause("Press Enter once the bot is in your server")
    cfg["invited"] = True
    return True


def step_plugin(cfg):
    if not plugin_installed():
        say("  Installing the official Discord plugin for Claude Code...")
        run(["claude", "plugin", "marketplace", "add", MARKETPLACE], 300, capture=False)
        run(["claude", "plugin", "install", PLUGIN, "--scope", "user"], 300, capture=False)
    if not plugin_installed():
        bad("The plugin didn't install. Check your internet and that git works, then run setup again.")
        return False
    # Off for your normal Claude sessions; Brochacho turns it on just for itself.
    run(["claude", "plugin", "disable", PLUGIN, "--scope", "user"], 120)
    ok("Discord plugin installed (only active inside Brochacho).")
    return True


def step_autonomy(cfg):
    say("  How much should Brochacho do without asking you?\n")
    keys = list(MODES)
    current = cfg.get("mode", "auto")
    for i, k in enumerate(keys, 1):
        label, _, text = MODES[k]
        mark = c(" (current)", "dim") if k == current and cfg.get("mode") else ""
        say(f"  {i}. {c(label, 'bold')}{mark}\n     {text}\n")
    while True:
        pick = ask("Choose 1, 2 or 3", str(keys.index(current) + 1))
        if pick in ("1", "2", "3"):
            break
    mode = keys[int(pick) - 1]
    if mode == "full" and not yes("Sure? Anyone with your Discord login could control this computer.", False):
        mode = "auto"
    cfg["mode"] = mode
    ok(f"Mode: {MODES[mode][0]}. Change it any time with 'brochacho setup'.")
    say(c("       Either way, Discord replies, photos and voice messages never need your approval.", "dim"))
    return True


def step_voice(cfg):
    say("  Brochacho reads photos you send automatically. Voice messages need a small speech-to-text")
    say("  engine that runs on this computer (free, private, ~200 MB download once).\n")
    if not yes("Turn on voice messages?", cfg.get("voice", True)):
        cfg["voice"] = False
        ok("Voice messages off.")
        return True
    if not has_uv():
        say("  Installing uv (runs the speech engine)...")
        REQUIREMENTS[3][2]()
        if not has_uv():
            bad("uv didn't install; voice stays off. Install it from https://docs.astral.sh/uv/ and run setup again.")
            cfg["voice"] = False
            return True
    models = {"1": "base", "2": "small", "3": "tiny"}
    say("  Speech model:  1. base (good, fast; recommended)   2. small (better, slower)   3. tiny (fastest)")
    current = {v: k for k, v in models.items()}.get(cfg.get("voice_model", "base"), "1")
    cfg["voice_model"] = models.get(ask("Choose 1, 2 or 3", current), "base")
    say("  Downloading the speech engine and model (one time, 1-3 minutes)...")
    err = warm_up_voice(cfg["voice_model"])
    if err:
        warn(f"Voice warm-up had a problem: {err}")
        warn("Voice stays on; the first voice message will retry the download.")
    else:
        ok("Voice messages ready.")
    cfg["voice"] = True
    return True


def step_shortcuts(cfg):
    exe = install_self()
    autostart = yes("Start Brochacho automatically when you log in?", cfg.get("autostart", False))
    cfg["stay_awake"] = yes("Keep this computer awake while Brochacho runs?", cfg.get("stay_awake", False))
    cfg["autostart"] = autostart
    make_shortcuts(exe, autostart)
    register_machine()
    return True


def step_pair(cfg):
    if paired():
        ok("Your Discord account is already paired.")
        if not yes("Pair another account?", False):
            return True
    say("  Last step: tell the bot it's you.\n")
    say("  A Brochacho window opens now. The first time, Claude Code may ask a question or two in")
    say("  that window (trust this folder, confirm the permission mode): answer them there.\n")
    pause("Press Enter to start Brochacho")
    save_cfg(cfg)
    open_new_window(installed_exe() if FROZEN and installed_exe().exists() else Path(sys.executable))
    say("\n  Once the Brochacho window says it's on, open Discord on your phone or computer and")
    say("  send your bot a DM: " + c("hi", "bold") + ". It answers with a 6-character pairing code.\n")
    return pair_loop()


def pair_loop():
    while True:
        code = ask("Type the code here (or Enter to skip for now)")
        if not code:
            warn("Skipped. Run 'brochacho pair' later to finish.")
            return True
        sender = approve_code(code)
        if sender:
            lock_to_allowlist()
            ok(f"Paired! Discord user {sender} can now talk to Brochacho; everyone else is ignored.")
            return True
        bad("That code isn't waiting (typo, expired, or Brochacho wasn't running yet). DM 'hi' again for a new one.")


STEPS = [
    ("Install what Brochacho needs", step_requirements),
    ("Sign in to Claude", step_login),
    ("Pick the folder Claude works in", step_folder),
    ("Create your Discord bot", step_bot),
    ("Install the Discord plugin", step_plugin),
    ("Choose how independent Brochacho is", step_autonomy),
    ("Voice messages", step_voice),
    ("Shortcuts and auto-start", step_shortcuts),
    ("Pair your Discord account", step_pair),
]


def cmd_setup(args=None):
    refresh_path()
    cfg = load_cfg()
    banner(f"Brochacho setup  v{VERSION}")
    say("  Text your computer from Discord; Claude does the work and texts back.")
    say(f"  {len(STEPS)} short steps. You can stop any time and run setup again; it picks up where you left off.")
    for i, (title, fn) in enumerate(STEPS, 1):
        banner(f"Step {i} of {len(STEPS)}: {title}")
        if not fn(cfg):
            save_cfg(cfg)
            bad("Setup stopped here. Fix the problem above and run setup again.")
            return 1
        save_cfg(cfg)
    cfg["setup_done"] = VERSION
    save_cfg(cfg)
    banner("All set!")
    say(f"  - Turn it on: double-click {c('Brochacho', 'bold')} on your Desktop.")
    say("  - Text your bot anything: 'what's in my to-do list?', a photo of a receipt, or a voice note.")
    say("  - Keep the Brochacho window open; closing it turns Brochacho off.")
    say("  - Change answers later: run Brochacho > Re-run setup.\n")
    return 0


# -------------------------------------------------------------------------------------- doctor
def cmd_doctor(args=None):
    refresh_path()
    cfg = load_cfg()
    banner("Brochacho check-up")
    problems = 0

    def check(good, yes_text, no_text):
        nonlocal problems
        if good:
            ok(yes_text)
        else:
            bad(no_text)
            problems += 1

    for name, fn, _, why, link in REQUIREMENTS:
        if name.startswith("uv") and not cfg.get("voice"):
            continue
        check(fn(), f"{name} installed", f"{name} missing ({why}): {link}")
    if has_claude():
        check(claude_logged_in(), "Claude Code signed in", "Claude Code not signed in: run 'claude auth login'")
        check(plugin_installed(), "Discord plugin installed", "Discord plugin missing: run setup step 5")
    vault = cfg.get("vault")
    check(vault and Path(vault).is_dir(), f"Folder: {vault}", "No folder picked: run setup")
    token = read_token()
    if not token:
        check(False, "", "No bot token: run setup")
    else:
        status, info = check_token(token)
        if status == "offline":
            warn(f"Couldn't reach Discord to test the token ({info.get('error')})")
        else:
            check(status != "bad", f"Bot token works ({info.get('bot', '?')})", "Bot token rejected: reset it and run setup")
            if status != "bad":
                check(status == "ok", "Message Content Intent on", "Message Content Intent off: Developer Portal > Bot")
    check(paired(), "Your Discord account is paired", "Nobody paired yet: run 'brochacho pair'")
    if paired():
        check(access().get("dmPolicy") == "allowlist", "Locked to your account", "Bot answers strangers with pairing codes: run 'brochacho pair'")
    say(f"\n  Mode: {MODES.get(cfg.get('mode', 'auto'), MODES['auto'])[0]}    Voice: {'on' if cfg.get('voice') else 'off'}")
    say("\n  " + (c("Everything looks good.", "green") if not problems else c(f"{problems} thing(s) to fix.", "yellow")))
    return 1 if problems else 0


def cmd_pair(args=None):
    banner("Pair your Discord account")
    say("  1. Make sure the Brochacho window is running.")
    say("  2. DM your bot 'hi'. It answers with a 6-character code.\n")
    return 0 if pair_loop() else 1


# --------------------------------------------------------------------------------------- start
_lock_handle = None


def single_instance():
    global _lock_handle
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    if IS_WIN:
        import ctypes
        _lock_handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\Brochacho")
        return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    import fcntl
    _lock_handle = open(CFG_DIR / "brochacho.lock", "w")
    try:
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def stay_awake():
    if IS_WIN:
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    elif IS_MAC:
        subprocess.Popen(["caffeinate", "-is", "-w", str(os.getpid())])


def cmd_start(args):
    if IS_WIN:
        os.system("title Brochacho")
    else:
        sys.stdout.write("\033]0;Brochacho\007")
    refresh_path()
    cfg = load_cfg()
    missing = [n for n, fn, *_ in REQUIREMENTS[:3] if not fn()]
    if missing or not read_token() or not cfg.get("vault"):
        bad("Brochacho isn't set up yet" + (f" (missing: {', '.join(missing)})" if missing else "") + ".")
        if yes("Run setup now?"):
            return cmd_setup()
        return 1
    if not single_instance():
        warn("Brochacho is already running on this computer.")
        time.sleep(3)
        return 0
    vault = Path(args.vault or cfg["vault"]).expanduser()
    if not vault.is_dir():
        bad(f"The folder {vault} is gone. Run setup to pick another.")
        return 1
    write_json(SETTINGS_FILE, build_settings(cfg))
    PERSONA_FILE.write_text(build_persona(cfg), encoding="utf-8")
    INBOX.mkdir(parents=True, exist_ok=True)
    if args.stay_awake or cfg.get("stay_awake"):
        stay_awake()
    if (vault / ".git").is_dir():
        run(["git", "-C", str(vault), "pull", "--ff-only"], 60)
    env = dict(os.environ)
    if FROZEN:
        env["PATH"] = str(Path(sys.executable).resolve().parent) + os.pathsep + env["PATH"]
    say(f"""
  +------------------------------------------------+
  |  BROCHACHO is on. DM your bot on Discord.      |
  |  Close this window to turn it off.             |
  +------------------------------------------------+
  folder: {vault}
  mode:   {MODES.get(cfg.get('mode', 'auto'), MODES['auto'])[0]}    voice: {'on' if cfg.get('voice') else 'off'}
""", "cyan")
    quick_fails = 0
    while True:  # restart after a crash or dropped connection; a clean /exit stops for good
        began = time.time()
        proc = subprocess.Popen(resolve(claude_command(cfg)), cwd=str(vault), env=env)
        while True:
            try:
                code = proc.wait()
                break
            except KeyboardInterrupt:
                continue  # Claude handles Ctrl+C itself
        if code == 0:
            return 0
        quick_fails = quick_fails + 1 if time.time() - began < 20 else 0
        if quick_fails >= 2:
            warn("Claude Code keeps closing right away. Run 'brochacho doctor' to see why.")
            if cfg.get("mode", "auto") == "auto":
                warn("If your plan doesn't have auto mode yet, run setup and pick option 2.")
        warn(f"Brochacho stopped (exit {code}). Restarting in 10 s; close the window to cancel.")
        time.sleep(10)


# ----------------------------------------------------------------------------------- uninstall
def cmd_uninstall(args=None):
    p = shortcut_paths()
    for path in [p["desktop"], p["startup"], p["menu"], CFG_DIR / "Brochacho.command"]:
        if path and Path(path).exists():
            Path(path).unlink()
            ok(f"Removed {path}")
    say("  Your token, settings and the program itself are kept. To remove everything, delete:")
    for path in (CFG_DIR, DISCORD_DIR, install_dir()):
        say(f"    {path}")
    return 0


# ---------------------------------------------------------------------------------------- main
def menu():
    cfg = load_cfg()
    if not cfg.get("setup_done"):
        return cmd_setup()
    banner(f"Brochacho  v{VERSION}")
    options = [("Start Brochacho", lambda: cmd_start(argparse.Namespace(vault=None, stay_awake=False))),
               ("Re-run setup", cmd_setup), ("Check that everything works", cmd_doctor),
               ("Pair a Discord account", cmd_pair), ("Remove shortcuts", cmd_uninstall)]
    for i, (label, _) in enumerate(options, 1):
        say(f"  {i}. {label}")
    pick = ask("Choose", "1")
    if pick.isdigit() and 1 <= int(pick) <= len(options):
        return options[int(pick) - 1][1]()
    return 0


def main(argv=None):
    _enable_console()
    parser = argparse.ArgumentParser(prog="brochacho", description="Text your computer from Discord.")
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="cmd")
    s = sub.add_parser("start", help="start Brochacho")
    s.add_argument("--vault", help="folder to work in (default: the one picked in setup)")
    s.add_argument("--stay-awake", action="store_true", help="keep the computer awake while running")
    sub.add_parser("setup", help="run the setup wizard")
    sub.add_parser("doctor", help="check every requirement")
    sub.add_parser("pair", help="approve your Discord account")
    w = sub.add_parser("wake", help="Wake-on-LAN another machine")
    w.add_argument("target", nargs="?", help="machine name, alias or MAC address; --list to list")
    t = sub.add_parser("transcribe", help="voice message to text")
    t.add_argument("file")
    sub.add_parser("uninstall", help="remove shortcuts and auto-start")
    args, extra = parser.parse_known_args(argv)
    if args.cmd == "wake" and "--list" in extra:
        args.target = "--list"
    handlers = {"start": cmd_start, "setup": cmd_setup, "doctor": cmd_doctor, "pair": cmd_pair,
                "wake": cmd_wake, "transcribe": cmd_transcribe, "uninstall": cmd_uninstall}
    interactive = args.cmd in (None, "setup", "doctor", "pair", "uninstall")
    try:
        code = handlers[args.cmd](args) if args.cmd else menu()
    except KeyboardInterrupt:
        say("\n  Stopped.")
        code = 1
    except Exception as e:  # keep the window open so a double-clicked .exe shows the error
        bad(f"Something went wrong: {e}")
        if not interactive:
            raise
        code = 1
    if interactive and (IS_WIN or FROZEN):
        pause("Press Enter to close")
    return code or 0


if __name__ == "__main__":
    sys.exit(main())
