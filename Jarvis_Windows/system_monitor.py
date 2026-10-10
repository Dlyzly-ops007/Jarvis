import os
import json
import threading
import datetime
from collections import deque

import tkinter as tk

try:
    import psutil
    _HAVE_PSUTIL = True
except ImportError:
    _HAVE_PSUTIL = False
    print("monitor: psutil not installed, CPU/RAM/battery will be blank. "
          "pip install psutil")

_NVML = False
try:
    import pynvml
    pynvml.nvmlInit()
    _nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
    _NVML = True
except Exception:
    _nvml_handle = None

try:
    import wmi
    import pythoncom
    _HAVE_WMI = True
except Exception:
    _HAVE_WMI = False


_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(_HERE, "monitor_data.json")

DEFAULT_INTERVAL = 180
CAPACITY = 10

SERIES_KEYS = (
    "cpu_percent", "ram_percent", "cpu_temp",
    "gpu_temp", "gpu_load", "battery_percent",
)
UNITS = {
    "cpu_percent": "%", "ram_percent": "%", "cpu_temp": "\u00b0C",
    "gpu_temp": "\u00b0C", "gpu_load": "%", "battery_percent": "%",
}

_series = {k: deque(maxlen=CAPACITY) for k in SERIES_KEYS}
_single = {}
_last_collect = None

_lock = threading.Lock()
_thread = None
_stop = None


def _now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _cpu_percent():
    if not _HAVE_PSUTIL:
        return None
    try:
        return round(psutil.cpu_percent(interval=None), 1)
    except Exception:
        return None


def _ram_percent():
    if not _HAVE_PSUTIL:
        return None
    try:
        return round(psutil.virtual_memory().percent, 1)
    except Exception:
        return None


def _cpu_temp():
    if _HAVE_PSUTIL:
        try:
            temps = psutil.sensors_temperatures()
        except Exception:
            temps = {}
        if temps:
            for key in ("coretemp", "k10temp", "zenpower", "acpitz", "cpu_thermal"):
                if temps.get(key):
                    return round(float(temps[key][0].current), 1)
            for arr in temps.values():
                if arr:
                    return round(float(arr[0].current), 1)
    if _HAVE_WMI:
        try:
            w = wmi.WMI(namespace="root\\wmi")
            zones = w.MSAcpi_ThermalZoneTemperature()
            if zones:
                tenths_kelvin = zones[0].CurrentTemperature
                return round((tenths_kelvin / 10.0) - 273.15, 1)
        except Exception:
            pass
    return None


def _gpu():
    out = {"temp": None, "load": None}
    if _NVML and _nvml_handle is not None:
        try:
            out["temp"] = int(pynvml.nvmlDeviceGetTemperature(
                _nvml_handle, pynvml.NVML_TEMPERATURE_GPU))
            out["load"] = int(pynvml.nvmlDeviceGetUtilizationRates(_nvml_handle).gpu)
            return out
        except Exception:
            pass
    try:
        import GPUtil
        gpus = GPUtil.getGPUs()
        if gpus:
            out["temp"] = round(float(gpus[0].temperature), 1)
            out["load"] = round(float(gpus[0].load) * 100, 1)
    except Exception:
        pass
    return out


def _battery_wear():
    if not _HAVE_WMI:
        return None
    try:
        w = wmi.WMI(namespace="root\\wmi")
        design = w.BatteryStaticData()[0].DesignedCapacity
        full = w.BatteryFullChargedCapacity()[0].FullChargedCapacity
        if design and full and design > 0:
            return round((1 - (full / design)) * 100, 1)
    except Exception:
        pass
    return None


def _battery():
    out = {"percent": None, "charging": None, "plugged": None,
           "secsleft": None, "wear": None}
    if _HAVE_PSUTIL:
        try:
            b = psutil.sensors_battery()
        except Exception:
            b = None
        if b is not None:
            out["percent"] = round(float(b.percent), 1)
            out["plugged"] = bool(b.power_plugged)
            out["charging"] = bool(b.power_plugged)
            if b.secsleft is not None and b.secsleft >= 0:
                out["secsleft"] = int(b.secsleft)
    out["wear"] = _battery_wear()
    return out


def _push(key, value):
    _series[key].append({
        "t": _now_iso(),
        "v": (None if value is None else float(value)),
    })


def collect_once():
    global _last_collect
    now = _now_iso()

    cpu = _cpu_percent()
    ram = _ram_percent()
    ctemp = _cpu_temp()
    gpu = _gpu()
    bat = _battery()

    with _lock:
        _push("cpu_percent", cpu)
        _push("ram_percent", ram)
        _push("cpu_temp", ctemp)
        _push("gpu_temp", gpu["temp"])
        _push("gpu_load", gpu["load"])
        _push("battery_percent", bat["percent"])

        _single["battery_charging"] = {"t": now, "v": bat["charging"]}
        _single["battery_plugged"] = {"t": now, "v": bat["plugged"]}
        _single["battery_wear_percent"] = {"t": now, "v": bat["wear"]}
        _single["battery_secsleft"] = {"t": now, "v": bat["secsleft"]}
        _last_collect = now

    _write_json()


def _write_json():
    try:
        with _lock:
            payload = {
                "updated": _last_collect,
                "interval_seconds": DEFAULT_INTERVAL,
                "capacity": CAPACITY,
                "series": {
                    k: {"unit": UNITS[k], "points": list(_series[k])}
                    for k in SERIES_KEYS
                },
                "single": dict(_single),
            }
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"monitor: could not write {DATA_PATH}: {e}")


def snapshot():
    with _lock:
        return {
            "series": {k: list(v) for k, v in _series.items()},
            "single": dict(_single),
            "updated": _last_collect,
        }


def _loop(interval):
    if _HAVE_WMI:
        try:
            pythoncom.CoInitialize()
        except Exception:
            pass
    if _HAVE_PSUTIL:
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
    while not _stop.is_set():
        try:
            collect_once()
        except Exception as e:
            print(f"monitor: collect error: {e}")
        _stop.wait(interval)
    if _HAVE_WMI:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def start(interval=DEFAULT_INTERVAL):
    global _thread, _stop
    if _thread is not None and _thread.is_alive():
        return
    _stop = threading.Event()
    _thread = threading.Thread(target=_loop, args=(interval,), daemon=True)
    _thread.start()


def stop():
    if _stop is not None:
        _stop.set()
    if _thread is not None:
        _thread.join(timeout=5)
    if _NVML:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


_BG      = "#080b12"
_PANEL   = "#0e1524"
_GRID    = "#1b2740"
_TEXT    = "#c8d6e5"
_MUTED   = "#54617a"
_MONO    = "Consolas"

_CHART_STYLE = {
    "cpu_percent":     {"title": "CPU LOAD",    "color": "#00e5ff", "vmin": 0, "vmax": 100},
    "ram_percent":     {"title": "MEMORY",      "color": "#7c4dff", "vmin": 0, "vmax": 100},
    "cpu_temp":        {"title": "CPU TEMP",    "color": "#ff9f1c", "vmin": None, "vmax": None},
    "gpu_load":        {"title": "GPU LOAD",    "color": "#39ff14", "vmin": 0, "vmax": 100},
    "gpu_temp":        {"title": "GPU TEMP",    "color": "#ff3b6b", "vmin": None, "vmax": None},
    "battery_percent": {"title": "BATTERY",     "color": "#2af5c0", "vmin": 0, "vmax": 100},
}
_GRID_ORDER = ("cpu_percent", "ram_percent", "cpu_temp",
               "gpu_load", "gpu_temp", "battery_percent")

_WIN_W, _WIN_H = 920, 660

_dash = None
_dash_canvas = None
_dash_after = None


def _fmt_hms(secs):
    if secs is None:
        return "--"
    h, rem = divmod(int(secs), 3600)
    m = rem // 60
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _ago(iso):
    if not iso:
        return "never"
    try:
        then = datetime.datetime.fromisoformat(iso)
        s = int((datetime.datetime.now() - then).total_seconds())
        if s < 60:
            return f"{s}s ago"
        return f"{s // 60}m {s % 60}s ago"
    except Exception:
        return iso


def _plot_line(cv, x, y, w, h, points, color, vmin, vmax):
    for i in range(5):
        gy = y + h * i / 4
        cv.create_line(x, gy, x + w, gy, fill=_GRID)

    vals = [p["v"] for p in points]
    real = [v for v in vals if v is not None]
    if not real:
        cv.create_text(x + w / 2, y + h / 2, text="no data",
                       fill=_MUTED, font=(_MONO, 9))
        return

    lo = vmin if vmin is not None else min(real)
    hi = vmax if vmax is not None else max(real)
    if hi - lo < 1e-6:
        hi = lo + 1
    if vmax is None:
        hi += (hi - lo) * 0.15
    if vmin is None:
        lo -= (hi - lo) * 0.10

    n = max(len(points), 1)

    def X(i):
        return x + (w * (i / max(n - 1, 1)))

    def Y(v):
        return y + h - (h * (v - lo) / (hi - lo))

    coords = [(X(i), Y(v)) for i, v in enumerate(vals) if v is not None]

    if len(coords) >= 2:
        area = [(coords[0][0], y + h)] + coords + [(coords[-1][0], y + h)]
        flat_area = [c for xy in area for c in xy]
        cv.create_polygon(*flat_area, fill=color, stipple="gray12", outline="")
        flat = [c for xy in coords for c in xy]
        cv.create_line(*flat, fill=color, width=6, stipple="gray50",
                       joinstyle="round", capstyle="round")
        cv.create_line(*flat, fill=color, width=2,
                       joinstyle="round", capstyle="round")

    for (cx, cy) in coords:
        cv.create_oval(cx - 2, cy - 2, cx + 2, cy + 2, fill=color, outline="")
    lx, ly = coords[-1]
    cv.create_oval(lx - 4, ly - 4, lx + 4, ly + 4, outline=color, width=2)


def _card(cv, x, y, w, h, key, series):
    style = _CHART_STYLE[key]
    cv.create_rectangle(x, y, x + w, y + h, fill=_PANEL, outline=_GRID)
    cv.create_text(x + 12, y + 10, anchor="nw", text=style["title"],
                   fill=_MUTED, font=(_MONO, 9))

    vals = [p["v"] for p in series if p["v"] is not None]
    cur = vals[-1] if vals else None
    cur_txt = ("--" if cur is None else f"{cur:g}{UNITS[key]}")
    cv.create_text(x + 12, y + 22, anchor="nw", text=cur_txt,
                   fill=style["color"], font=(_MONO, 17, "bold"))

    _plot_line(cv, x + 12, y + 54, w - 24, h - 66, series,
               style["color"], style["vmin"], style["vmax"])


def _battery_panel(cv, x, y, w, h, snap):
    cv.create_rectangle(x, y, x + w, y + h, fill=_PANEL, outline=_GRID)
    cv.create_text(x + 16, y + 12, anchor="nw", text="BATTERY",
                   fill=_MUTED, font=(_MONO, 9))

    single = snap["single"]
    bp = snap["series"].get("battery_percent") or []
    pct = None
    for p in reversed(bp):
        if p["v"] is not None:
            pct = p["v"]
            break
    charging = (single.get("battery_charging") or {}).get("v")
    wear = (single.get("battery_wear_percent") or {}).get("v")
    secsleft = (single.get("battery_secsleft") or {}).get("v")

    if pct is not None and pct <= 20 and not charging:
        col = "#ff3b6b"
    elif charging:
        col = "#39ff14"
    else:
        col = "#00e5ff"

    r = min(h, w) / 2 - 26
    cx = x + 26 + r
    cy = y + h / 2 + 6
    cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=_GRID, width=12)
    if pct is not None:
        cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=90,
                      extent=-3.6 * pct, style="arc", outline=col, width=12)
        cv.create_text(cx, cy - 6, text=f"{pct:g}%", fill=col,
                       font=(_MONO, 22, "bold"))
    else:
        cv.create_text(cx, cy - 6, text="--", fill=_MUTED, font=(_MONO, 22, "bold"))

    state = "CHARGING" if charging else "DISCHARGING"
    if charging is None:
        state = "NO BATTERY"
    cv.create_text(cx, cy + 22, text=state, fill=col, font=(_MONO, 9, "bold"))

    tx = cx + r + 40
    ty = y + 34
    rows = [
        ("STATUS", state),
        ("TIME LEFT", _fmt_hms(secsleft) if not charging else "on AC"),
        ("WEAR", f"{wear:g}%" if wear is not None else "n/a"),
    ]
    for label, value in rows:
        cv.create_text(tx, ty, anchor="nw", text=label, fill=_MUTED, font=(_MONO, 9))
        cv.create_text(tx + 130, ty, anchor="nw", text=value, fill=_TEXT,
                       font=(_MONO, 12, "bold"))
        ty += 30

    if wear is not None:
        bx, by, bw = tx, ty + 6, w - (tx - x) - 24
        cv.create_rectangle(bx, by, bx + bw, by + 10, outline=_GRID)
        fillw = bw * max(0.0, min(wear, 100)) / 100.0
        wc = "#ff3b6b" if wear >= 30 else ("#ff9f1c" if wear >= 15 else "#39ff14")
        cv.create_rectangle(bx, by, bx + fillw, by + 10, fill=wc, outline="")


def _redraw():
    global _dash_after
    if _dash is None or _dash_canvas is None:
        return
    cv = _dash_canvas
    cv.delete("all")
    snap = snapshot()

    cv.create_rectangle(0, 0, _WIN_W, 46, fill=_PANEL, outline="")
    cv.create_text(20, 23, anchor="w", text="JARVIS  \u00b7  SYSTEM MONITOR",
                   fill="#00e5ff", font=(_MONO, 14, "bold"))
    cv.create_text(_WIN_W - 20, 23, anchor="e",
                   text=f"updated {_ago(snap['updated'])}  \u00b7  every {DEFAULT_INTERVAL // 60} min",
                   fill=_MUTED, font=(_MONO, 9))

    pad = 16
    top = 46 + pad
    cols, rows = 3, 2
    gap = 12
    grid_w = _WIN_W - 2 * pad
    grid_h = 400
    cw = (grid_w - (cols - 1) * gap) / cols
    ch = (grid_h - (rows - 1) * gap) / rows

    for idx, key in enumerate(_GRID_ORDER):
        r, c = divmod(idx, cols)
        x = pad + c * (cw + gap)
        y = top + r * (ch + gap)
        _card(cv, x, y, cw, ch, key, snap["series"].get(key, []))

    by = top + grid_h + gap
    _battery_panel(cv, pad, by, grid_w, _WIN_H - by - pad, snap)

    _dash_after = _dash.after(2000, _redraw)


def _close_dashboard():
    global _dash, _dash_canvas, _dash_after
    if _dash_after is not None and _dash is not None:
        try:
            _dash.after_cancel(_dash_after)
        except Exception:
            pass
    _dash_after = None
    if _dash is not None:
        try:
            _dash.destroy()
        except Exception:
            pass
    _dash = None
    _dash_canvas = None


def open_dashboard(parent):
    global _dash, _dash_canvas
    if _dash is not None:
        try:
            _dash.deiconify()
            _dash.lift()
            _dash.focus_force()
            return
        except Exception:
            _close_dashboard()

    _dash = tk.Toplevel(parent)
    _dash.title("JARVIS - System Monitor")
    _dash.geometry(f"{_WIN_W}x{_WIN_H}")
    _dash.resizable(False, False)
    _dash.configure(bg=_BG)
    _dash.protocol("WM_DELETE_WINDOW", _close_dashboard)

    _dash_canvas = tk.Canvas(_dash, width=_WIN_W, height=_WIN_H,
                             bg=_BG, highlightthickness=0)
    _dash_canvas.pack(fill="both", expand=True)

    _redraw()
    _dash.lift()
    _dash.focus_force()
