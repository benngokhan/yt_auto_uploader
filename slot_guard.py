#!/usr/bin/env python3
"""Identify publication slots so a delayed cron and its rescue cannot both publish."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import re
import sys

UTC = timezone.utc
SCHEDULES = {
    "30 9 * * *": (9, 30, None, "short"),
    "0 13 * * 5": (13, 0, 4, "long"),
    "30 16 * * *": (16, 30, None, "short"),
}
WATCHDOGS = {
    "05 10 * * *": ("30 9 * * *", "erken"),
    "15 10 * * *": ("30 9 * * *", "tescil"),
    "35 13 * * 5": ("0 13 * * 5", "erken"),
    "45 13 * * 5": ("0 13 * * 5", "tescil"),
    "05 17 * * *": ("30 16 * * *", "erken"),
    "15 17 * * *": ("30 16 * * *", "tescil"),
}
KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$")


def _utc(now):
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("An aware UTC datetime is required")
    return now.astimezone(UTC)


def scheduled_slot(schedule, now=None):
    """Most recent intended occurrence, even when a cron arrives after UTC midnight."""
    if schedule not in SCHEDULES:
        raise ValueError("Unknown scheduled slot")
    current = _utc(now)
    hour, minute, weekday, kind = SCHEDULES[schedule]
    candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if weekday is not None:
        candidate -= timedelta(days=(candidate.weekday() - weekday) % 7)
    if candidate > current + timedelta(minutes=2):
        candidate -= timedelta(days=7 if weekday is not None else 1)
    return candidate.strftime("%Y-%m-%dT%H:%MZ"), kind


def parse_slot(key, now=None, recovery=False):
    if not KEY_RE.fullmatch(key or ""):
        raise ValueError("Invalid slot identifier")
    try:
        stamp = datetime.strptime(key, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
    except ValueError:
        raise ValueError("Invalid slot date") from None
    if (stamp.hour, stamp.minute) in {(9, 30), (16, 30)}:
        kind = "short"
    elif (stamp.hour, stamp.minute) == (13, 0) and stamp.weekday() == 4:
        kind = "long"
    else:
        raise ValueError("Not a configured publication slot")
    if recovery:
        age = _utc(now) - stamp
        if age < -timedelta(minutes=2) or age > timedelta(hours=6):
            raise ValueError("Rescue slot is in the future or too old")
    return stamp, kind


def watchdog_slot(schedule, now=None):
    if schedule not in WATCHDOGS:
        return None
    source_cron, stage = WATCHDOGS[schedule]
    key, kind = scheduled_slot(source_cron, now)
    return key, kind, stage


def slot_completed(log_path, key, now=None):
    """Match exact new SLOT tags; use type/time window only for legacy records."""
    slot, kind = parse_slot(key)
    path = Path(log_path)
    if not path.exists():
        return False
    upper = min(_utc(now), slot + timedelta(hours=2))
    lower = slot - timedelta(minutes=35)
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 4 or parts[0].upper().startswith(("LOCKED_", "MANUAL_SKIP")):
            continue
        is_long = parts[1].lower().startswith("uzun_")
        tags = [part for part in parts[5:] if part.startswith("SLOT=")]
        if tags:
            if f"SLOT={key}" in tags and ((kind == "long") == is_long):
                return True
            continue
        try:
            uploaded = datetime.strptime(parts[3], "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
        except ValueError:
            continue
        if (kind == "long") == is_long and lower <= uploaded <= upper:
            return True
    return False


def slot_claimed(claims_path, key):
    parse_slot(key)
    path = Path(claims_path)
    return path.exists() and key in {
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def reserve_slot(claims_path, log_path, key):
    """Claim before any YouTube request. A claim is never automatically released."""
    parse_slot(key)
    if slot_completed(log_path, key) or slot_claimed(claims_path, key):
        return False
    path = Path(claims_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as claims:
        claims.write(key + "\n")
    return True


def reserve_main():
    key = os.environ.get("SLOT_KEY", "").strip()
    if key:
        parse_slot(key, recovery=True)
        allow = reserve_slot("slot_claims.txt", "uploaded.txt", key)
    else:
        allow = True  # ordinary explicit manual uploads are not assigned a schedule slot
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"allow={'true' if allow else 'false'}\n")
    print(f"SLOT KORUMASI: {key or 'manuel'} -> {'izin' if allow else 'önceden ayrılmış veya yayınlanmış'}")


def main():
    event = os.environ.get("EVENT_NAME", "")
    schedule = os.environ.get("EVENT_SCHEDULE", "").strip()
    rescue = os.environ.get("RECOVERY_SLOT", "").strip()
    key = kind = ""
    if event == "schedule":
        key, kind = scheduled_slot(schedule)
        parse_slot(key, recovery=True)
    elif event == "workflow_dispatch" and rescue:
        _, kind = parse_slot(rescue, recovery=True)
        key = rescue
    elif rescue:
        raise ValueError("Rescue identifier allowed only on workflow_dispatch")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"key={key}\nkind={kind}\n")
    print(f"SLOT: {key or 'manuel/validasyon'} ({kind or '-'})")


if __name__ == "__main__":
    if sys.argv[1:] == ["reserve"]:
        reserve_main()
    elif not sys.argv[1:]:
        main()
    else:
        raise SystemExit("Unknown command")
