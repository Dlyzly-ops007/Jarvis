import os
import queue
import threading
import tkinter as tk

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError as e:
    raise SystemExit(
        "gui_main.py needs pystray and pillow:\n"
        "    pip install pystray pillow\n"
        f"(import failed: {e})"
    )

import jarvis_main as jarvis
import voice_main as voice
import system_monitor as monitor
import notificationss as notification


_HERE = os.path.dirname(os.path.abspath(__file__))
ICON_CANDIDATES = (
    os.path.join(_HERE, "jarvis.png"),
    os.path.join(_HERE, "jarvis.ico"),
)
HISTORY_PATH = os.path.join(_HERE, "command_history.json")
MAX_HISTORY = 300


_root = None
_icon = None
_ui_queue = queue.Queue()

_history = []
_history_lock = threading.Lock()

_type_win = None
_entry = None
_history_list = None

_controls_win = None
_btn_listen = None
_btn_speak = None


def _post(fn):
    _ui_queue.put(fn)


def _drain_ui_queue():
    while True:
        try:
            fn = _ui_queue.get_nowait()
        except queue.Empty:
            break
        try:
            fn()
        except Exception as e:
            print(f"UI callback failed: {e}")
    if _root is not None:
        _root.after(80, _drain_ui_queue)


def _load_history():
    global _history
    try:
        import json
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            with _history_lock:
                _history = [str(x) for x in data][:MAX_HISTORY]
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"could not load history: {e}")


def _save_history():
    try:
        import json
        with _history_lock:
            snapshot = list(_history)
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"could not save history: {e}")


def _remember_command(text):
    norm = (text or "").strip()
    if not norm:
        return False
    lowered = norm.lower()
    with _history_lock:
        for existing in _history:
            if existing.lower() == lowered:
                return False
        _history.insert(0, norm)
        del _history[MAX_HISTORY:]
    _save_history()
    return True


def run_command(text, on_done=None):
    def worker():
        cmd = (text or "").strip()
        if not cmd:
            return
        print(f"\nYou: {cmd}")
        name = None
        try:
            name = jarvis.dispatch(cmd)
        except Exception as e:
            print(f"command failed: {e}")
            name = None

        added = False
        if name and name != "fallback":
            added = _remember_command(cmd)

        if on_done is not None:
            _post(lambda: on_done(name, added))

    threading.Thread(target=worker, daemon=True).start()


def _on_cmd_done(name, added):
    if added:
        _refresh_history_list()


def _show_type_window():
    global _type_win, _entry, _history_list
    if _type_win is None:
        _type_win = tk.Toplevel(_root)
        _type_win.title("JARVIS - Command")
        _type_win.geometry("440x380")
        _type_win.minsize(320, 260)
        _type_win.protocol("WM_DELETE_WINDOW", _type_win.withdraw)

        top = tk.Frame(_type_win)
        top.pack(fill="x", padx=8, pady=8)
        _entry = tk.Entry(top)
        _entry.pack(side="left", fill="x", expand=True)
        _entry.bind("<Return>", lambda e: _submit_from_entry())
        tk.Button(top, text="Send", command=_submit_from_entry).pack(side="left", padx=(6, 0))

        mid = tk.Frame(_type_win)
        mid.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        scrollbar = tk.Scrollbar(mid)
        scrollbar.pack(side="right", fill="y")
        _history_list = tk.Listbox(mid, activestyle="dotbox", yscrollcommand=scrollbar.set)
        _history_list.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=_history_list.yview)
        _history_list.bind("<Double-Button-1>", lambda e: _run_selected())
        _history_list.bind("<Return>", lambda e: _run_selected())

        tk.Label(
            _type_win,
            text="Double-click a past command to run it again",
            fg="#666",
        ).pack(pady=(0, 6))

    _refresh_history_list()
    _type_win.deiconify()
    _type_win.lift()
    _type_win.focus_force()
    if _entry is not None:
        _entry.focus_set()


def _refresh_history_list():
    if _history_list is None:
        return
    _history_list.delete(0, tk.END)
    with _history_lock:
        items = list(_history)
    for cmd in items:
        _history_list.insert(tk.END, cmd)


def _submit_from_entry():
    if _entry is None:
        return
    text = _entry.get().strip()
    if not text:
        return
    _entry.delete(0, tk.END)
    run_command(text, on_done=_on_cmd_done)


def _run_selected():
    if _history_list is None:
        return
    sel = _history_list.curselection()
    if not sel:
        return
    run_command(_history_list.get(sel[0]), on_done=_on_cmd_done)


def _show_controls_window():
    global _controls_win, _btn_listen, _btn_speak
    if _controls_win is None:
        _controls_win = tk.Toplevel(_root)
        _controls_win.title("JARVIS - Controls")
        _controls_win.geometry("260x240")
        _controls_win.resizable(False, False)
        _controls_win.protocol("WM_DELETE_WINDOW", _controls_win.withdraw)

        _btn_listen = tk.Button(_controls_win, width=26, command=_ui_toggle_listening)
        _btn_listen.pack(pady=(12, 4))
        _btn_speak = tk.Button(_controls_win, width=26, command=_ui_toggle_speaking)
        _btn_speak.pack(pady=4)
        tk.Button(_controls_win, width=26, text="Enable both",
                  command=lambda: _set_both(True)).pack(pady=4)
        tk.Button(_controls_win, width=26, text="Disable both",
                  command=lambda: _set_both(False)).pack(pady=4)
        tk.Button(_controls_win, width=26, text="Exit JARVIS",
                  bg="#b00020", fg="white", command=_exit_app).pack(pady=(14, 6))

    _refresh_controls()
    _controls_win.deiconify()
    _controls_win.lift()
    _controls_win.focus_force()


def _refresh_controls():
    if _btn_listen is not None:
        on = voice.is_listening_enabled()
        _btn_listen.config(text=("Listening: ON  (click to mute)" if on
                                 else "Listening: OFF  (click to enable)"))
    if _btn_speak is not None:
        on = voice.is_speaking_enabled()
        _btn_speak.config(text=("Speaking: ON  (click to mute)" if on
                                else "Speaking: OFF  (click to enable)"))


def _ui_toggle_listening():
    voice.set_listening(not voice.is_listening_enabled())
    _refresh_controls()
    _update_tray_menu()


def _ui_toggle_speaking():
    voice.set_speaking(not voice.is_speaking_enabled())
    _refresh_controls()
    _update_tray_menu()


def _set_both(enabled):
    voice.set_voice(enabled)
    _refresh_controls()
    _update_tray_menu()


def _make_icon_image():
    for path in ICON_CANDIDATES:
        if os.path.exists(path):
            try:
                return Image.open(path)
            except Exception as e:
                print(f"could not load icon {path}: {e}")
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=(28, 90, 200, 255))
    d.text((25, 20), "J", fill="white")
    return img


def _update_tray_menu():
    try:
        if _icon is not None:
            _icon.update_menu()
    except Exception:
        pass


def _tray_open_type(icon, item):
    _post(_show_type_window)


def _tray_open_controls(icon, item):
    _post(_show_controls_window)


def _tray_open_monitor(icon, item):
    _post(lambda: monitor.open_dashboard(_root))


def _tray_toggle_listening(icon, item):
    voice.set_listening(not voice.is_listening_enabled())
    icon.update_menu()
    _post(_refresh_controls)


def _tray_toggle_speaking(icon, item):
    voice.set_speaking(not voice.is_speaking_enabled())
    icon.update_menu()
    _post(_refresh_controls)


def _tray_enable_both(icon, item):
    voice.set_voice(True)
    icon.update_menu()
    _post(_refresh_controls)


def _tray_disable_both(icon, item):
    voice.set_voice(False)
    icon.update_menu()
    _post(_refresh_controls)


def _tray_exit(icon, item):
    _post(_exit_app)
    icon.stop()


def _build_menu():
    return pystray.Menu(
        pystray.MenuItem("Type command...", _tray_open_type, default=True),
        pystray.MenuItem("Controls...", _tray_open_controls),
        pystray.MenuItem("Monitor graphs...", _tray_open_monitor),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Listening", _tray_toggle_listening,
                         checked=lambda item: voice.is_listening_enabled()),
        pystray.MenuItem("Speaking", _tray_toggle_speaking,
                         checked=lambda item: voice.is_speaking_enabled()),
        pystray.MenuItem("Enable both", _tray_enable_both),
        pystray.MenuItem("Disable both", _tray_disable_both),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", _tray_exit),
    )


def _exit_app():
    try:
        notification.offline()
    except Exception:
        pass
    try:
        monitor.stop()
    except Exception:
        pass
    try:
        voice.shutdown()
    except Exception as e:
        print(f"voice shutdown error: {e}")
    try:
        if _icon is not None:
            _icon.stop()
    except Exception:
        pass
    try:
        if _root is not None:
            _root.destroy()
    except Exception:
        pass


def main():
    global _root, _icon

    _load_history()

    _root = tk.Tk()
    _root.withdraw()
    _root.title("JARVIS")
    _root.after(80, _drain_ui_queue)

    voice.start_listening(lambda cmd: run_command(cmd, on_done=_on_cmd_done))

    monitor.start()
    notification.online()

    _icon = pystray.Icon("jarvis", _make_icon_image(), "JARVIS", menu=_build_menu())
    _icon.run_detached()

    print("JARVIS running in the tray. "
          "Left-click the icon to type, right-click for controls.")

    try:
        _root.mainloop()
    finally:
        try:
            voice.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
