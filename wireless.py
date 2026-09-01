import platform
import subprocess

def _is_windows():
    return platform.system() == "Windows"

def _guard():
    if not _is_windows():
        return False, "wireless.py only supports Windows"
    return True, ""

def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return None, "", "command not found"
    except subprocess.TimeoutExpired:
        return None, "", "command timed out"
    except Exception as e:
        return None, "", str(e)


# Wifi
WIFI_IFACE_NAMES = ("Wi-Fi", "WiFi", "Wireless Network Connection")

def _find_wifi_iface():
    code, out, err = _run(["netsh", "interface", "show", "interface"])
    if code != 0:
        return None
    for line in out.splitlines():
        for name in WIFI_IFACE_NAMES:
            if name.lower() in line.lower():
                return name
    return None


def _wifi_state():
    """(ok, on|None, err)"""
    iface = _find_wifi_iface()
    if not iface:
        return False, None, "no Wi-Fi adapter found"
    code, out, err = _run(["netsh", "interface", "show", "interface", f"name={iface}"])
    if code != 0:
        return False, None, err or "failed to read Wi-Fi status"
    state = None
    for line in out.splitlines():
        if "Admin State" in line:
            state = line.split(":")[-1].strip().lower()
    if state is None:
        return False, None, "could not parse Wi-Fi state"
    return True, state == "enabled", None


def wifi_status():
    ok, msg = _guard()
    if not ok:
        return False, msg
    ok, on, err = _wifi_state()
    if not ok:
        return False, err
    return True, "Wi-Fi is on" if on else "Wi-Fi is off"


def wifi_on():
    ok, msg = _guard()
    if not ok:
        return False, msg
    iface = _find_wifi_iface()
    if not iface:
        return False, "no Wi-Fi adapter found"
    code, out, err = _run(["netsh", "interface", "set", "interface", f"name={iface}", "admin=enabled"])
    if code == 0:
        return True, "Wi-Fi enabled"
    return False, err or "unable to enable Wi-Fi (try running as admin)"


def wifi_off():
    ok, msg = _guard()
    if not ok:
        return False, msg
    iface = _find_wifi_iface()
    if not iface:
        return False, "no Wi-Fi adapter found"
    code, out, err = _run(["netsh", "interface", "set", "interface", f"name={iface}", "admin=disabled"])
    if code == 0:
        return True, "Wi-Fi disabled"
    return False, err or "unable to disable Wi-Fi (try running as admin)"


def wifi_toggle():
    ok, msg = _guard()
    if not ok:
        return False, msg
    ok, on, err = _wifi_state()
    if not ok:
        return False, err
    return wifi_off() if on else wifi_on()


#Bluetooth

_BT_FIND_PS = (
    "Get-PnpDevice -Class Bluetooth | "
    "Where-Object { $_.Status -ne 'Error' } | "
    "Select-Object -First 1 -ExpandProperty InstanceId"
)

def _find_bt_device_id():
    code, out, err = _run(["powershell", "-NoProfile", "-Command", _BT_FIND_PS])
    if code != 0 or not out:
        return None
    return out.splitlines()[0].strip()


def _bt_state():
    """(ok, on|None, err)"""
    dev_id = _find_bt_device_id()
    if not dev_id:
        return False, None, "no Bluetooth adapter found"
    code, out, err = _run([
        "powershell", "-NoProfile", "-Command",
        f"(Get-PnpDevice -InstanceId '{dev_id}').Status"
    ])
    if code != 0:
        return False, None, err or "failed to read Bluetooth status"
    return True, out.strip().lower() == "ok", None


def bluetooth_status():
    ok, msg = _guard()
    if not ok:
        return False, msg
    ok, on, err = _bt_state()
    if not ok:
        return False, err
    return True, "Bluetooth is on" if on else "Bluetooth is off"


def bluetooth_on():
    ok, msg = _guard()
    if not ok:
        return False, msg
    dev_id = _find_bt_device_id()
    if not dev_id:
        return False, "no Bluetooth adapter found"
    code, out, err = _run([
        "powershell", "-NoProfile", "-Command",
        f"Enable-PnpDevice -InstanceId '{dev_id}' -Confirm:$false"
    ])
    if code == 0:
        return True, "Bluetooth enabled"
    return False, err or "unable to enable Bluetooth (try running as admin)"


def bluetooth_off():
    ok, msg = _guard()
    if not ok:
        return False, msg
    dev_id = _find_bt_device_id()
    if not dev_id:
        return False, "no Bluetooth adapter found"
    code, out, err = _run([
        "powershell", "-NoProfile", "-Command",
        f"Disable-PnpDevice -InstanceId '{dev_id}' -Confirm:$false"
    ])
    if code == 0:
        return True, "Bluetooth disabled"
    return False, err or "unable to disable Bluetooth (try running as admin)"


def bluetooth_toggle():
    ok, msg = _guard()
    if not ok:
        return False, msg
    ok, on, err = _bt_state()
    if not ok:
        return False, err
    return bluetooth_off() if on else bluetooth_on()


if __name__ == "__main__":
    for fn in (wifi_status, bluetooth_status):
        print(fn.__name__, "->", fn())
