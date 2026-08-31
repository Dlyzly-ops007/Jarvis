import re
command_rules = []

def register(name, match_type, pattern, priority=100):
    """Decorator: @register("status", "exact", ("status", "/status"))"""
    def decorator(handler):
        command_rules.append({
            "name": name,
            "match_type": match_type,
            "pattern": pattern,
            "handler": handler,
            "priority": priority,
        })
        command_rules.sort(key=lambda rule: rule["priority"])
        return handler
    return decorator


def rule_matches(rule, cmd):
    match_type = rule["match_type"]
    pattern = rule["pattern"]

    if match_type == "exact":
        patterns = pattern if isinstance(pattern, tuple) else (pattern,)
        return cmd in patterns

    if match_type == "prefix":
        return cmd.startswith(pattern)  # str.startswith takes tuples natively

    if match_type == "contains":
        patterns = pattern if isinstance(pattern, tuple) else (pattern,)
        return any(p in cmd for p in patterns)

    if match_type == "regex":
        return re.match(pattern, cmd) is not None

    if match_type == "custom":
        return pattern(cmd)  #bool predicate

    raise ValueError(f"Unknown match type: {match_type}")


def dispatch(cmd):
    """Runs the first matching handler. Returns True if something matched."""
    cmd = (cmd or "").lower().strip()
    for rule in command_rules:
        if rule_matches(rule, cmd):
            rule["handler"](cmd)
            return True
    return False


def which_rule(cmd):
    """Debug helper: which rule would fire, without running it."""
    cmd = (cmd or "").lower().strip()
    for rule in command_rules:
        if rule_matches(rule, cmd):
            return rule["name"]
    return None


@register("stop", "regex", r'.*\bstop\b', priority=0)
def handle_stop(cmd):
    print("command mode off")


@register("status", "exact", ("status", "/status"), priority=10)
def handle_status(cmd):
    print("status: TODO")


@register("open", "regex", r'^(open|please open|can you open|could you open)\b', priority=20)
def handle_open(cmd):
    target = re.sub(r'^(open|please open|can you open|could you open)\b', '', cmd).strip()
    print(f"open: {target}")


@register("scan_for", "contains", "scan for", priority=20)
def handle_scan_for(cmd):
    target = cmd.split("scan for")[-1].strip()
    print(f"scan_for: {target}")


@register("launch", "prefix", "launch", priority=20)
def handle_launch(cmd):
    target = cmd.replace("launch", "", 1).strip()
    print(f"launch -> open {target}")


# status / quick info

@register("screenshot", "exact", ("screenshot", "/screenshot"), priority=11)
def handle_screenshot(cmd):
    print("screenshot: taken")


@register("summary", "exact", ("summary", "/summary"), priority=12)
def handle_summary(cmd):
    print("summary: TODO")


@register("clearreminders", "exact", ("clearreminders", "/clearreminders"), priority=13)
def handle_clearreminders(cmd):
    print("reminders cleared")


#apps control 

@register("addgame", "prefix", ("addgame", "/addgame"), priority=21)
def handle_addgame(cmd):
    g = cmd.replace("addgame", "").replace("/addgame", "").strip()
    if g:
        print(f"addgame: {g}")


@register("cursor", "prefix", ("cursor", "/cursor"), priority=22)
def handle_cursor(cmd):
    sub = cmd.replace("cursor", "").replace("/cursor", "").strip()
    print(f"cursor scheme: {sub}")


# browser / search 

@register("smart_search", "prefix", "smart search", priority=30)
def handle_smart_search(cmd):
    q = cmd.replace("smart search", "", 1).strip()
    print(f"smart search: {q}")


@register("go_to", "prefix", "go to ", priority=31)
def handle_go_to(cmd):
    url = cmd.replace("go to ", "", 1).strip()
    print(f"navigate: {url}")


@register("click", "prefix", "click ", priority=32)
def handle_click(cmd):
    target = cmd.replace("click ", "", 1).strip()
    print(f"click: {target}")


@register("browse", "contains", "browse", priority=33)
def handle_browse(cmd):
    q = cmd.split("browse")[-1].strip()
    print(f"browse: {q}")


# window / system controls 

@register("snap", "contains", "snap", priority=40)
def handle_snap(cmd):
    print("snap: win+shift+s")


@register("close_window", "contains", "close window", priority=41)
def handle_close_window(cmd):
    print("close window: alt+backspace")


@register("change_window", "contains", "change window", priority=42)
def handle_change_window(cmd):
    print("change window: alt+tab")


@register("enter", "contains", "enter", priority=43)
def handle_enter(cmd):
    print("key: enter")


@register("lock", "regex", r'.*\block\b', priority=44)
def handle_lock(cmd):
    print("lock screen")


@register("battery", "contains", ("battery status", "battery"), priority=45)
def handle_battery(cmd):
    print("battery: TODO")


@register("mute_volume", "contains", "mute", priority=46)
def handle_mute_volume(cmd):
    print("volume: muted")


@register("media_next", "custom",
          lambda cmd: any(p in cmd for p in ("next track", "skip song", "skip track", "next song")),
          priority=47)
def handle_media_next(cmd):
    print("media: next track")


@register("media_prev", "custom",
          lambda cmd: any(p in cmd for p in ("previous track", "last track", "rewind", "go back a track")),
          priority=48)
def handle_media_prev(cmd):
    print("media: previous track")


@register("media_play_pause", "custom",
          lambda cmd: any(p in cmd for p in (
              "pause the video", "pause the music", "pause that",
              "resume the video", "resume playback", "play the video",
              "unpause", "pause music", "resume music")),
          priority=49)
def handle_media_play_pause(cmd):
    print("media: play/pause")


@register("wifi_off", "contains", ("wifi off", "turn off wifi"), priority=50)
def handle_wifi_off(cmd):
    print("wifi: off")


@register("wifi_on", "contains", ("wifi on", "turn on wifi"), priority=51)
def handle_wifi_on(cmd):
    print("wifi: on")


@register("wifi_toggle", "contains", "toggle wifi", priority=52)
def handle_wifi_toggle(cmd):
    print("wifi: toggled")


@register("overlay", "exact", ("overlay", "/overlay", "screen overlay"), priority=53)
def handle_overlay(cmd):
    print("opening screen overlay")


@register("bluetooth_off", "contains", ("bluetooth off", "turn off bluetooth"), priority=54)
def handle_bluetooth_off(cmd):
    print("bluetooth: off")


@register("bluetooth_on", "contains", ("bluetooth on", "turn on bluetooth"), priority=55)
def handle_bluetooth_on(cmd):
    print("bluetooth: on")


@register("bluetooth_toggle", "contains", "toggle bluetooth", priority=56)
def handle_bluetooth_toggle(cmd):
    print("bluetooth: toggled")


@register("time", "custom",
          lambda cmd: re.search(r'\btime\b', cmd) is not None or "date and time" in cmd,
          priority=57)
def handle_time(cmd):
    print("time: TODO")


@register("system_status", "contains", ("system status", "check cpu and ram"), priority=58)
def handle_system_status(cmd):
    print("system status: TODO")


@register("spam_key", "contains", "spam", priority=59)
def handle_spam_key(cmd):
    print("spam key until esc")


@register("flip_coin", "contains", "flip a coin", priority=60)
def handle_flip_coin(cmd):
    print("coin flip: TODO")


@register("sort_folder", "contains", ("sort folder", "short folder"), priority=61)
def handle_sort_folder(cmd):
    print("sort folder")


@register("eye_track", "contains", ("eye track", "i track", "eye tracking"), priority=62)
def handle_eye_track(cmd):
    print("eye tracking: TODO")


@register("solve", "contains", "solve", priority=63)
def handle_solve(cmd):
    expr = cmd.split("solve")[-1].strip()
    print(f"solve: {expr}")


@register("color_scheme", "contains", ("color", "colour"), priority=64)
def handle_color_scheme(cmd):
    print("key: alt+q")


@register("find", "regex", r'.*\bfind\b', priority=65)
def handle_find(cmd):
    q = cmd.split("find")[-1].strip()
    print(f"find: {q}")


@register("code_window", "regex", r'.*\bcode\b', priority=66)
def handle_code_window(cmd):
    print("open input window")


@register("clean", "regex", r'.*\bclean\b', priority=67)
def handle_clean(cmd):
    print("cleanup: TODO")


@register("writee", "contains", "writee", priority=68)
def handle_writee(cmd):
    print("write: TODO")


# work profiles

@register("pause_work", "custom",
          lambda cmd: "pause work" in cmd or cmd.strip() == "pw", priority=70)
def handle_pause_work(cmd):
    print("work: paused")


@register("continue_work", "custom",
          lambda cmd: "continue work" in cmd or cmd.strip() == "cw", priority=71)
def handle_continue_work(cmd):
    print("work: resumed")


@register("save_work", "custom",
          lambda cmd: "save work" in cmd or cmd.strip() == "sw", priority=72)
def handle_save_work(cmd):
    print("work: saved")


@register("resume_profile", "custom",
          lambda cmd: "resume" in cmd and "work" not in cmd, priority=73)
def handle_resume_profile(cmd):
    name = cmd.split("resume")[-1].strip()
    print(f"resume profile: {name}")


@register("overwrite", "contains", "overwrite", priority=74)
def handle_overwrite(cmd):
    print("overwrite: pending profile")


# reminders / checklist 

@register("my_reminders", "contains", ("my reminders", "remind me again"), priority=80)
def handle_my_reminders(cmd):
    print("reminders: list")


@register("remind_me", "custom",
          lambda cmd: "remind me" in cmd or "remember" in cmd, priority=81)
def handle_remind_me(cmd):
    text = cmd.replace("remind me", "").replace("remember", "").strip()
    print(f"remind me: {text}")


@register("clear_checklist", "contains", "clear checklist", priority=82)
def handle_clear_checklist(cmd):
    print("checklist: confirm to clear")


@register("delete_profile", "contains", "delete profile", priority=83)
def handle_delete_profile(cmd):
    name = cmd.split("delete profile")[-1].strip()
    print(f"delete profile: {name}")


@register("confirm", "contains", "confirm", priority=84)
def handle_confirm(cmd):
    print("confirm: TODO (needs pending-action state)")


#  game mode

@register("game_mode", "contains", "game mode", priority=90)
def handle_game_mode(cmd):
    print("game mode: on")


@register("game_restore_yes", "custom", lambda cmd: "yes" in cmd, priority=91)
def handle_game_restore_yes(cmd):
    print("game restore: yes (needs pending-restore state)")


@register("game_restore_no", "custom", lambda cmd: "no" in cmd, priority=92)
def handle_game_restore_no(cmd):
    print("game restore: no (needs pending-restore state)")


# screen / image 

@register("lms", "contains", "lms", priority=100)
def handle_lms(cmd):
    print("lms: TODO")


@register("screen_tags", "contains", ("what's on my screen", "whats on my screen"), priority=101)
def handle_screen_tags(cmd):
    print("screen tags: TODO")


@register("screen_text", "contains", ("get text from screen", "read screen"), priority=102)
def handle_screen_text(cmd):
    print("screen text: TODO")


@register("upload_image", "contains", "upload image", priority=103)
def handle_upload_image(cmd):
    print("upload image: TODO")


@register("analyse_image", "contains", ("analyse image", "get text from image"), priority=104)
def handle_analyse_image(cmd):
    mode = "text" if "text" in cmd else "tags"
    print(f"analyse image: {mode}")


# info / small talk 

@register("weather", "contains", "weather", priority=110)
def handle_weather(cmd):
    print("weather: TODO")


@register("news", "contains", "news", priority=111)
def handle_news(cmd):
    print("news: TODO")


@register("convert", "contains", "convert", priority=112)
def handle_convert(cmd):
    q = cmd.split("convert")[-1].strip()
    print(f"convert: {q}")


@register("translate", "contains", "translate", priority=113)
def handle_translate(cmd):
    print("translate: TODO")


@register("brief_me", "contains", "brief me", priority=114)
def handle_brief_me(cmd):
    print("brief me: TODO")


@register("current_state", "contains", ("what am i doing", "current state"), priority=115)
def handle_current_state(cmd):
    print("current state: TODO")


@register("activity_summary", "contains", ("activity summary", "what have i been doing"), priority=116)
def handle_activity_summary(cmd):
    print("activity summary: TODO")


@register("birthday", "contains", ("happy birthday", "birthday jarvis"), priority=117)
def handle_birthday(cmd):
    print("birthday: TODO")


@register("thanks", "contains", "thank", priority=118)
def handle_thanks(cmd):
    print("acknowledged")


@register("how_old", "contains", "how old are you", priority=119)
def handle_how_old(cmd):
    print("age: TODO")


@register("talk_ask_chat", "contains", ("talk", "ask", "chat"), priority=120)
def handle_talk_ask_chat(cmd):
    q = cmd.replace("talk", "").replace("ask", "").replace("chat", "").strip()
    print(f"chat: {q}")


# spotify 

@register("play_usual", "contains", ("play the usual", "usual playlist"), priority=130)
def handle_play_usual(cmd):
    print("spotify: play usual")


@register("play_query", "custom",
          lambda cmd: "play" in cmd and any(w in cmd for w in ("song", "track", "play")),
          priority=131)
def handle_play_query(cmd):
    q = cmd.replace("play", "").strip()
    print(f"spotify: play {q}" if q else "spotify: resume")


@register("pause_music", "contains", ("pause music", "pause spotify"), priority=132)
def handle_pause_music(cmd):
    print("spotify: pause")


@register("resume_music", "contains", ("resume music", "resume spotify"), priority=133)
def handle_resume_music(cmd):
    print("spotify: resume")


@register("next_song", "contains", ("next song", "next track", "skip"), priority=134)
def handle_next_song(cmd):
    print("spotify: next")


@register("prev_song", "contains", ("previous song", "prev song"), priority=135)
def handle_prev_song(cmd):
    print("spotify: previous")


@register("shuffle", "contains", "shuffle", priority=136)
def handle_shuffle(cmd):
    print("spotify: shuffle")


@register("volume_up", "contains", "volume up", priority=137)
def handle_volume_up(cmd):
    print("spotify: volume up")


@register("volume_down", "contains", "volume down", priority=138)
def handle_volume_down(cmd):
    print("spotify: volume down")


@register("now_playing", "contains", ("what's playing", "whats playing", "current song"), priority=139)
def handle_now_playing(cmd):
    print("spotify: now playing")


# clipboard / documents 

@register("clipboard", "contains",
          ("clipboard", "what did i copy", "search clipboard", "summarise clipboard",
           "fix this", "explain clipboard"),
          priority=150)
def handle_clipboard(cmd):
    print("clipboard: TODO")


@register("upload_document", "contains", ("upload document", "upload timetable"), priority=151)
def handle_upload_document(cmd):
    print("upload document: TODO")


#automations 

@register("automations_status", "contains", ("my automations", "automation status"), priority=160)
def handle_automations_status(cmd):
    print("automations: TODO")


@register("forget_automation", "prefix", "forget automation", priority=161)
def handle_forget_automation(cmd):
    keyword = cmd.split("forget automation", 1)[-1].strip()
    print(f"forget automation: {keyword}")


# research / corrector 

@register("deep_research", "custom",
          lambda cmd: any(t in cmd for t in
                           ("deep search", "deep research", "research this",
                            "look into this properly", "investigate")),
          priority=170)
def handle_deep_research(cmd):
    print("deep research: TODO")


@register("corrector_on", "custom",
          lambda cmd: any(t in cmd for t in
                           ("typing character on", "start corrector", "typing corrector on", "autocorrect on")),
          priority=171)
def handle_corrector_on(cmd):
    print("corrector: on")


@register("corrector_off", "custom",
          lambda cmd: any(t in cmd for t in
                           ("typing character of", "stop corrector", "typing corrector off", "autocorrect off")),
          priority=172)
def handle_corrector_off(cmd):
    print("corrector: off")


# memory 

@register("recall_memory", "regex", r"what do you remember about (.+)", priority=180)
def handle_recall_memory(cmd):
    topic = re.search(r"what do you remember about (.+)", cmd).group(1).strip()
    print(f"recall: {topic}")


@register("remember_that", "regex", r"remember that (.+)", priority=181)
def handle_remember_that(cmd):
    fact = re.match(r"remember that (.+)", cmd).group(1).strip()
    print(f"remember: {fact}")


@register("forget_fact", "regex", r"forget (.+)", priority=182)
def handle_forget_fact(cmd):
    q = re.match(r"forget (.+)", cmd).group(1).strip()
    print(f"forget: {q}")


#  exams / quiz / todos 

@register("add_exam", "custom",
          lambda cmd: any(t in cmd for t in ("add exam", "add an exam", "new exam")),
          priority=190)
def handle_add_exam(cmd):
    print("add exam: open window")


@register("quiz_me", "regex", r"(quiz me on|test me on|viva prep)\s+(.+)", priority=191)
def handle_quiz_me(cmd):
    topic = re.search(r"(quiz me on|test me on|viva prep)\s+(.+)", cmd).group(2).strip()
    print(f"quiz me: {topic}")


@register("jarvis_todos", "regex", r"(what are my jarvis todos|jarvis todo list)", priority=192)
def handle_jarvis_todos(cmd):
    print("jarvis todos: TODO")


# fallback: nothing matched, hand off to the LLM/agent path 

@register("fallback", "custom", lambda cmd: True, priority=9999)
def handle_fallback(cmd):
    print(f"fallback -> agent: {cmd}")
