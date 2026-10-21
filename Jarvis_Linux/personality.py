"""Remarks and greetings. Concise, mildly dry, competent — and sparing with "sir".

`{h}` in a line becomes ", <honorific>" about half the time (or never if the
honorific is empty). Other {placeholders} are filled from keyword arguments.
"""
from __future__ import annotations

import random
from datetime import datetime

REMARKS: dict[str, list[str]] = {
    "startup": ["Online and ready{h}.", "Systems up. What do you need?", "Ready when you are{h}."],
    "ack": ["On it{h}.", "Right away.", "Done.", "Consider it done."],
    "open": ["Opening {name}.", "Launching {name}{h}.", "{name}, coming up."],
    "not_found": ["Nothing matched{h}.", "Came up empty.", "I looked. It isn't there."],
    "app_not_found": ["I can't find an installed app called '{name}'.",
                      "No installed app matches '{name}'{h}."],
    "unknown": ["I didn't catch a command in that{h}.", "Not something I know how to do yet.",
                "That one's beyond me for now. Try 'help'."],
    "error": ["Something went wrong on my end{h}. Details are in the log.",
              "That failed. The log has the details."],
    "refuse_privileged": ["I don't run anything as root. If you're sure, do that one yourself.",
                          "Privileged commands are off-limits for me{h}. Deliberately."],
    "refuse_power": ["I don't do power operations{h}. Use the system menu — and say 'exit' to close me.",
                     "Shutting down the machine isn't my call. Say 'exit' if you just want me gone."],
    "unported": ["{feature} hasn't made it to the Linux build yet.",
                 "{feature} is still Windows-only. On the list."],
    "thanks": ["Anytime{h}.", "Of course.", "That's what I'm here for."],
    "how_are_you": ["All systems nominal{h}.", "Running smoothly. Can't complain — well, I could.",
                    "Fine, thanks. Better than your tab count, probably."],
    "who": ["I'm {name}. Lightweight Linux edition — fewer features, fewer crashes."],
    "farewell": ["Signing off{h}.", "Goodbye. Try not to break anything.", "Shutting down. Call if you need me."],
    "late_night": ["It's late{h}.", "Still at it at this hour?"],
    "early": ["You're up early{h}."],
    "busy": ["The CPU is working hard{h}.", "Something's keeping the CPU busy."],
    "suggest": ["Did you mean '{cmd}'? Say yes to run it."],
    "cancel": ["Fine, leaving it.", "Never mind then."],
}


class Personality:
    def __init__(self, settings, rng: random.Random | None = None):
        self.settings = settings
        self.rng = rng or random.Random()

    def _fill(self, line: str, fmt: dict) -> str:
        hon = str(self.settings.get("personality.honorific") or "").strip()
        h = f", {hon}" if hon and self.rng.random() < 0.5 else ""
        try:
            return line.format(h=h, **fmt)
        except (KeyError, IndexError, ValueError):
            return line.replace("{h}", h)

    def line(self, key: str, **fmt) -> str:
        """Always returns a line (falls back to 'unknown')."""
        choices = REMARKS.get(key) or REMARKS["unknown"]
        return self._fill(self.rng.choice(choices), fmt)

    def remark(self, key: str, **fmt) -> str:
        """Optional flavour: returns '' unless the remark_chance roll succeeds."""
        chance = float(self.settings.get("personality.remark_chance") or 0)
        if key in REMARKS and self.rng.random() < chance:
            return self._fill(self.rng.choice(REMARKS[key]), fmt)
        return ""

    def greeting(self, now: datetime | None = None) -> str:
        now = now or datetime.now()
        hour, wd = now.hour, now.weekday()
        name = str(self.settings.get("user_name") or "").strip()
        who = f", {name}" if name else "{h}"
        if hour < 5:
            options = [f"Quite late{who}. Good evening.", f"Still up{who}?"]
        elif hour < 7:
            options = [f"Good morning{who}, you're up early.", "Early start today. Good morning."]
        elif hour < 12:
            if wd == 0:
                options = [f"New week{who}. Good morning.", "Monday morning. Let's make it count."]
            elif wd >= 5:
                options = [f"Weekend morning{who}.", "Morning. Enjoy the weekend."]
            else:
                options = [f"Good morning{who}.", "Morning. What are we doing today?"]
        elif hour < 17:
            options = [f"Good afternoon{who}.", "Afternoon. What do you need?"]
        elif hour < 21:
            options = ([f"Friday evening{who}.", "End of the week. Good evening."] if wd == 4
                       else [f"Good evening{who}.", "Evening. Long day?"])
        else:
            options = [f"Evening{who}. It's getting late.", "Late night again?"]
        return self._fill(self.rng.choice(options), {})
