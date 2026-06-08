import discord
import os
from countdown import get_channel_id, build_countdown_message

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)


@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

    channel_id = get_channel_id("general")
    channel = client.get_channel(int(channel_id))

    if channel:
        message = build_countdown_message()
        await channel.send(message)


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content.startswith("$hello"):
        await message.channel.send("Hello!")


client.run(DISCORD_TOKEN)