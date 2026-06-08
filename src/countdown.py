import json
from datetime import datetime, timezone
from pathlib import Path

NFL_KICKOFF = datetime(2026, 9, 10, tzinfo=timezone.utc)

CONFIG_PATH = Path("discord-channels.json")

with open(CONFIG_PATH, "r") as f:
    CHANNELS = json.load(f)


def days_until_kickoff():
    now = datetime.now(timezone.utc)
    delta = NFL_KICKOFF - now
    return max(delta.days, 0)


def get_channel_id(name: str):
    return CHANNELS.get(name)


def build_countdown_message():
    days = days_until_kickoff()

    if days == 0:
        return "🏈 NFL IS TODAY! LET'S GO!"
    return f"🏈 NFL Kickoff is in **{days} days!**"