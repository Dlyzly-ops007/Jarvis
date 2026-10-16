"""Linux implementation of the Platform interface.

Reads /proc and /sys directly (no psutil), and shells out only to well-known
desktop tools (xdg-open, gtk-launch, notify-send, nmcli, locate, ...). Every
subprocess call uses an argument list (never shell=True), a timeout, and no
privilege escalation. Missing tools degrade to a clear "not available" result.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import shlex
import shutil
import socket
import struct
import subprocess
import time
from pathlib import Path

from core import fail, ok
from oslayer import AppEntry, PlatformBase, is_privileged_exec

log = logging.getLogger("jarvis.linux")

FIELD_CODES = {"%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N", "%v", "%m", "%i"}
TERMINALS = [("x-terminal-emulator", ["-e"]), ("xdg-terminal-exec", []), ("qterminal", ["-e"]),
             ("xfce4-terminal", ["-x"]), ("gnome-terminal", ["--"]), ("konsole", ["-e"]),
             ("xterm", ["-e"])]
USER_DIR_KEYS = {"desktop": "DESKTOP", "download": "DOWNLOAD", "downloads": "DOWNLOAD",
                 "documents": "DOCUMENTS", "document": "DOCUMENTS", "music": "MUSIC",
                 "pictures": "PICTURES", "picture": "PICTURES", "photos": "PICTURES",
                 "videos": "VIDEOS", "video": "VIDEOS", "templates": "TEMPLATES", "public": "PUBLICSHARE"}


def _read(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


def _run(args: list[str], timeout: float = 8.0, env: dict | None = None) -> tuple[int | None, str, str]:
    """Run a command, capture output. Never raises. rc None = could not run."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env,
                           stdin=subprocess.DEVNULL)
        return p.returncode, p.stdout, p.stderr.strip()
    except FileNotFoundError:
        return None, "", f"{args[0]} not found"
    except subprocess.TimeoutExpired:
        return None, "", f"{args[0]} timed out"
    except OSError as e:
        return None, "", str(e)


def _spawn(args: list[str]) -> tuple[bool, str]:
    """Start a detached GUI process. Never raises."""
    try:
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        return True, ""
    except (OSError, ValueError) as e:
        return False, str(e)


def split_terse(line: str) -> list[str]:
    """Split one line of `nmcli -t` output (':' separated, '\\:' escaped)."""
    parts, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def exec_to_argv(exec_str: str, name: str = "", path: str = "") -> list[str]:
    """Desktop-entry Exec= to argv, dropping field codes (%f, %U, ...)."""
    try:
        tokens = shlex.split(exec_str)
    except ValueError:
        tokens = exec_str.split()
    argv = []
    for t in tokens:
        if t in FIELD_CODES:
            continue
        t = t.replace("%c", name).replace("%k", path).replace("%%", "\x00")
        t = re.sub(r"%[fFuUdDnNvmi]", "", t).replace("\x00", "%")
        if t:
            argv.append(t)
    return argv


def parse_desktop_file(path: str, desktop_id: str = "") -> AppEntry | None:
    """Minimal [Desktop Entry] parser. Returns None for hidden/non-app entries."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    section, kv = None, {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section != "Desktop Entry" or "=" not in line:
            continue
        k, _, v = line.partition("=")
        kv.setdefault(k.strip(), v.strip())
    if kv.get("Type", "Application") != "Application":
        return None
    if kv.get("NoDisplay", "").lower() == "true" or kv.get("Hidden", "").lower() == "true":
        return None
    if not kv.get("Name") or not kv.get("Exec"):
        return None
    split = lambda s: tuple(x.strip() for x in s.split(";") if x.strip())
    return AppEntry(
        name=kv["Name"], exec=kv["Exec"], desktop_id=desktop_id or os.path.basename(path),
        path=path, terminal=kv.get("Terminal", "").lower() == "true",
        generic_name=kv.get("GenericName", ""), keywords=split(kv.get("Keywords", "")),
        categories=split(kv.get("Categories", "")), source="desktop")


class LinuxPlatform(PlatformBase):
    name = "linux"

    # -- helpers ------------------------------------------------------------
    def has_display(self) -> bool:
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

    def _need_display(self, what: str) -> dict | None:
        if self.has_display():
            return None
        return fail(f"No graphical session detected, so I can't {what}. "
                    "Run me from a terminal inside the desktop.", error="DISPLAY/WAYLAND_DISPLAY unset")

    def diagnostics(self) -> dict:
        tools = ["xdg-open", "gtk-launch", "gio", "notify-send", "nmcli", "iwgetid", "ip",
                 "plocate", "locate", "loginctl", "xflock4", "xdg-screensaver",
                 "espeak-ng", "espeak", "spd-say", "piper", "aplay", "paplay", "pw-play"]
        return {
            "platform": self.name,
            "desktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
            "session": os.environ.get("XDG_SESSION_TYPE", ""),
            "display": self.has_display(),
            "dbus": bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")),
            "root": os.geteuid() == 0,
            "tools": {t: bool(shutil.which(t)) for t in tools},
        }

    # -- opening ------------------------------------------------------------
    def open_path(self, path: str) -> dict:
        p = Path(path).expanduser()
        if not p.exists():
            return fail(f"{p} doesn't exist.", error="missing path")
        if (err := self._need_display("open files")):
            return err
        for opener in (["xdg-open"], ["gio", "open"]):
            if shutil.which(opener[0]):
                good, e = _spawn(opener + [str(p)])
                if good:
                    return ok(f"Opened {p}", speech=f"Opening {p.name or p}.")
                log.warning("open_path via %s failed: %s", opener[0], e)
        return fail("I couldn't open that — xdg-open isn't available.", error="no opener")

    def open_url(self, url: str) -> dict:
        if (err := self._need_display("open a browser")):
            return err
        if shutil.which("xdg-open"):
            good, e = _spawn(["xdg-open", url])
            if good:
                return ok(f"Opened {url}")
            log.warning("xdg-open failed: %s", e)
        return super().open_url(url)

    def user_dir(self, name: str) -> Path | None:
        name = name.lower().strip()
        home = Path.home()
        if name in ("home", "~", "home folder"):
            return home
        key = USER_DIR_KEYS.get(name)
        if not key:
            return None
        cfg = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
        text = _read(str(cfg))
        m = re.search(rf'^XDG_{key}_DIR="([^"]*)"', text, re.M)
        if m:
            p = Path(m.group(1).replace("$HOME", str(home))).expanduser()
            if p.is_dir():
                return p
        fallback = {"DOWNLOAD": "Downloads", "PUBLICSHARE": "Public"}.get(key, key.capitalize())
        p = home / fallback
        return p if p.is_dir() else None

    # -- applications ---------------------------------------------------------
    def _app_dirs(self) -> list[Path]:
        home = Path.home()
        data_home = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
        data_dirs = (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
        dirs = [data_home / "applications"] + [Path(d) / "applications" for d in data_dirs if d]
        dirs += [home / ".local/share/flatpak/exports/share/applications",
                 Path("/var/lib/flatpak/exports/share/applications"),
                 Path("/var/lib/snapd/desktop/applications")]
        seen, out = set(), []
        for d in dirs:
            if d not in seen and d.is_dir():
                seen.add(d)
                out.append(d)
        return out

    def list_apps(self) -> list[AppEntry]:
        entries, seen_ids = [], set()
        for base in self._app_dirs():
            for fp in sorted(glob.glob(str(base / "**" / "*.desktop"), recursive=True)):
                did = os.path.relpath(fp, base).replace(os.sep, "-")
                if did in seen_ids:            # earlier dirs override later ones (XDG spec)
                    continue
                seen_ids.add(did)
                e = parse_desktop_file(fp, did)
                if e:
                    entries.append(e)
        log.info("indexed %d desktop apps", len(entries))
        return entries

    def default_app(self, category: str, index: list[AppEntry]) -> AppEntry | None:
        did = None
        if category == "WebBrowser" and shutil.which("xdg-settings"):
            rc, out, _ = _run(["xdg-settings", "get", "default-web-browser"], timeout=4)
            did = out.strip() if rc == 0 else None
        elif category == "FileManager" and shutil.which("xdg-mime"):
            rc, out, _ = _run(["xdg-mime", "query", "default", "inode/directory"], timeout=4)
            did = out.strip() if rc == 0 else None
        elif category == "TerminalEmulator" and shutil.which("x-terminal-emulator"):
            return AppEntry(name="Terminal", exec="x-terminal-emulator", source="path")
        if did:
            for e in index:
                if e.desktop_id == did:
                    return e
        return None

    def launch_app(self, entry: AppEntry) -> dict:
        if is_privileged_exec(entry.exec):
            return fail(f"{entry.name} needs elevated privileges; I won't launch it.", error="privileged")
        if (err := self._need_display("launch apps")):
            return err
        # 1) gtk-launch / gio understand field codes, Terminal=true, DBus activation.
        if entry.desktop_id and entry.source == "desktop":
            if shutil.which("gtk-launch"):
                try:
                    rc = subprocess.run(["gtk-launch", entry.desktop_id], stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        timeout=15).returncode
                    if rc == 0:
                        return ok(f"Launched {entry.name}")
                    log.info("gtk-launch %s rc=%s, trying next method", entry.desktop_id, rc)
                except (OSError, subprocess.TimeoutExpired) as e:
                    log.info("gtk-launch failed: %s", e)
            if entry.path and shutil.which("gio"):
                rc, _, err = _run(["gio", "launch", entry.path], timeout=15)
                if rc == 0:
                    return ok(f"Launched {entry.name}")
                log.info("gio launch %s rc=%s %s", entry.path, rc, err)
        # 2) Parse Exec ourselves.
        argv = exec_to_argv(entry.exec, entry.name, entry.path)
        if not argv:
            return fail(f"{entry.name} has no usable launch command.", error="empty Exec")
        if not shutil.which(argv[0]) and not os.path.isfile(argv[0]):
            return fail(f"{entry.name} seems to be uninstalled ({argv[0]} missing).", error="binary missing")
        if entry.terminal:
            for term, flag in TERMINALS:
                if shutil.which(term):
                    argv = [term] + flag + argv
                    break
            else:
                return fail(f"{entry.name} needs a terminal and I couldn't find one.", error="no terminal")
        good, e = _spawn(argv)
        return ok(f"Launched {entry.name}") if good else fail(f"Couldn't launch {entry.name}.", error=e)

    def locate(self, pattern: str, limit: int = 2000) -> list[str] | None:
        binary = shutil.which("plocate") or shutil.which("locate")
        if not binary or not pattern:
            return None
        rc, out, err = _run([binary, "-i", "-b", "-l", str(limit), "--", pattern], timeout=6)
        if rc == 0:
            return [l for l in out.splitlines() if l]
        if rc == 1 and not err:          # ran fine, no matches
            return []
        log.info("locate unavailable (rc=%s): %s", rc, err)
        return None

    # -- notifications / session ---------------------------------------------
    def notify(self, title: str, body: str, urgency: str = "normal",
               app_name: str = "Jarvis", timeout_ms: int = 6000) -> dict:
        if not shutil.which("notify-send"):
            return fail("Desktop notifications need notify-send (package libnotify-bin).",
                        error="notify-send not found")
        urgency = urgency if urgency in ("low", "normal", "critical") else "normal"
        rc, _, err = _run(["notify-send", "-a", app_name, "-u", urgency, "-t", str(int(timeout_ms)),
                           title, body], timeout=6)
        if rc == 0:
            return ok("Notification sent.")
        return fail("The notification didn't go through.", error=err or f"rc={rc}")

    def lock_screen(self) -> dict:
        desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        attempts = []
        if "xfce" in desktop:
            attempts.append(["xflock4"])
        attempts += [["loginctl", "lock-session"], ["xdg-screensaver", "lock"],
                     ["gnome-screensaver-command", "-l"], ["dm-tool", "lock"]]
        tried = []
        for cmd in attempts:
            if not shutil.which(cmd[0]):
                continue
            rc, _, err = _run(cmd, timeout=8)
            if rc == 0:
                return ok("Screen locked.", speech="Locking.")
            tried.append(f"{cmd[0]}: {err or rc}")
        return fail("I couldn't find a way to lock this session.", error="; ".join(tried) or "no locker")

    # -- system data ------------------------------------------------------------
    @staticmethod
    def _cpu_times() -> tuple[int, int] | None:
        first = _read("/proc/stat").split("\n", 1)[0].split()
        if not first or first[0] != "cpu":
            return None
        vals = [int(v) for v in first[1:9]]
        idle = vals[3] + vals[4]
        return idle, sum(vals)

    def cpu_stats(self) -> dict | None:
        a = self._cpu_times()
        if a is None:
            return None
        time.sleep(0.3)
        b = self._cpu_times() or a
        d_total = b[1] - a[1]
        pct = 0.0 if d_total <= 0 else 100.0 * (1 - (b[0] - a[0]) / d_total)
        model = ""
        for line in _read("/proc/cpuinfo").splitlines():
            if line.lower().startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
        try:
            load = os.getloadavg()
        except OSError:
            load = None
        return {"percent": round(pct, 1), "load": load, "cores": os.cpu_count() or 1, "model": model}

    def memory_stats(self) -> dict | None:
        info = {}
        for line in _read("/proc/meminfo").splitlines():
            k, _, v = line.partition(":")
            parts = v.split()
            if parts and parts[0].isdigit():
                info[k] = int(parts[0]) * 1024
        if "MemTotal" not in info:
            return None
        total = info["MemTotal"]
        avail = info.get("MemAvailable", info.get("MemFree", 0))
        st, sf = info.get("SwapTotal", 0), info.get("SwapFree", 0)
        return {"total": total, "available": avail, "used": total - avail,
                "percent": round(100.0 * (total - avail) / total, 1) if total else 0.0,
                "swap_total": st, "swap_used": st - sf}

    def battery(self) -> dict | None:
        batteries, ac_online = [], None
        for dev in sorted(glob.glob("/sys/class/power_supply/*")):
            typ = _read(f"{dev}/type")
            if typ == "Mains":
                ac_online = _read(f"{dev}/online") == "1" or bool(ac_online)
            elif typ == "Battery" and _read(f"{dev}/present", "1") == "1":
                cap = _read(f"{dev}/capacity")
                if not cap.isdigit():
                    continue
                status = _read(f"{dev}/status", "Unknown")
                secs = None
                e_now = _read(f"{dev}/energy_now") or _read(f"{dev}/charge_now")
                p_now = _read(f"{dev}/power_now") or _read(f"{dev}/current_now")
                if status == "Discharging" and e_now.isdigit() and p_now.isdigit() and int(p_now) > 0:
                    secs = int(3600 * int(e_now) / int(p_now))
                batteries.append({"name": os.path.basename(dev), "percent": int(cap),
                                  "status": status, "seconds_left": secs})
        if not batteries:
            return None
        main = batteries[0]
        charging = main["status"] in ("Charging", "Full") or (ac_online is True and main["status"] != "Discharging")
        return {"percent": main["percent"], "status": main["status"], "charging": charging,
                "plugged_in": ac_online, "seconds_left": main["seconds_left"], "count": len(batteries)}

    def uptime_seconds(self) -> float | None:
        raw = _read("/proc/uptime").split()
        try:
            return float(raw[0])
        except (IndexError, ValueError):
            return None

    def temperatures(self) -> list[tuple[str, float]] | None:
        temps = []
        for zone in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
            t = _read(f"{zone}/temp")
            if t.lstrip("-").isdigit() and int(t) > 0:
                temps.append((_read(f"{zone}/type", os.path.basename(zone)), int(t) / 1000.0))
        for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
            name = _read(f"{hw}/name", os.path.basename(hw))
            for inp in sorted(glob.glob(f"{hw}/temp*_input"))[:4]:
                t = _read(inp)
                if t.lstrip("-").isdigit() and int(t) > 0:
                    label = _read(inp.replace("_input", "_label")) or name
                    temps.append((label, int(t) / 1000.0))
        return temps or None

    def top_processes(self, n: int = 5) -> list[dict] | None:
        procs = []
        for d in glob.glob("/proc/[0-9]*"):
            name, rss = "", 0
            for line in _read(f"{d}/status").splitlines():
                if line.startswith("Name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("VmRSS:"):
                    try:
                        rss = int(line.split()[1]) * 1024
                    except (IndexError, ValueError):
                        rss = 0
                    break
            if name and rss:
                procs.append({"pid": int(os.path.basename(d)), "name": name, "rss": rss})
        if not procs:
            return None
        procs.sort(key=lambda p: p["rss"], reverse=True)
        return procs[:n]

    # -- network -----------------------------------------------------------------
    def network_interfaces(self) -> list[dict] | None:
        ifaces = []
        for dev in sorted(glob.glob("/sys/class/net/*")):
            name = os.path.basename(dev)
            if name == "lo":
                continue
            wireless = os.path.isdir(f"{dev}/wireless") or os.path.exists(f"{dev}/phy80211")
            is_virtual = os.path.realpath(dev).startswith("/sys/devices/virtual/")
            ifaces.append({"name": name, "state": _read(f"{dev}/operstate", "unknown"),
                           "wireless": wireless, "virtual": is_virtual, "ipv4": []})
        if shutil.which("ip"):
            rc, out, _ = _run(["ip", "-j", "-4", "addr"], timeout=4)
            if rc == 0:
                try:
                    by_name = {i["name"]: i for i in ifaces}
                    for item in json.loads(out or "[]"):
                        tgt = by_name.get(item.get("ifname"))
                        if tgt is not None:
                            tgt["ipv4"] = [a["local"] for a in item.get("addr_info", []) if "local" in a]
                except (ValueError, KeyError, TypeError) as e:
                    log.debug("ip -j parse failed: %s", e)
        return ifaces

    def default_gateway(self) -> str | None:
        for line in _read("/proc/net/route").splitlines()[1:]:
            f = line.split()
            if len(f) >= 3 and f[1] == "00000000":
                try:
                    return socket.inet_ntoa(struct.pack("<L", int(f[2], 16)))
                except (ValueError, struct.error, OSError):
                    return None
        return None

    def wifi_status(self) -> dict | None:
        ifaces = self.network_interfaces() or []
        wlan = [i for i in ifaces if i["wireless"]]
        status = {"adapter": bool(wlan), "device": wlan[0]["name"] if wlan else None,
                  "enabled": None, "ssid": None, "signal": None, "security": None, "tool": None}
        if shutil.which("nmcli"):
            status["tool"] = "nmcli"
            rc, out, _ = _run(["nmcli", "-t", "-f", "WIFI", "general"], timeout=5)
            if rc == 0 and out.strip():
                status["enabled"] = out.strip().lower() == "enabled"
            rc, out, _ = _run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,SECURITY",
                               "device", "wifi", "list", "--rescan", "no"], timeout=8)
            if rc == 0:
                for line in out.splitlines():
                    f = split_terse(line)
                    if len(f) >= 4 and f[0] == "yes":
                        status.update(ssid=f[1] or "(hidden)", security=f[3] or "open",
                                      signal=int(f[2]) if f[2].isdigit() else None)
                        break
            return status
        if shutil.which("iwgetid"):
            status["tool"] = "iwgetid"
            rc, out, _ = _run(["iwgetid", "-r"], timeout=4)
            if rc == 0 and out.strip():
                status["ssid"] = out.strip()
        for line in _read("/proc/net/wireless").splitlines()[2:]:
            f = line.split()
            if len(f) > 2:
                try:
                    status["signal"] = min(100, int(float(f[2].rstrip(".")) * 100 / 70))
                except ValueError:
                    pass
                break
        return status

    def wifi_scan(self) -> dict:
        if not shutil.which("nmcli"):
            return fail("Wi-Fi scanning needs NetworkManager's nmcli.", error="nmcli not found")
        rc, out, err = _run(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi",
                             "list", "--rescan", "auto"], timeout=20)
        if rc != 0:
            return fail("The Wi-Fi scan failed.", error=err or f"rc={rc}")
        best: dict[str, dict] = {}
        for line in out.splitlines():
            f = split_terse(line)
            if len(f) < 3 or not f[0]:
                continue
            sig = int(f[1]) if f[1].isdigit() else 0
            if f[0] not in best or sig > best[f[0]]["signal"]:
                best[f[0]] = {"ssid": f[0], "signal": sig, "security": f[2] or "open"}
        nets = sorted(best.values(), key=lambda n: n["signal"], reverse=True)[:10]
        if not nets:
            return ok("No Wi-Fi networks in range (or no Wi-Fi adapter).", networks=[])
        lines = [f"  {n['signal']:>3}%  {n['ssid']}  ({n['security']})" for n in nets]
        return ok("Networks in range:\n" + "\n".join(lines),
                  speech=f"I can see {len(nets)} networks. Strongest is {nets[0]['ssid']}.", networks=nets)

    def set_wifi(self, enabled: bool) -> dict:
        if not shutil.which("nmcli"):
            return fail("Wi-Fi control needs NetworkManager's nmcli.", error="nmcli not found")
        state = "on" if enabled else "off"
        rc, _, err = _run(["nmcli", "radio", "wifi", state], timeout=10)
        if rc == 0:
            return ok(f"Wi-Fi turned {state}.")
        return fail(f"I couldn't turn Wi-Fi {state}. NetworkManager said: {err or rc}",
                    error=err or f"rc={rc}")
