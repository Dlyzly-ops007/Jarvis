"""Capabilities: the portable logic on top of a Platform.

  AppLauncher       resolve "open <name>" against the installed-app index
  FileSearch        find files/folders under configured roots (locate fast path)
  SystemMonitor     CPU / RAM / disk / battery / uptime / temps / top processes
  Network           connectivity, interfaces, Wi-Fi
  WebSearch         build + open search URLs
  BackgroundMonitor periodic threshold alerts with once-per-episode hysteresis

All public methods return core result dicts and never raise.
"""
from __future__ import annotations

import difflib
import fnmatch
import logging
import os
import re
import shutil
import socket
import threading
import time
from pathlib import Path
from urllib.parse import quote_plus

from core import fail, ok
from oslayer import AppEntry, PlatformBase, is_privileged_exec

log = logging.getLogger("jarvis.caps")


# ── formatting helpers ─────────────────────────────────────────────────────
def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = [f"{d} day{'s' * (d != 1)}"] if d else []
    if h:
        parts.append(f"{h} hour{'s' * (h != 1)}")
    if m or not parts:
        parts.append(f"{m} minute{'s' * (m != 1)}")
    return ", ".join(parts)


# ── applications ────────────────────────────────────────────────────────────
CATEGORY_ALIASES = {
    "browser": "WebBrowser", "web browser": "WebBrowser", "internet": "WebBrowser",
    "terminal": "TerminalEmulator", "console": "TerminalEmulator", "shell": "TerminalEmulator",
    "file manager": "FileManager", "files": "FileManager", "file explorer": "FileManager",
    "explorer": "FileManager", "text editor": "TextEditor", "editor": "TextEditor",
    "notepad": "TextEditor", "calculator": "Calculator", "calc": "Calculator",
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def score_app(query: str, e: AppEntry) -> float:
    q = _norm(query)
    name = _norm(e.name)
    stem = e.desktop_id[:-8].lower() if e.desktop_id.endswith(".desktop") else e.desktop_id.lower()
    stem_last = stem.split(".")[-1] if stem else ""
    exec0 = ""
    if e.exec:
        first = e.exec.split()[0] if e.exec.split() else ""
        exec0 = os.path.basename(first.strip('"')).lower()
    if q in (name, exec0, stem, stem_last):
        return 1.0
    if name.startswith(q) or (exec0 and exec0.startswith(q)):
        return 0.9
    words = set(re.split(r"[\s\-_.]+", name))
    if set(q.split()) <= words:
        return 0.85
    if q in name:
        return 0.8
    extra = " ".join([e.generic_name, *e.keywords]).lower()
    if q and q in extra:
        return 0.7
    return 0.75 * difflib.SequenceMatcher(None, q, name).ratio()


class AppLauncher:
    MIN_SCORE = 0.6

    def __init__(self, platform: PlatformBase, settings):
        self.platform = platform
        self.settings = settings
        self._index: list[AppEntry] | None = None
        self._lock = threading.Lock()

    def index(self, refresh: bool = False) -> list[AppEntry]:
        with self._lock:
            if self._index is None or refresh:
                try:
                    self._index = self.platform.list_apps()
                except Exception:          # platform bug must not kill routing
                    log.exception("app index failed")
                    self._index = []
            return self._index

    def blocked_reason(self, entry: AppEntry) -> str | None:
        blocked = {_norm(b) for b in self.settings.get("apps.blocked", [])}
        if _norm(entry.name) in blocked:
            return "on the blocked list"
        if is_privileged_exec(entry.exec):
            return "requires root privileges"
        return None

    def resolve(self, query: str) -> tuple[str, object]:
        """-> ('ok', entry) | ('ambiguous', [entries]) | ('blocked', (entry, reason)) | ('none', None)"""
        q = _norm(re.sub(r"^(?:the|my)\s+|\s+(?:app|application|program)$", "", _norm(query)))
        aliases = {_norm(k): v for k, v in (self.settings.get("apps.aliases") or {}).items()}
        q = _norm(aliases.get(q, q))
        if not q:
            return "none", None
        index = self.index()
        chosen = None
        category = CATEGORY_ALIASES.get(q)
        if category:
            chosen = self.platform.default_app(category, index) or next(
                (e for e in index if category in e.categories), None)
        if chosen is None:
            scored = sorted(((score_app(q, e), e) for e in index), key=lambda t: t[0], reverse=True)
            scored = [(s, e) for s, e in scored if s >= self.MIN_SCORE]
            if scored:
                top = scored[0][0]
                close, names = [], set()
                for s, e in scored:
                    if top - s <= 0.05 and _norm(e.name) not in names:
                        names.add(_norm(e.name))
                        close.append(e)
                if top >= 0.99 or len(close) == 1:
                    chosen = scored[0][1]
                else:
                    return "ambiguous", close[:4]
        if chosen is None and self.settings.get("apps.allow_path_fallback") and re.fullmatch(r"[\w.+-]+", q):
            path = self.platform.which(q)
            if path:
                chosen = AppEntry(name=q, exec=path, source="path")
        if chosen is None:
            return "none", None
        reason = self.blocked_reason(chosen)
        if reason:
            return "blocked", (chosen, reason)
        return "ok", chosen

    def launch_entry(self, entry: AppEntry) -> dict:
        reason = self.blocked_reason(entry)
        if reason:
            return fail(f"I won't open {entry.name} — it {reason}.", error="blocked")
        try:
            return self.platform.launch_app(entry)
        except Exception as e:
            log.exception("launch_app crashed")
            return fail(f"Launching {entry.name} failed.", error=str(e))

    def launch(self, query: str) -> dict:
        status, payload = self.resolve(query)
        if status == "ok":
            r = self.launch_entry(payload)
            r.setdefault("data", {})["app"] = payload.name
            return r
        if status == "ambiguous":
            names = [e.name for e in payload]
            listing = "\n".join(f"  {i}. {n}" for i, n in enumerate(names, 1))
            return fail(f"Which one did you mean?\n{listing}", error="ambiguous",
                        speech=f"Which one: {', '.join(names[:-1])} or {names[-1]}?", choices=payload)
        if status == "blocked":
            entry, reason = payload
            return fail(f"I won't open {entry.name} — it {reason}.", error="blocked")
        return fail(f"No installed app matches '{query}'.", error="not_found")


# ── file search ───────────────────────────────────────────────────────────
class FileSearch:
    def __init__(self, platform: PlatformBase, settings):
        self.platform = platform
        self.settings = settings

    def resolve_root(self, text: str) -> Path | None:
        t = (text or "").strip().strip("'\"")
        if not t:
            return None
        t = re.sub(r"^(?:my|the)\s+|\s+(?:folder|directory|dir)$", "", t.strip(), flags=re.I)
        special = self.platform.user_dir(t.lower())
        if special:
            return special
        p = Path(t).expanduser()
        return p if p.is_dir() else None

    @staticmethod
    def matcher(query: str):
        q = query.lower().strip()
        if any(c in q for c in "*?["):
            return lambda name: fnmatch.fnmatch(name.lower(), q)
        tokens = q.split()
        return lambda name: all(t in name.lower() for t in tokens)

    @staticmethod
    def _rank(query: str, path: str) -> tuple:
        q = query.lower().strip()
        name = os.path.basename(path).lower()
        stem = os.path.splitext(name)[0]
        tier = 0 if q in (name, stem) else 1 if name.startswith(q) else 2
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0
        return tier, path.count(os.sep), -mtime

    def _allowed(self, path: str, roots: list[Path], hidden: bool) -> bool:
        if not any(path == str(r) or path.startswith(str(r).rstrip(os.sep) + os.sep) for r in roots):
            return False
        parts = Path(path).parts
        excl = set(self.settings.get("files.exclude_dirs") or [])
        if any(p in excl for p in parts):
            return False
        return hidden or not any(p.startswith(".") for p in parts)

    def _walk(self, match, kind: str, roots: list[Path], hidden: bool, cap: int) -> tuple[list[str], bool]:
        """Iterative, depth- and time-bounded scandir walk. Never follows symlinked dirs."""
        excl = set(self.settings.get("files.exclude_dirs") or [])
        max_depth = int(self.settings.get("files.max_depth") or 10)
        deadline = time.monotonic() + float(self.settings.get("files.time_budget_s") or 4.0)
        found, truncated = [], False
        stack = [(r, 0) for r in reversed(roots)]
        while stack:
            if time.monotonic() > deadline:
                truncated = True
                break
            d, depth = stack.pop()
            try:
                with os.scandir(d) as it:
                    entries = list(it)
            except OSError:
                continue
            for e in entries:
                if not hidden and e.name.startswith("."):
                    continue
                try:
                    is_dir = e.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if match(e.name) and (kind == "any" or (kind == "dir") == is_dir):
                    found.append(e.path)
                    if len(found) >= cap:
                        return found, True
                if is_dir and e.name not in excl and depth < max_depth:
                    stack.append((e.path, depth + 1))
        return found, truncated

    def search(self, query: str, kind: str = "any", root: Path | None = None, exts: tuple = ()) -> dict:
        query = (query or "").strip().strip("'\"")
        if not query:
            return fail("Search for what?", error="empty query")
        roots = [root] if root else [Path(r).expanduser() for r in self.settings.get("files.search_roots") or ["~"]]
        roots = [r.resolve() for r in roots if r.is_dir()]
        if not roots:
            return fail("None of the search folders exist.", error="no roots")
        hidden = bool(self.settings.get("files.include_hidden"))
        limit = int(self.settings.get("files.max_results") or 10)
        base_match = self.matcher(query)
        exts = tuple(e.lower() for e in exts)
        match = (lambda n: base_match(n) and n.lower().endswith(exts)) if exts else base_match
        found: list[str] | None = None
        truncated = False
        if self.settings.get("files.use_locate") and not any(c in query for c in "*?["):
            hits = self.platform.locate(query.split()[0])
            if hits:     # empty/None -> db missing or stale; walk instead
                found = [h for h in hits if match(os.path.basename(h)) and self._allowed(h, roots, hidden)
                         and os.path.exists(h) and (kind == "any" or (kind == "dir") == os.path.isdir(h))]
                found = found or None
        if found is None:
            found, truncated = self._walk(match, kind, roots, hidden, cap=limit * 20)
        found.sort(key=lambda p: self._rank(query, p))
        found = found[:limit]
        if not found:
            where = ", ".join(str(r) for r in roots)
            return fail(f"No {'folders' if kind == 'dir' else 'files'} matching '{query}' under {where}.",
                        error="not_found", results=[])
        home = str(Path.home())
        lines = [f"  {i}. {p.replace(home, '~', 1)}{'/' if os.path.isdir(p) else ''}"
                 for i, p in enumerate(found, 1)]
        note = "\n  (search stopped early — narrow it down or add 'in <folder>')" if truncated else ""
        names = ", ".join(os.path.basename(p) for p in found[:3])
        speech = (f"Found {os.path.basename(found[0])}." if len(found) == 1
                  else f"Found {len(found)} matches. Top ones: {names}.")
        return ok(f"Found {len(found)} match{'es' * (len(found) != 1)}:\n" + "\n".join(lines) + note
                  + "\n  Say 'open 1' to open one.", speech=speech, results=found)


# ── system information ─────────────────────────────────────────────────────
class SystemMonitor:
    def __init__(self, platform: PlatformBase, settings):
        self.platform = platform
        self.settings = settings

    def _safe(self, fn, *a):
        try:
            return fn(*a)
        except Exception:
            log.exception("%s failed", getattr(fn, "__name__", fn))
            return None

    def cpu(self) -> dict:
        s = self._safe(self.platform.cpu_stats)
        if not s:
            return fail("CPU stats aren't available here.", error="unavailable")
        load = f", load {s['load'][0]:.2f}/{s['load'][1]:.2f}/{s['load'][2]:.2f}" if s.get("load") else ""
        return ok(f"CPU at {s['percent']:.0f}% across {s['cores']} cores{load}."
                  + (f"\n  {s['model']}" if s.get("model") else ""),
                  speech=f"CPU is at {s['percent']:.0f} percent.", **s)

    def memory(self) -> dict:
        m = self._safe(self.platform.memory_stats)
        if not m:
            return fail("Memory stats aren't available here.", error="unavailable")
        swap = (f" Swap {fmt_bytes(m['swap_used'])} of {fmt_bytes(m['swap_total'])}."
                if m.get("swap_total") else "")
        return ok(f"RAM {m['percent']:.0f}% used — {fmt_bytes(m['used'])} of {fmt_bytes(m['total'])}, "
                  f"{fmt_bytes(m['available'])} available.{swap}",
                  speech=f"Memory is {m['percent']:.0f} percent used, {fmt_bytes(m['available'])} free.", **m)

    def disk(self, paths: list[str] | None = None) -> dict:
        paths = paths or self.settings.get("monitor.disk_paths") or ["/"]
        rows, seen = [], set()
        for raw in paths:
            p = Path(raw).expanduser()
            try:
                dev = p.stat().st_dev
                if dev in seen:
                    continue
                seen.add(dev)
                u = shutil.disk_usage(p)
            except OSError as e:
                log.info("disk_usage %s: %s", p, e)
                continue
            free_pct = 100.0 * u.free / u.total if u.total else 0.0
            rows.append({"path": str(p), "total": u.total, "free": u.free, "free_pct": round(free_pct, 1)})
        if not rows:
            return fail("I couldn't read disk usage for those paths.", error="unavailable")
        lines = [f"{r['path']}: {fmt_bytes(r['free'])} free of {fmt_bytes(r['total'])} ({r['free_pct']:.0f}% free)"
                 for r in rows]
        return ok("Disk — " + "; ".join(lines) + ".",
                  speech=f"{fmt_bytes(rows[0]['free'])} free on {rows[0]['path']}.", disks=rows)

    def battery(self) -> dict:
        b = self._safe(self.platform.battery)
        if not b:
            return ok("No battery detected — this looks like a desktop or VM.", speech="No battery detected.",
                      present=False)
        state = "charging" if b["charging"] else "on battery"
        left = f", about {fmt_duration(b['seconds_left'])} left" if b.get("seconds_left") else ""
        return ok(f"Battery {b['percent']}% ({b['status'].lower()}, {state}{left}).",
                  speech=f"Battery is at {b['percent']} percent, {state}.", present=True, **b)

    def uptime(self) -> dict:
        up = self._safe(self.platform.uptime_seconds)
        if up is None:
            return fail("Uptime isn't available here.", error="unavailable")
        return ok(f"Up for {fmt_duration(up)}.", seconds=up)

    def temperatures(self) -> dict:
        temps = self._safe(self.platform.temperatures)
        if not temps:
            return ok("No temperature sensors exposed (common in VMs).", speech="No temperature sensors found.")
        hottest = max(temps, key=lambda t: t[1])
        lines = "\n".join(f"  {label}: {c:.0f}°C" for label, c in temps[:8])
        return ok(f"Temperatures:\n{lines}", speech=f"Hottest sensor is {hottest[1]:.0f} degrees.", temps=temps)

    def top(self, n: int = 5) -> dict:
        procs = self._safe(self.platform.top_processes, n)
        if not procs:
            return fail("Process info isn't available here.", error="unavailable")
        lines = "\n".join(f"  {p['name']:<22} {fmt_bytes(p['rss']):>9}  (pid {p['pid']})" for p in procs)
        return ok(f"Top memory users:\n{lines}",
                  speech=f"{procs[0]['name']} is using the most memory, {fmt_bytes(procs[0]['rss'])}.",
                  processes=procs)

    def summary(self) -> dict:
        parts, speech = [], []
        for fn in (self.cpu, self.memory, self.disk, self.battery, self.uptime):
            r = fn()
            if r["ok"] and not (fn == self.battery and not r.get("data", {}).get("present")):
                parts.append(r["text"].split("\n")[0])
                speech.append(r.get("speech") or r["text"])
        if not parts:
            return fail("System information isn't available on this platform.", error="unavailable")
        return ok("\n".join(f"  {p}" for p in parts), speech=" ".join(speech[:3]))

    def snapshot(self) -> dict:
        cpu = self._safe(self.platform.cpu_stats) or {}
        mem = self._safe(self.platform.memory_stats) or {}
        bat = self._safe(self.platform.battery)
        d = self.disk().get("data", {}).get("disks", [])
        return {"cpu": cpu.get("percent"), "ram": mem.get("percent"),
                "battery": (bat["percent"], bat["charging"]) if bat else None,
                "disk": [(r["path"], r["free_pct"]) for r in d]}


# ── network ──────────────────────────────────────────────────────────────
class Network:
    def __init__(self, platform: PlatformBase, settings):
        self.platform = platform
        self.settings = settings

    def internet(self) -> tuple[bool, str | None, float | None]:
        timeout = float(self.settings.get("network.timeout_s") or 2.0)
        for hp in self.settings.get("network.check_hosts") or []:
            host, _, port = str(hp).rpartition(":")
            if not host:
                host, port = port, "53"
            t0 = time.monotonic()
            try:
                with socket.create_connection((host, int(port)), timeout=timeout):
                    return True, host, (time.monotonic() - t0) * 1000
            except (OSError, ValueError):
                continue
        return False, None, None

    @staticmethod
    def primary_ip() -> str | None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("192.0.2.1", 9))           # TEST-NET, no packet is sent
                return s.getsockname()[0]
        except OSError:
            return None

    def status(self) -> dict:
        online, host, ms = self.internet()
        lines = [f"Internet: {'online' if online else 'OFFLINE'}"
                 + (f" (reached {host} in {ms:.0f} ms)" if online else "")]
        ifaces = None
        try:
            ifaces = self.platform.network_interfaces()
        except Exception:
            log.exception("network_interfaces failed")
        if ifaces and not any(i.get("ipv4") for i in ifaces):
            lines.append(f"  Local IP: {self.primary_ip() or 'unknown'}")
        if ifaces:
            for i in ifaces:
                if i.get("virtual") and not i.get("ipv4"):
                    continue
                kind = "wifi" if i["wireless"] else "wired/virtual"
                ips = ", ".join(i["ipv4"]) or "no IPv4"
                lines.append(f"  {i['name']} [{kind}] {i['state']} — {ips}")
        else:
            ip = self.primary_ip()
            lines.append(f"  Local IP: {ip or 'unknown'}")
        gw = self.platform.default_gateway()
        if gw:
            lines.append(f"  Gateway: {gw}")
        wifi = self._safe_wifi()
        if wifi and wifi.get("ssid"):
            lines.append(f"  Wi-Fi: {wifi['ssid']}" + (f" ({wifi['signal']}%)" if wifi.get("signal") else ""))
        speech = ("You're online." if online else "You appear to be offline.")
        if wifi and wifi.get("ssid"):
            speech += f" Connected to {wifi['ssid']}."
        return ok("\n".join(lines), speech=speech, online=online, latency_ms=ms)

    def _safe_wifi(self) -> dict | None:
        try:
            return self.platform.wifi_status()
        except Exception:
            log.exception("wifi_status failed")
            return None

    def wifi(self) -> dict:
        w = self._safe_wifi()
        if w is None:
            return fail("Wi-Fi status isn't available on this platform.", error="unsupported")
        if not w.get("adapter") and not w.get("ssid"):
            return ok("No Wi-Fi adapter detected — you're on a wired or virtual connection "
                      "(normal for a VM). Try 'network status'.", speech="No Wi-Fi adapter detected.", **w)
        if w.get("enabled") is False:
            return ok("Wi-Fi radio is off.", **w)
        if w.get("ssid"):
            sig = f", signal {w['signal']}%" if w.get("signal") is not None else ""
            sec = f", {w['security']}" if w.get("security") else ""
            return ok(f"Connected to {w['ssid']}{sig}{sec}.", speech=f"Connected to {w['ssid']}.", **w)
        return ok("Wi-Fi is on but not connected to a network.", **w)

    def set_wifi(self, enabled: bool) -> dict:
        if not self.settings.get("network.allow_wifi_toggle"):
            return fail("Wi-Fi control is disabled in settings (network.allow_wifi_toggle).", error="disabled")
        try:
            return self.platform.set_wifi(enabled)
        except Exception as e:
            log.exception("set_wifi failed")
            return fail("Wi-Fi control failed.", error=str(e))

    def scan(self) -> dict:
        try:
            return self.platform.wifi_scan()
        except Exception as e:
            log.exception("wifi_scan failed")
            return fail("Wi-Fi scan failed.", error=str(e))


# ── web search ───────────────────────────────────────────────────────────
ENGINES = {
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "google": "https://www.google.com/search?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "startpage": "https://www.startpage.com/do/search?q={q}",
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "github": "https://github.com/search?q={q}",
    "stackoverflow": "https://stackoverflow.com/search?q={q}",
    "reddit": "https://www.reddit.com/search/?q={q}",
}
ENGINE_NAMES = {"stack overflow": "stackoverflow", "ddg": "duckduckgo", "duck duck go": "duckduckgo", "yt": "youtube"}


class WebSearch:
    def __init__(self, platform: PlatformBase, settings):
        self.platform = platform
        self.settings = settings

    def engines(self) -> dict:
        return {**ENGINES, **(self.settings.get("web.engines") or {})}

    def canonical(self, name: str | None) -> str | None:
        if not name:
            return None
        n = ENGINE_NAMES.get(_norm(name), _norm(name).replace(" ", ""))
        return n if n in self.engines() else None

    def build_url(self, query: str, engine: str | None = None) -> str:
        engines = self.engines()
        name = self.canonical(engine) or self.canonical(self.settings.get("web.search_engine")) or "duckduckgo"
        return engines[name].replace("{q}", quote_plus(query.strip()))

    def search(self, query: str, engine: str | None = None) -> dict:
        query = (query or "").strip()
        if not query:
            return fail("Search the web for what?", error="empty query")
        url = self.build_url(query, engine)
        r = self.platform.open_url(url)
        if r["ok"]:
            where = f" on {engine}" if engine else ""
            return ok(f"Searching{where}: {query}\n  {url}", speech=f"Searching for {query}.", url=url)
        return fail(f"Couldn't open the browser. Search URL: {url}", error=r.get("error"), url=url)


# ── background monitor ───────────────────────────────────────────────────
class BackgroundMonitor:
    """Checks a snapshot every interval; alerts once per episode per condition."""

    def __init__(self, system: SystemMonitor, settings, on_alert):
        self.system = system
        self.settings = settings
        self.on_alert = on_alert
        self.active: set[str] = set()
        self._cpu_streak = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _enter(self, key: str) -> bool:
        if key in self.active:
            return False
        self.active.add(key)
        return True

    def evaluate(self, snap: dict) -> list[tuple[str, str, str]]:
        g = self.settings.get
        alerts: list[tuple[str, str, str]] = []
        bat = snap.get("battery")
        if bat:
            pct, charging = bat
            crit, low, high = int(g("monitor.battery_critical")), int(g("monitor.battery_low")), int(g("monitor.battery_high"))
            if charging:
                self.active -= {"battery_low", "battery_critical"}
                if high and pct >= high and self._enter("battery_high"):
                    alerts.append(("battery_high", f"Battery at {pct}% — you can unplug.", "low"))
            else:
                self.active.discard("battery_high")
                if pct <= crit and self._enter("battery_critical"):
                    self.active.add("battery_low")
                    alerts.append(("battery_critical", f"Battery critical: {pct}%. Plug in now.", "critical"))
                elif pct <= low and self._enter("battery_low"):
                    alerts.append(("battery_low", f"Battery low: {pct}%. Time to plug in.", "normal"))
        ram = snap.get("ram")
        if ram is not None:
            limit = float(g("monitor.ram_high"))
            if ram >= limit and self._enter("ram_high"):
                alerts.append(("ram_high", f"Memory is {ram:.0f}% used. Say 'top processes' to see why.", "normal"))
            elif ram < limit - 5:
                self.active.discard("ram_high")
        cpu = snap.get("cpu")
        if cpu is not None:
            limit = float(g("monitor.cpu_high"))
            self._cpu_streak = self._cpu_streak + 1 if cpu >= limit else 0
            if self._cpu_streak >= int(g("monitor.cpu_sustain_checks")) and self._enter("cpu_high"):
                alerts.append(("cpu_high", f"CPU has been above {limit:.0f}% for a while.", "normal"))
            elif cpu < limit - 10:
                self.active.discard("cpu_high")
        low_free = float(g("monitor.disk_low_free_pct"))
        for path, free_pct in snap.get("disk") or []:
            key = f"disk_low:{path}"
            if free_pct <= low_free and self._enter(key):
                alerts.append((key, f"Disk space low on {path}: {free_pct:.0f}% free.", "normal"))
            elif free_pct > low_free + 2:
                self.active.discard(key)
        return alerts

    def tick(self) -> None:
        try:
            for key, msg, urgency in self.evaluate(self.system.snapshot()):
                log.warning("monitor alert %s: %s", key, msg)
                self.on_alert(msg, urgency)
        except Exception:
            log.exception("monitor tick failed")

    def _loop(self) -> None:
        while not self._stop.wait(max(5, int(self.settings.get("monitor.interval_s") or 60))):
            self.tick()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> dict:
        if self.running:
            return ok("Monitoring is already running.")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="jarvis-monitor", daemon=True)
        self._thread.start()
        return ok("Background monitoring on.")

    def stop(self) -> dict:
        self._stop.set()
        return ok("Background monitoring off.")
