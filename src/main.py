import discord
import os
import asyncio
import json
import re
from datetime import datetime, timedelta
import pytz

from countdown import get_channel_id, build_countdown_message
from channel_control import (
    get_mod_channel_id,
    parse_channel_from_mention,
    open_channel,
    close_channel
)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True  # required to read message.content
client = discord.Client(intents=intents)

PT = pytz.timezone("America/Los_Angeles")

STATE_FILE = "nfl_post_state.json"


# --------------------------------------#
# State handling (prevents duplicates)  #
# --------------------------------------#
def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


# ------------------------------------#
# Next scheduled run (Monday 9AM PT)  #
# ------------------------------------#
def next_run_time():
    now = datetime.now(PT)

    # days until next Monday
    days_ahead = (7 - now.weekday()) % 7

    # if it's Monday but past 9AM, push to next week
    if days_ahead == 0 and now.hour >= 9:
        days_ahead = 7

    next_monday = (now + timedelta(days=days_ahead)).replace(
        hour=9,
        minute=0,
        second=0,
        microsecond=0
    )

    return next_monday


# --------------------#
# Scheduler loop      #
# --------------------#
async def nfl_scheduler():
    await client.wait_until_ready()

    while not client.is_closed():
        state = load_state()
        now = datetime.now(PT)

        run_time = next_run_time()
        sleep_seconds = (run_time - now).total_seconds()

        print(f"[Scheduler] Next NFL post: {run_time}")

        # sleep until scheduled time
        await asyncio.sleep(max(sleep_seconds, 0))

        # reload state after waking
        state = load_state()

        # prevent duplicate run on restart or crash recovery
        if state.get("last_run") == run_time.isoformat():
            continue

        channel = client.get_channel(get_channel_id("general"))

        if channel:
            message = build_countdown_message()
            await channel.send(message)

            # mark as completed
            state["last_run"] = run_time.isoformat()
            save_state(state)


# -----------------#
# Discord events   #
# -----------------#
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

    # ensure scheduler only starts once
    if not hasattr(client, "nfl_task_started"):
        client.nfl_task_started = True
        asyncio.create_task(nfl_scheduler())


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    print(f"[MSG] #{message.channel.name}: {message.content}")

    # allow hello anywhere
    if message.content.startswith("$hello"):
        await message.channel.send("Hello!")
        return

    # load mod channel ID with error handling
    try:
        mod_channel_id = get_mod_channel_id()
    except Exception as e:
        print(f"[ERROR] Could not load mod channel ID: {e}")
        return

    # enforce mod channel ONLY for admin commands
    if message.channel.id != mod_channel_id:
        return

    content = message.content.split()

    if len(content) < 2:
        await message.channel.send("Usage: !close #channel or !open #channel")
        return

    command = content[0].lower()
    target = content[1]

    # extract optional quoted reason e.g. "49ers lost 28-3"
    reason_match = re.search(r'"(.+)"', message.content)
    reason = reason_match.group(1) if reason_match else None

    channel = parse_channel_from_mention(message.guild, target)

    if not channel:
        await message.channel.send("❌ Channel not found.")
        return

    if command == "!close":
        await close_channel(message.guild, channel, reason)
        await message.channel.send(f"🔒 Closed {channel.name}")

    elif command == "!open":
        await open_channel(message.guild, channel, reason)
        await message.channel.send(f"🔓 Opened {channel.name}")


# --------------#
# Start bot     #
# --------------#
client.run(DISCORD_TOKEN)