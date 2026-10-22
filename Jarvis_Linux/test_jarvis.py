"""Tests for the router/coordinator and core logic. Standard library only:

    python3 -m unittest -v          (or: python3 -m pytest -q)

No real desktop actions happen: a FakePlatform records what would be opened,
launched or notified, and voice is a silent stub.
"""
from __future__ import annotations

import json
import os
import random
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from capabilities import AppLauncher, BackgroundMonitor, FileSearch, score_app
from core import Settings, coerce, fail, ok
from jarvis_main import Jarvis, Router, parse_choice, parse_duration, split_commands
from oslayer import AppEntry, PlatformBase, is_privileged_exec
from personality import Personality
from platform_linux import exec_to_argv, parse_desktop_file, split_terse


class FakePlatform(PlatformBase):
    name = "fake"

    def __init__(self, apps=None):
        self.apps = apps or []
        self.opened, self.urls, self.launched, self.notes = [], [], [], []

    def list_apps(self):
        return list(self.apps)

    def default_app(self, category, index):
        return None

    def launch_app(self, entry):
        self.launched.append(entry.name)
        return ok(f"Launched {entry.name}")

    def open_path(self, path):
        self.opened.append(path)
        return ok(f"Opened {path}")

    def open_url(self, url):
        self.urls.append(url)
        return ok(f"Opened {url}")

    def notify(self, title, body, urgency="normal", app_name="Jarvis", timeout_ms=6000):
        self.notes.append((title, body, urgency))
        return ok("sent")

    def user_dir(self, name):
        return None

    def cpu_stats(self):
        return {"percent": 12.0, "load": (0.1, 0.2, 0.3), "cores": 4, "model": "Fake CPU"}

    def memory_stats(self):
        return {"total": 8 << 30, "available": 6 << 30, "used": 2 << 30, "percent": 25.0,
                "swap_total": 0, "swap_used": 0}

    def battery(self):
        return {"percent": 55, "status": "Discharging", "charging": False, "plugged_in": False,
                "seconds_left": 3600, "count": 1}


class SilentVoice:
    output_enabled = False
    _q = __import__("queue").Queue()

    def __init__(self):
        self.said, self.toggles = [], []

    def say(self, text):
        self.said.append(text)

    def set_output(self, on):
        self.toggles.append(("out", on))
        self.output_enabled = on
        return ok(f"Voice output {'on' if on else 'off'}.")

    def set_input(self, on):
        self.toggles.append(("in", on))
        return fail("Voice input unavailable: test.", error="test") if on else ok("Voice input off.")

    def stop_speaking(self):
        pass

    def is_speaking(self):
        return False

    def status(self):
        return {"output": self.output_enabled, "tts": None, "input": False, "stt": "test"}

    def shutdown(self):
        pass


APPS = [
    AppEntry(name="Firefox ESR", exec="firefox-esr %u", desktop_id="firefox-esr.desktop", categories=("WebBrowser",)),
    AppEntry(name="Text Editor", exec="gnome-text-editor %U", desktop_id="org.gnome.TextEditor.desktop",
             categories=("TextEditor",)),
    AppEntry(name="Text Viewer", exec="textview", desktop_id="textview.desktop"),
    AppEntry(name="Root Terminal", exec="pkexec xfce4-terminal", desktop_id="root-term.desktop"),
    AppEntry(name="Visual Studio Code", exec="/usr/share/code/code --unity-launch %F", desktop_id="code.desktop"),
]


def make_jarvis(tmp: Path, **overrides) -> tuple[Jarvis, FakePlatform, list]:
    data = {"files": {"search_roots": [str(tmp)], "use_locate": False},
            "logging": {"dir": str(tmp / "logs")}, "personality": {"remark_chance": 0}}
    for k, v in overrides.items():
        data.setdefault(k, {}).update(v)
    settings = Settings(data, path=tmp / "cfg.json", file_data={})
    plat = FakePlatform(APPS)
    out: list[str] = []
    j = Jarvis(settings, platform=plat, voice=SilentVoice(), output=out.append)
    j.persona.rng = random.Random(1)
    return j, plat, out


class RouterTests(unittest.TestCase):
    def test_normalize_strips_wake_word_and_fillers(self):
        r = Router(wake_words=["jarvis"])
        self.assertEqual(r.normalize("Hey Jarvis, could you please open Firefox please?"), "open Firefox")
        self.assertEqual(r.normalize("jarvis"), "")
        self.assertEqual(r.normalize("  what time is it?!  "), "what time is it")

    def test_fullmatch_and_priority(self):
        r = Router(wake_words=[])
        r.add("low", [r"open (.+)"], lambda m: ok("low"), priority=50)
        r.add("high", [r"open terminal"], lambda m: ok("high"), priority=10)
        self.assertEqual(r.dispatch("open terminal")["text"], "high")
        self.assertEqual(r.dispatch("open firefox")["text"], "low")
        self.assertEqual(r.dispatch("please open nothing here and more")["intent"], "low")
        self.assertEqual(r.dispatch("reopen")["intent"], "unknown")      # no substring hijacking

    def test_handler_exception_becomes_failure(self):
        r = Router(wake_words=[])
        r.add("boom", [r"boom"], lambda m: 1 / 0)
        with self.assertLogs("jarvis.main", level="ERROR"):
            res = r.dispatch("boom")
        self.assertFalse(res["ok"])
        self.assertIn("ZeroDivisionError", res["error"])

    def test_split_commands(self):
        self.assertEqual(split_commands("open firefox and check battery"), ["open firefox", "check battery"])
        self.assertEqual(split_commands("find cats and dogs"), ["find cats and dogs"])
        self.assertEqual(split_commands("open files; what time is it then lock"),
                         ["open files", "what time is it", "lock"])
        self.assertEqual(split_commands("remind me in 5 minutes to open the door and check mail"),
                         ["remind me in 5 minutes to open the door and check mail"])
        self.assertEqual(split_commands(""), [])

    def test_parse_helpers(self):
        self.assertEqual(parse_choice("the second one", 3), 1)
        self.assertEqual(parse_choice("open 3", 3), 2)
        self.assertEqual(parse_choice("last", 4), 3)
        self.assertIsNone(parse_choice("7", 3))
        self.assertEqual(parse_duration("10", "minutes"), 600)
        self.assertEqual(parse_duration("an", "hour"), 3600)
        self.assertIsNone(parse_duration("lots", "minutes"))


class JarvisRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmp_ctx.name)
        self.j, self.plat, self.out = make_jarvis(self.tmp)

    def tearDown(self):
        self.j.shutdown()
        self.tmp_ctx.cleanup()

    def intent(self, text):
        return self.j.handle(text)[-1]["intent"]

    def test_intent_table(self):
        cases = {
            "what time is it": "time", "what's the date": "date", "hello": "greeting", "jarvis": "greeting",
            "system status": "system_status", "check battery": "battery", "how much ram do i have": "memory",
            "cpu usage": "cpu", "disk space": "disk", "uptime": "uptime", "top processes": "top_processes",
            "am i online": "network", "wifi status": "wifi_status", "scan wifi": "wifi_scan",
            "lock the screen": "lock", "voice status": "voice_status", "show settings": "settings_show",
            "search for kali tools": "web", "youtube lofi beats": "web_engine",
            "search linux on wikipedia": "web_site", "what is a kernel module": "question",
            "find report.pdf": "files", "find folder projects": "files", "where is my thesis": "files",
            "sudo apt update": "refuse_privileged", "open a root terminal": "refuse_privileged",
            "run the command ls": "refuse_shell", "shutdown the computer": "refuse_power",
            "reboot": "refuse_power", "spotify": "unported", "game mode on": "unported",
            "remind me in 5 minutes to stretch": "remind", "set a timer for 2 minutes": "remind",
            "notify me the build finished": "notify", "set search engine to google": "settings_set",
            "help": "help",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.intent(text), want)

    def test_open_app_and_category_alias(self):
        self.j.handle("open firefox")
        self.j.handle("open the browser")
        self.j.handle("launch code")
        self.assertEqual(self.plat.launched, ["Firefox ESR", "Firefox ESR", "Visual Studio Code"])

    def test_privileged_app_blocked(self):
        r = self.j.handle("open root terminal")[-1]      # explicit "root terminal" -> refused early
        self.assertFalse(r["ok"])
        r = self.j.apps.launch("Root Terminal")
        self.assertEqual(r["error"], "blocked")
        self.assertEqual(self.plat.launched, [])

    def test_ambiguous_app_then_choice(self):
        r = self.j.handle("open text")[-1]
        self.assertEqual(r["error"], "ambiguous")
        self.assertIsNotNone(self.j.pending)
        r = self.j.handle("the second one")[-1]
        self.assertTrue(r["ok"])
        self.assertEqual(self.plat.launched, ["Text Viewer"])
        self.assertIsNone(self.j.pending)

    def test_unknown_app(self):
        r = self.j.handle("open definitelynotanapp")[-1]
        self.assertFalse(r["ok"])
        self.assertEqual(self.plat.launched, [])

    def test_web_and_urls(self):
        self.j.handle("search for kali linux tools")
        self.j.handle("youtube lofi")
        self.j.handle("open github.com")
        self.j.handle("go to youtube")
        self.assertEqual(self.plat.urls, [
            "https://duckduckgo.com/?q=kali+linux+tools",
            "https://www.youtube.com/results?search_query=lofi",
            "https://github.com", "https://www.youtube.com"])

    def test_file_search_and_open_result(self):
        (self.tmp / "docs").mkdir()
        (self.tmp / "docs" / "report.pdf").write_text("x")
        (self.tmp / "docs" / "report-old.txt").write_text("x")
        (self.tmp / ".hidden").mkdir()
        (self.tmp / ".hidden" / "report.pdf").write_text("x")
        r = self.j.handle("find report")[-1]
        self.assertTrue(r["ok"])
        results = r["data"]["results"]
        self.assertEqual(len(results), 2)                          # hidden dir skipped
        self.assertTrue(results[0].endswith("report.pdf"))           # exact stem ranks first
        self.j.handle("open 2")
        self.assertEqual(self.plat.opened, [results[1]])
        r = self.j.handle("find pdfs about report")[-1]
        self.assertEqual([os.path.basename(p) for p in r["data"]["results"]], ["report.pdf"])
        r = self.j.handle("find folder docs")[-1]
        self.assertEqual(r["data"]["results"], [str(self.tmp / "docs")])
        r = self.j.handle("find nothing-like-this")[-1]
        self.assertFalse(r["ok"])

    def test_chain(self):
        results = self.j.handle("open firefox and check battery then what time is it")
        self.assertEqual([r["intent"] for r in results], ["open", "battery", "time"])

    def test_suggestion_yes(self):
        r = self.j.handle("systme status")[-1]
        self.assertEqual(r["intent"], "unknown")
        r = self.j.handle("yes")[-1]
        self.assertEqual(r["intent"], "system_status")

    def test_voice_toggles_are_independent(self):
        self.j.handle("voice output on")
        self.assertTrue(self.j.settings.get("voice.output_enabled"))
        r = self.j.handle("voice input on")[-1]
        self.assertFalse(r["ok"])                                  # stub says input unavailable
        self.assertFalse(self.j.settings.get("voice.input_enabled"))
        self.assertTrue(self.j.settings.get("voice.output_enabled"))
        self.j.handle("mute")
        self.assertFalse(self.j.settings.get("voice.output_enabled"))

    def test_settings_set_and_save(self):
        self.j.handle("set remark chance to 0.5")
        self.assertEqual(self.j.settings.get("personality.remark_chance"), 0.5)
        self.assertFalse(self.j.handle("set tts rate to fast")[-1]["ok"])
        self.assertFalse(self.j.handle("set nonsense to 3")[-1]["ok"])
        self.j.handle("call me Tony")
        self.assertTrue(self.j.handle("save settings")[-1]["ok"])
        saved = json.loads((self.tmp / "cfg.json").read_text())
        self.assertEqual(saved["personality"]["remark_chance"], 0.5)
        self.assertEqual(saved["user_name"], "Tony")
        self.assertNotIn("files", saved)                           # only changed keys persisted

    def test_reminder_fires_and_notifies(self):
        r = self.j.handle("remind me in 1 second to stretch")[-1]
        self.assertTrue(r["ok"])
        time.sleep(1.4)
        self.assertIn(("Jarvis", "Reminder: stretch", "normal"), self.plat.notes)
        self.assertEqual(self.j.reminders, [])

    def test_exit_stops_chain(self):
        results = self.j.handle("exit; what time is it")
        self.assertEqual(len(results), 1)
        self.assertFalse(self.j.running)


class CoreTests(unittest.TestCase):
    def test_coerce(self):
        self.assertIs(coerce("yes", False), True)
        self.assertEqual(coerce("12", 0), 12)
        self.assertEqual(coerce("0.5", 0.1), 0.5)
        self.assertEqual(coerce("a, b", []), ["a", "b"])
        with self.assertRaises(ValueError):
            coerce("maybe", True)

    def test_env_overrides_not_persisted(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "c.json"
            cfg.write_text(json.dumps({"web": {"search_engine": "bing"}}))
            s = Settings.load(cfg, env={"JARVIS_VOICE__OUTPUT_ENABLED": "true", "JARVIS_ASSISTANT_NAME": "Friday",
                                        "JARVIS_NOT__A__KEY": "x", "JARVIS_MONITOR__RAM_HIGH": "abc"})
            self.assertTrue(s.get("voice.output_enabled"))
            self.assertEqual(s.get("assistant_name"), "Friday")
            self.assertEqual(s.get("web.search_engine"), "bing")
            self.assertEqual(s.get("monitor.ram_high"), 90)           # bad value ignored
            self.assertTrue(any("RAM_HIGH" in w for w in s.warnings))
            s.save()
            self.assertEqual(json.loads(cfg.read_text()), {"web": {"search_engine": "bing"}})

    def test_bad_config_file_is_survivable(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "c.json"
            cfg.write_text("{not json")
            s = Settings.load(cfg, env={})
            self.assertEqual(s.get("assistant_name"), "Jarvis")
            self.assertTrue(s.warnings)

    def test_personality_honorific_toggle(self):
        s = Settings({"personality": {"honorific": ""}})
        p = Personality(s, random.Random(0))
        for _ in range(20):
            self.assertNotIn("{h}", p.line("ack"))
            self.assertNotIn(", ", p.line("thanks").rstrip("."))


class CapabilityTests(unittest.TestCase):
    def test_desktop_parsing_and_exec(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "x.desktop"
            f.write_text(textwrap.dedent("""\
                [Desktop Entry]
                Type=Application
                Name=My Tool
                Name[de]=Mein Werkzeug
                Exec=mytool --open %U "quoted arg"
                Keywords=tool;helper;
                [Desktop Action new]
                Name=Ignored
                Exec=ignored
                """))
            e = parse_desktop_file(str(f))
            self.assertEqual((e.name, e.keywords), ("My Tool", ("tool", "helper")))
            self.assertEqual(exec_to_argv(e.exec), ["mytool", "--open", "quoted arg"])
            f.write_text("[Desktop Entry]\nType=Application\nName=Hidden\nExec=x\nNoDisplay=true\n")
            self.assertIsNone(parse_desktop_file(str(f)))

    def test_privilege_detection(self):
        self.assertTrue(is_privileged_exec("pkexec gparted"))
        self.assertTrue(is_privileged_exec('sh -c "sudo nmap -sS"'))
        self.assertTrue(is_privileged_exec("/usr/bin/pkexec foo"))
        self.assertFalse(is_privileged_exec("sudoku"))
        self.assertFalse(is_privileged_exec("gnome-sudoku --x"))

    def test_app_scoring(self):
        self.assertEqual(score_app("code", APPS[4]), 1.0)                 # exec basename
        self.assertGreater(score_app("firefox", APPS[0]), score_app("firefox", APPS[1]))

    def test_nmcli_terse_split(self):
        self.assertEqual(split_terse(r"yes:My\:Net:70:WPA2"), ["yes", "My:Net", "70", "WPA2"])

    def test_monitor_hysteresis(self):
        s = Settings({"monitor": {"battery_high": 80}})
        mon = BackgroundMonitor(system=None, settings=s, on_alert=lambda *a: None)
        keys = lambda snap: [k for k, _, _ in mon.evaluate(snap)]
        self.assertEqual(keys({"battery": (19, False)}), ["battery_low"])
        self.assertEqual(keys({"battery": (18, False)}), [])               # once per episode
        self.assertEqual(keys({"battery": (9, False)}), ["battery_critical"])
        self.assertEqual(keys({"battery": (9, True)}), [])                 # plugged in: reset
        self.assertEqual(keys({"battery": (85, True)}), ["battery_high"])
        self.assertEqual(keys({"battery": (15, False)}), ["battery_low"])  # new episode
        self.assertEqual(keys({"ram": 95}), ["ram_high"])
        self.assertEqual(keys({"ram": 96}), [])
        self.assertEqual(keys({"ram": 50}), [])
        self.assertEqual(keys({"ram": 95}), ["ram_high"])
        for _ in range(2):
            self.assertEqual(keys({"cpu": 99}), [])
        self.assertEqual(keys({"cpu": 99}), ["cpu_high"])                  # sustained only
        self.assertEqual(keys({"disk": [("/", 5.0)]}), ["disk_low:/"])

    def test_file_search_time_budget_and_glob(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(30):
                (Path(d) / f"note{i}.md").write_text("x")
            (Path(d) / "node_modules").mkdir()
            (Path(d) / "node_modules" / "note-x.md").write_text("x")
            s = Settings({"files": {"search_roots": [d], "use_locate": False, "max_results": 5}})
            fs = FileSearch(FakePlatform(), s)
            r = fs.search("note*.md")
            self.assertEqual(len(r["data"]["results"]), 5)
            self.assertFalse(any("node_modules" in p for p in r["data"]["results"]))
            self.assertFalse(fs.search("")["ok"])


class VoiceTests(unittest.TestCase):
    def test_wake_word_rules(self):
        from voice import Voice, clean_for_speech
        v = Voice(Settings({"voice": {"wake_word": "jarvis", "require_wake_word": True}}))
        self.assertEqual(v.extract_command("Jarvis, open firefox", now=0), "open firefox")
        self.assertEqual(v.extract_command("hey jarvis what time is it", now=0), "what time is it")
        self.assertIsNone(v.extract_command("open firefox", now=0))          # no wake word
        self.assertIsNone(v.extract_command("jarvis", now=100))               # arms for 8 s
        self.assertEqual(v.extract_command("check battery", now=104), "check battery")
        self.assertIsNone(v.extract_command("check battery", now=105))        # disarmed again
        v.settings.set("voice.require_wake_word", False)
        self.assertEqual(v.extract_command("open firefox", now=0), "open firefox")
        self.assertEqual(clean_for_speech("**Bold**   `code`"), "Bold code")

    def test_missing_engines_fail_gracefully(self):
        from voice import Voice
        v = Voice(Settings({"voice": {"tts_backend": "definitely-not-installed", "stt_backend": "nope"}}))
        self.assertFalse(v.set_output(True)["ok"])
        self.assertFalse(v.output_enabled)
        self.assertFalse(v.set_input(True)["ok"])
        v.say("ignored while off")                                            # must not raise
        v.shutdown()


if __name__ == "__main__":
    unittest.main()
