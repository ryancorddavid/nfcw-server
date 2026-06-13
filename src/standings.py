import discord
import aiohttp
import traceback

NFC_WEST_TEAMS = {"Seattle Seahawks", "Los Angeles Rams", "San Francisco 49ers", "Arizona Cardinals"}

CLINCH_LABELS = {
    "conference": "★ ",
    "division":   "✓ ",
    "wildcard":   "x ",
    "eliminated": "e ",
}


# --------------------------------#
# Fetch + parse NFC West          #
# --------------------------------#
async def fetch_nfc_west_standings():
    for season in (None, 2025):
        url = "https://site.api.espn.com/apis/v2/sports/football/nfl/standings"
        if season:
            url += f"?season={season}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json(content_type=None)

        teams = []

        for conference in data.get("children", []):
            if conference.get("name") != "National Football Conference":
                continue

            for entry in conference.get("standings", {}).get("entries", []):
                team_name = entry.get("team", {}).get("displayName", "?")

                if team_name not in NFC_WEST_TEAMS:
                    continue

                stats = {s["name"]: s.get("value", s.get("displayValue", 0)) for s in entry.get("stats", [])}

                teams.append({
                    "name": team_name,
                    "wins": int(stats.get("wins", 0)),
                    "losses": int(stats.get("losses", 0)),
                    "ties": int(stats.get("ties", 0)),
                    "pct": float(stats.get("winPercent", 0.0)),
                    "clinched": stats.get("clincher", ""),
                })

        teams.sort(key=lambda t: t["wins"], reverse=True)

        if teams:
            return teams, season == 2025

    return [], True


# --------------------------------#
# Build embed                     #
# --------------------------------#
def build_standings_embed(teams, fallback=False):
    title = "🏈 NFC West Standings"
    if fallback:
        title += " — 2025 Final"

    embed = discord.Embed(
        title=title,
        color=discord.Color.dark_gold()
    )

    for i, team in enumerate(teams, start=1):
        prefix = CLINCH_LABELS.get(team["clinched"], "")
        name = f"{i}. {prefix}{team['name']}"
        record = f"**{team['wins']}W — {team['losses']}L — {team['ties']}T**\nPCT: {team['pct']:.3f}"
        embed.add_field(name=name, value=record, inline=False)

    footer = "NFC West • 2025 Final Standings" if fallback else "NFC West • Live Standings"
    embed.set_footer(text=footer)

    return embed


# --------------------------------#
# Command handler                 #
# --------------------------------#
async def handle_standings(message):
    try:
        teams, fallback = await fetch_nfc_west_standings()
        embed = build_standings_embed(teams, fallback=fallback)
    except Exception as e:
        print(f"[ERROR] Failed to fetch standings:")
        traceback.print_exc()
        embed = discord.Embed(
            title="⚠️ Standings Unavailable",
            description="Could not fetch NFC West standings. Try again later.",
            color=discord.Color.orange()
        )

    await message.channel.send(embed=embed)