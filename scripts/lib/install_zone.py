"""The install's time zone for Python helpers (ISSUE1895, #1895).

src/config.ts resolves ONE zone for the whole install (APP_TZ): SCHEDULER_TZ
from store/config-overrides.json over .env, and the host zone when it is unset
or not a real zone. `scripts/lib/install-tz.sh` is the shell side of the same
rule; this is the Python side, so a script does not have to carry its own copy.

The literal that used to stand in these scripts named one single city, which is
right for exactly one install and silently an hour or more off on every other.
(The zone name itself is not spelled out here: a source pin greps for it.)

Usage:

    import os, sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'lib'))
    from install_zone import local_tz, local_zone_name

    TZ = local_tz()            # a tzinfo, DST rules included
    print(local_zone_name())   # the zone's NAME, for a message or a cron file
"""

import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

# scripts/lib/install_zone.py -> the repo root is two levels up.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pinned_zone(repo_root: str = REPO_ROOT) -> str:
    """The zone the operator pinned, or '' when none is readable.

    MARVEEN_TZ wins when set (one script run in another zone, deliberately),
    then SCHEDULER_TZ from store/config-overrides.json, then from .env. The
    precedence is the same as src/config.ts and usage-collect.py.
    """
    explicit = (os.environ.get("MARVEEN_TZ") or "").strip()
    if explicit:
        return explicit
    try:
        with open(os.path.join(repo_root, "store", "config-overrides.json"), encoding="utf-8") as f:
            ov = json.load(f)
        if isinstance(ov, dict) and ov.get("SCHEDULER_TZ"):
            return str(ov["SCHEDULER_TZ"]).strip()
    except Exception:
        pass
    try:
        with open(os.path.join(repo_root, ".env"), encoding="utf-8", errors="replace") as f:
            # Parity with src/env-parse.ts: the LAST occurrence wins, and one
            # pair of surrounding quotes is removed.
            value = ""
            for line in f:
                line = line.strip()
                if line.startswith("SCHEDULER_TZ="):
                    value = line.split("=", 1)[1].strip()
                    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                        value = value[1:-1]
            return value
    except Exception:
        return ""


def host_zone_name() -> str:
    """The host's zone by NAME, or '' when it cannot be read.

    A fixed offset (what datetime.now().astimezone() gives) would render a time
    on the other side of a DST switch an hour off, so the NAME matters.
    """
    tz = (os.environ.get("TZ") or "").lstrip(":").strip()
    if tz and "/" in tz:
        return tz
    try:
        target = os.path.realpath("/etc/localtime")
        if "/zoneinfo/" in target:
            return target.split("/zoneinfo/", 1)[1]
    except Exception:
        pass
    return ""


def local_zone_name(repo_root: str = REPO_ROOT) -> str:
    """The install's zone name, pinned first, then the host's; '' if neither."""
    for zone in (pinned_zone(repo_root), host_zone_name()):
        if zone:
            try:
                ZoneInfo(zone)
            except Exception:
                continue  # a misspelled zone: try the next candidate, as config.ts does
            return zone
    return ""


def local_tz(repo_root: str = REPO_ROOT):
    """The install's zone as a tzinfo. Falls back to the process's own zone."""
    name = local_zone_name(repo_root)
    if name:
        return ZoneInfo(name)
    return datetime.now().astimezone().tzinfo
