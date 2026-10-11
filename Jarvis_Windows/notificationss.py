import os

_HERE = os.path.dirname(os.path.abspath(__file__))

_ICON = None
for _cand in (os.path.join(_HERE, "jarvis.ico"), os.path.join(_HERE, "jarvis.png")):
    if os.path.exists(_cand):
        _ICON = _cand
        break

APP_ID = "JARVIS"

try:
    from winotify import Notification, audio
    _HAVE_WINOTIFY = True
except ImportError:
    _HAVE_WINOTIFY = False


def notify(title, msg, silent=True):
    if not _HAVE_WINOTIFY:
        print(f"[notify] {title}: {msg}")
        return
    try:
        kwargs = {"app_id": APP_ID, "title": title, "msg": msg}
        if _ICON:
            kwargs["icon"] = _ICON
        toast = Notification(**kwargs)
        if silent:
            try:
                toast.set_audio(audio.Silent, loop=False)
            except Exception:
                pass
        toast.show()
    except Exception as e:
        print(f"notification failed: {e}")


def online():
    notify("JARVIS", "Assistant is online and listening.", silent=True)


def offline():
    notify("JARVIS", "Assistant has been shut down.", silent=False)
