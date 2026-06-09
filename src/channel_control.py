import json
import discord

CONFIG_PATH = "config/discord-channels.json"

TEAM_ROLES = ["49ers", "Rams", "Seahawks", "Cardinals"]


# -------------------------#
# Load config              #
# -------------------------#
def load_channels():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def get_mod_channel_id():
    return int(load_channels()["moderator-only"])


# -------------------------#
# Channel parsing          #
# -------------------------#
def parse_channel_from_mention(guild, mention: str):
    """
    Converts:
    - #general
    - <#123456789>
    - 123456789 (raw ID)
    into a Discord channel object
    """

    # Case 1: mention format <#123>
    if mention.startswith("<#") and mention.endswith(">"):
        channel_id = int(mention[2:-1])
        return guild.get_channel(channel_id)

    # Case 2: raw ID
    if mention.isdigit():
        return guild.get_channel(int(mention))

    # Case 3: channel name (#general)
    if mention.startswith("#"):
        name = mention[1:]

        for channel in guild.channels:
            if channel.name.lower() == name.lower():
                return channel

    return None


# -------------------------#
# Channel actions          #
# -------------------------#
async def close_channel(guild, channel, reason=None):
    # lock @everyone
    overwrite = channel.overwrites_for(guild.default_role)
    overwrite.send_messages = False
    await channel.set_permissions(guild.default_role, overwrite=overwrite)

    # lock each team role so they can't override @everyone
    for role_name in TEAM_ROLES:
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            overwrite = channel.overwrites_for(role)
            overwrite.send_messages = False
            await channel.set_permissions(role, overwrite=overwrite)

    embed = discord.Embed(
        title="🔒 Channel Closed",
        description="This channel has been closed by a moderator.\nYou can no longer send messages here.",
        color=discord.Color.red()
    )
    if reason:
        embed.add_field(name="Message", value=reason, inline=False)
    await channel.send(embed=embed)


async def open_channel(guild, channel, reason=None):
    # restore @everyone
    overwrite = channel.overwrites_for(guild.default_role)
    overwrite.send_messages = True
    await channel.set_permissions(guild.default_role, overwrite=overwrite)

    # restore each team role
    for role_name in TEAM_ROLES:
        role = discord.utils.get(guild.roles, name=role_name)
        if role:
            overwrite = channel.overwrites_for(role)
            overwrite.send_messages = True
            await channel.set_permissions(role, overwrite=overwrite)

    embed = discord.Embed(
        title="🔓 Channel Opened",
        description="This channel has been reopened by a moderator.\nYou can now send messages here.",
        color=discord.Color.green()
    )
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)
    await channel.send(embed=embed)