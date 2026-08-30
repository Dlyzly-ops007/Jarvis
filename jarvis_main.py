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
        return cmd.startswith(pattern)

    if match_type == "contains":
        return pattern in cmd

    if match_type == "regex":
        return re.match(pattern, cmd) is not None

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
