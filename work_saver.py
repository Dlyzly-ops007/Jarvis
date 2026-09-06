import json
import os
import platform
import string
import subprocess
import time
import webbrowser
from datetime import datetime

try:
    import win32api, win32con, win32gui, win32process
    import win32com.client
    import psutil
    import pyautogui
    import pyperclip
    import pygetwindow as gw
except ImportError:
    win32api = win32con = win32gui = win32process = win32com = None
    psutil = pyautogui = pyperclip = gw = None

SESSION_FILE = "session.json"
WORK_PROFILES_FILE = "work_profiles.json"
LAYOUT_WORK_FILE = "layout_work.json"
BLOCKLIST_FILE = "session_blocklist.json"

SYSTEM_SKIP = [
    "jarvis", "idle", "cmd", "powershell", "task manager",
    "settings", "control panel", "overlay", "nvidia", "amd",
    "xbox", "game bar", "start", "action center",
    "volume mixer", "snipping tool", "windows input experience",
    "program manager", "shell_traywnd", "battery", "clock", "lockapp",
    "cortana", "widgets", "microsoft text input", "command palette",
]
SYSTEM_SKIP_EXACT = ["python", "pythonw"]

_pause_time = [None]
_pending_overwrite = {"name": None, "data": None, "file": None}


def _is_windows():
    return platform.system() == "Windows"


def _guard():
    if not _is_windows():
        return False, "work_saver only supports Windows"
    if win32gui is None:
        return False, "missing dependency -- pip install pywin32 psutil pyautogui pyperclip pygetwindow"
    return True, ""


def _blocklist():
    try:
        with open(BLOCKLIST_FILE) as f:
            return json.load(f)
    except Exception:
        return {"urls": [], "apps": []}


def _window_layout(hwnd):
    try:
        show_cmd = win32gui.GetWindowPlacement(hwnd)[1]
        if show_cmd == win32con.SW_SHOWMAXIMIZED:
            return "maximized", list(win32gui.GetWindowRect(hwnd))
        if show_cmd == win32con.SW_SHOWMINIMIZED:
            return "maximized", None
        rect = list(win32gui.GetWindowRect(hwnd))
        mon = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        work = win32api.GetMonitorInfo(mon)["Work"]
        wa_w, wa_h = work[2] - work[0], work[3] - work[1]
        win_w, win_h = rect[2] - rect[0], rect[3] - rect[1]
        if win_w >= wa_w * 0.95 and win_h >= wa_h * 0.95:
            return "maximized", rect
        return "snapped", rect
    except Exception as e:
        print(f"layout detection failed: {e}")
        return "maximized", None


def _chrome_profiles():
    user_data = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "User Data")
    try:
        with open(os.path.join(user_data, "Local State"), encoding="utf-8") as f:
            state = json.load(f)
        cache = state.get("profile", {}).get("info_cache", {})
        return {folder: info.get("name", folder) for folder, info in cache.items()}
    except Exception as e:
        print(f"couldn't read chrome profiles: {e}")
        return {"Default": "Default"}


def _find_chrome_exe():
    for c in (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ):
        if os.path.exists(c):
            return c
    return "chrome"


def _has_layout(session):
    return any(item.get("window_state") == "snapped" for item in session)


def _default_ask_text(prompt):
    import tkinter as tk
    result = [""]
    root = tk.Tk()
    root.withdraw()
    popup = tk.Toplevel(root)
    popup.title("JARVIS")
    popup.grab_set()
    tk.Label(popup, text=prompt, justify="left", wraplength=360).pack(padx=20, pady=(10, 4))
    entry = tk.Entry(popup, width=40)
    entry.pack(padx=20, pady=10)
    entry.focus()

    def submit():
        result[0] = entry.get()
        popup.destroy()

    tk.Button(popup, text="OK", command=submit).pack(pady=(0, 10))
    popup.bind("<Return>", lambda e: submit())
    popup.wait_window()
    root.destroy()
    return (result[0] or "").strip()


def capture_session(ask_text=None):
    ok, msg = _guard()
    if not ok:
        print(msg)
        return None

    ask_text = ask_text or _default_ask_text
    blocklist = _blocklist()
    session = []
    seen = set()
    alphabet = iter(string.ascii_lowercase)

    all_windows = []

    def enum_all(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd).strip().replace("\u200b", "")
        if not title:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            exe = psutil.Process(pid).name().lower()
        except Exception:
            exe = ""
        all_windows.append((hwnd, title, exe))

    win32gui.EnumWindows(enum_all, None)
    if not all_windows:
        return None

    chrome_count = sum(1 for _, _, exe in all_windows if "chrome.exe" in exe)
    chrome_profiles = _chrome_profiles() if chrome_count else {}

    for hwnd, title, exe in all_windows:
        if hwnd in seen:
            continue
        seen.add(hwnd)
        w_lower = title.lower()

        if any(x in w_lower for x in SYSTEM_SKIP):
            continue
        if any(x in exe for x in SYSTEM_SKIP_EXACT):
            continue

        is_chrome = "chrome.exe" in exe
        is_edge = "msedge.exe" in exe

        if is_chrome or is_edge:
            try:
                state, rect = _window_layout(hwnd)
                profile = None
                if is_chrome:
                    if chrome_count > 1:
                        win32gui.SetForegroundWindow(hwnd)
                        time.sleep(0.3)
                        options = ", ".join(f"{v} ({k})" for k, v in chrome_profiles.items())
                        typed = ask_text(
                            f"Which Chrome profile is this window?\n({title[:60]})\n\nAvailable: {options}"
                        ).strip()
                        profile = typed if typed in chrome_profiles else "Default"
                    else:
                        profile = "Default"

                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.BringWindowToTop(hwnd)
                win32com.client.Dispatch("WScript.Shell").SendKeys('%')
                time.sleep(0.3)
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(1.5)

                r = win32gui.GetWindowRect(hwnd)
                pyautogui.click((r[0] + r[2]) // 2, r[1] + 15)
                time.sleep(0.5)
                pyautogui.hotkey("ctrl", "1")
                time.sleep(0.8)

                urls, first = [], None
                for i in range(50):
                    pyperclip.copy("")
                    time.sleep(0.2)
                    pyautogui.hotkey("ctrl", "l")
                    time.sleep(0.4)
                    pyautogui.hotkey("ctrl", "a")
                    time.sleep(0.2)
                    pyautogui.hotkey("ctrl", "c")
                    time.sleep(0.5)
                    url = pyperclip.paste().strip()
                    pyautogui.press("escape")
                    time.sleep(0.2)

                    if url:
                        if i == 0:
                            first = url
                        elif url == first:
                            break
                        blocked = any(b in url for b in blocklist.get("urls", []))
                        if not blocked and url not in urls:
                            urls.append(url)

                    pyautogui.hotkey("ctrl", "tab")
                    time.sleep(0.6)

                for url in urls:
                    entry = {"type": "url", "value": url, "window_state": state,
                              "window_rect": rect, "chrome_profile": profile}
                    if entry not in session:
                        session.append(entry)
            except Exception as e:
                print(f"browser capture failed ({exe}): {e}")

        elif "file explorer" in w_lower or ("explorer.exe" in exe and "explorer" in w_lower):
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.5)
                pyautogui.hotkey("alt", "d")
                time.sleep(0.2)
                pyautogui.hotkey("ctrl", "a")
                time.sleep(0.1)
                pyautogui.hotkey("ctrl", "c")
                time.sleep(0.3)
                path = pyperclip.paste().strip()
                pyautogui.press("escape")
                if path and (":\\" in path or path.startswith("\\\\")):
                    entry = {"type": "folder", "value": path}
                    if entry not in session:
                        session.append(entry)
            except Exception as e:
                print(f"explorer capture failed: {e}")

        elif "notepad.exe" in exe or "notepad" in w_lower:
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.4)
                pyautogui.hotkey("ctrl", "s")
                time.sleep(0.5)
                active = gw.getActiveWindow()
                if active and "save as" in active.title.lower():
                    filename = next(alphabet) + "_jarvis.txt"
                    pyautogui.hotkey("ctrl", "a")
                    pyautogui.write(filename, interval=0.05)
                    pyautogui.press("enter")
                    time.sleep(0.3)
                    session.append({"type": "notepad", "value": filename})
                else:
                    session.append({"type": "notepad", "value": title.replace(" - Notepad", "").strip()})
            except Exception as e:
                print(f"notepad capture failed: {e}")

        else:
            try:
                if any(b in w_lower for b in blocklist.get("apps", [])):
                    continue
                exe_path = None
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    exe_path = psutil.Process(pid).exe()
                except Exception:
                    pass
                entry = {"type": "app", "value": title, "exe": exe_path}
                if entry not in session:
                    session.append(entry)
            except Exception as e:
                print(f"app capture failed: {e}")

    return session


def pause_work(ask_text=None):
    ok, msg = _guard()
    if not ok:
        return False, msg, {}
    session = capture_session(ask_text)
    if not session:
        return False, "nothing open to pause", {}
    _pause_time[0] = datetime.now()
    with open(SESSION_FILE, "w") as f:
        json.dump(session, f, indent=2)
    return True, f"paused, {len(session)} items saved", {"items": len(session)}


def continue_work():
    ok, msg = _guard()
    if not ok:
        return False, msg, {}

    info = {}
    if _pause_time[0] and (datetime.now() - _pause_time[0]).seconds <= 60:
        info["quick_resume"] = True
    _pause_time[0] = None

    try:
        with open(SESSION_FILE) as f:
            session = json.load(f)
    except json.JSONDecodeError:
        return False, "session file is corrupted", info
    except Exception:
        return False, "nothing saved", info
    if not session:
        return False, "nothing saved", info

    opened = 0
    for item in session:
        try:
            if item["type"] == "url":
                webbrowser.open(item["value"]); time.sleep(0.5); opened += 1
            elif item["type"] == "folder":
                subprocess.Popen(["explorer.exe", item["value"]]); time.sleep(0.3); opened += 1
            elif item["type"] == "notepad":
                subprocess.Popen(["notepad.exe", item["value"]]); time.sleep(0.3); opened += 1
            elif item["type"] == "app":
                exe = item.get("exe")
                if exe:
                    try:
                        subprocess.Popen(exe); opened += 1
                    except Exception as e:
                        print(f"failed to open {exe}: {e}")
                else:
                    print(f"no exe stored for '{item['value']}', skipping")
        except Exception as e:
            print(f"failed to open {item}: {e}")

    info.update(opened=opened, total=len(session))
    return True, f"resuming your work, opened {opened} of {len(session)} items", info


def save_work(name=None, ask_text=None):
    ok, msg = _guard()
    if not ok:
        return False, msg, {}
    ask_text = ask_text or _default_ask_text

    session = capture_session(ask_text)
    if not session:
        return False, "nothing open to save", {}
    target = LAYOUT_WORK_FILE if _has_layout(session) else WORK_PROFILES_FILE

    if not name:
        name = ask_text("Name this profile")
    name = (name or "").strip().lower()
    if not name:
        return False, "no name given, save cancelled", {}

    try:
        with open(target) as f:
            profiles = json.load(f)
    except Exception:
        profiles = {}

    if name in profiles:
        _pending_overwrite["name"] = name
        _pending_overwrite["data"] = session
        _pending_overwrite["file"] = target
        return False, f"a profile called {name} already exists -- say overwrite to replace it", {"needs_overwrite": True}

    profiles[name] = {
        "items": session,
        "created_on": datetime.now().strftime("%Y-%m-%d"),
        "last_opened": datetime.now().strftime("%Y-%m-%d"),
        "open_count": 0,
    }
    with open(target, "w") as f:
        json.dump(profiles, f, indent=2)

    tag = " as a layout" if target == LAYOUT_WORK_FILE else ""
    return True, f"saved{tag} as {name}, {len(session)} items captured", {"items": len(session), "file": target}


def handle_overwrite_confirm():
    if not _pending_overwrite["name"]:
        return False, "nothing to overwrite", {}

    name = _pending_overwrite["name"]
    data = _pending_overwrite["data"]
    target = _pending_overwrite["file"]

    try:
        with open(target) as f:
            profiles = json.load(f)
    except Exception:
        profiles = {}

    old_count = profiles.get(name, {}).get("open_count", 0)
    profiles[name] = {
        "items": data,
        "created_on": datetime.now().strftime("%Y-%m-%d"),
        "last_opened": datetime.now().strftime("%Y-%m-%d"),
        "open_count": old_count,
    }
    with open(target, "w") as f:
        json.dump(profiles, f, indent=2)

    _pending_overwrite["name"] = _pending_overwrite["data"] = _pending_overwrite["file"] = None
    return True, f"overwritten, {name} updated", {}


def _find_profile(name):
    name = name.lower()
    for fname in (LAYOUT_WORK_FILE, WORK_PROFILES_FILE):
        try:
            with open(fname) as f:
                profiles = json.load(f)
        except Exception:
            continue
        if name in profiles:
            return profiles, fname
    return None, None


def _open_layout_window(urls, rect, profile="Default"):
    chrome = _find_chrome_exe()
    existing = set()

    def snap_existing(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if "chrome.exe" in psutil.Process(pid).name().lower():
                    existing.add(hwnd)
            except Exception:
                pass

    win32gui.EnumWindows(snap_existing, None)

    args = [chrome]
    if profile and profile != "Default":
        args.append(f"--profile-directory={profile}")
    args.append("--new-window")
    subprocess.Popen(args + urls)

    new_hwnd = None
    for _ in range(20):
        time.sleep(0.3)
        found = []

        def find_new(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and hwnd not in existing:
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    if "chrome.exe" in psutil.Process(pid).name().lower() and win32gui.GetWindowText(hwnd):
                        found.append(hwnd)
                except Exception:
                    pass

        win32gui.EnumWindows(find_new, None)
        if found:
            new_hwnd = found[0]
            break

    if new_hwnd and rect:
        try:
            win32gui.ShowWindow(new_hwnd, win32con.SW_RESTORE)
            left, top, right, bottom = rect
            win32gui.MoveWindow(new_hwnd, left, top, right - left, bottom - top, True)
        except Exception as e:
            print(f"failed to position layout window: {e}")

    return len(urls)


def _open_session_items(session):
    opened = 0
    layout_groups = {}
    profile_groups = {}
    remaining = []

    for item in session:
        if item.get("type") != "url":
            remaining.append(item)
            continue
        if item.get("window_state") == "snapped" and item.get("window_rect"):
            layout_groups.setdefault(tuple(item["window_rect"]), []).append(item)
        elif item.get("chrome_profile"):
            profile_groups.setdefault(item["chrome_profile"], []).append(item["value"])
        else:
            remaining.append(item)

    for rect, items in layout_groups.items():
        try:
            urls = [it["value"] for it in items]
            profile = items[0].get("chrome_profile") or "Default"
            opened += _open_layout_window(urls, list(rect), profile)
            time.sleep(0.5)
        except Exception as e:
            print(f"failed to open layout window: {e}")

    chrome = _find_chrome_exe()
    for profile, urls in profile_groups.items():
        try:
            args = [chrome]
            if profile != "Default":
                args.append(f"--profile-directory={profile}")
            subprocess.Popen(args + urls)
            time.sleep(0.5)
            opened += len(urls)
        except Exception as e:
            print(f"failed to open profile '{profile}' tabs: {e}")

    for item in remaining:
        try:
            if item["type"] == "url":
                webbrowser.open(item["value"]); time.sleep(0.5); opened += 1
            elif item["type"] == "folder":
                subprocess.Popen(["explorer.exe", item["value"]]); time.sleep(0.3); opened += 1
            elif item["type"] == "notepad":
                subprocess.Popen(["notepad.exe", item["value"]]); time.sleep(0.3); opened += 1
            elif item["type"] == "app":
                exe = item.get("exe")
                if exe:
                    subprocess.Popen(exe); opened += 1
                else:
                    print(f"no exe for '{item['value']}', skipping")
        except Exception as e:
            print(f"failed to open {item}: {e}")

    return opened


def load_work(name):
    ok, msg = _guard()
    if not ok:
        return False, msg, {}

    profiles, source = _find_profile(name)
    if profiles is None:
        return False, f"no profile called {name} found", {}
    name_l = name.lower()
    profile = profiles[name_l]

    info = {}
    last_opened = profile.get("last_opened")
    if not last_opened:
        info["first_open"] = True
    else:
        info["days_since_last_opened"] = (datetime.now() - datetime.strptime(last_opened, "%Y-%m-%d")).days

    profile["open_count"] = profile.get("open_count", 0) + 1
    info["open_count"] = profile["open_count"]
    profile["last_opened"] = datetime.now().strftime("%Y-%m-%d")
    profiles[name_l] = profile
    with open(source, "w") as f:
        json.dump(profiles, f, indent=2)

    items = profile if isinstance(profile, list) else profile.get("items", [])
    opened = _open_session_items(items)
    info.update(opened=opened, total=len(items))
    return True, f"loaded {name}, opened {opened} of {len(items)} items", info
