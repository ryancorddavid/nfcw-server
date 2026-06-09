import discord
import os
import asyncio
import re

from scheduler import nfl_scheduler
from countdown import get_channel_id, build_countdown_message
from channel_control import (
    get_mod_channel_id,
    parse_channel_from_mention,
    open_channel,
    close_channel
)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


# -----------------#
# Discord events   #
# -----------------#
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

    # ensure scheduler only starts once
    if not hasattr(client, "nfl_task_started"):
        client.nfl_task_started = True
        asyncio.create_task(nfl_scheduler(client))


@client.event
async def on_message(message):
    if message.author == client.user:
        return

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