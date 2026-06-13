import discord
import aiohttp
import asyncio
from datetime import datetime, timezone, timedelta
import pytz

from server.pickem_db import (
    get_or_create_week,
    lock_week,
    is_week_locked,
    mark_results_posted,
    save_games,
    get_games,
    set_game_score,
    save_pick,
    get_user_picks,
    calculate_and_save_scores,
    get_weekly_leaderboard,
    get_overall_leaderboard,
)
from countdown import get_channel_id

PT = pytz.timezone("America/Los_Angeles")
PICKEM_CHANNEL = "pick_ems"

RESULTS_RETRY_INTERVAL = 30 * 60  # 30 minutes


# --------------------------------#
# ESPN Schedule Fetch             #
# --------------------------------#
async def fetch_nfl_schedule(week_number: int) -> list:
    url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?seasontype=2&week={week_number}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json(content_type=None)

    games = []

    for event in data.get("events", []):
        competition = event["competitions"][0]
        competitors = competition["competitors"]

        home = next(c for c in competitors if c["homeAway"] == "home")
        away = next(c for c in competitors if c["homeAway"] == "away")

        kickoff_str = competition["date"]
        kickoff = datetime.strptime(kickoff_str, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)

        # MNF = Monday kickoff
        kickoff_pt = kickoff.astimezone(PT)
        is_mnf = kickoff_pt.weekday() == 0  # Monday

        games.append({
            "home_team": home["team"]["displayName"],
            "away_team": away["team"]["displayName"],
            "kickoff_time": kickoff,
            "is_mnf": is_mnf,
        })

    games.sort(key=lambda g: g["kickoff_time"])
    return games


# --------------------------------#
# Fetch and save schedule         #
# --------------------------------#
async def fetch_and_save_schedule(week_number: int) -> list:
    games = await fetch_nfl_schedule(week_number)
    if games:
        save_games(week_number, games)
        print(f"[PickEm] Saved {len(games)} games for week {week_number}")
    return games


# --------------------------------#
# Auto-lock at first kickoff      #
# --------------------------------#
async def schedule_auto_lock(client, week_number: int):
    games = get_games(week_number)

    if not games:
        return

    first_kickoff = min(g["kickoff_time"] for g in games)

    if isinstance(first_kickoff, datetime) and first_kickoff.tzinfo is None:
        first_kickoff = first_kickoff.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    wait_seconds = (first_kickoff - now).total_seconds()

    if wait_seconds > 0:
        print(f"[PickEm] Auto-lock scheduled in {wait_seconds:.0f}s for week {week_number}")
        await asyncio.sleep(wait_seconds)

    if not is_week_locked(week_number):
        lock_week(week_number)
        print(f"[PickEm] Week {week_number} locked at kickoff")

        channel = client.get_channel(get_channel_id(PICKEM_CHANNEL))
        if channel:
            embed = discord.Embed(
                title=f"🔒 Week {week_number} Picks Locked",
                description="Picks are now locked. Good luck everyone!",
                color=discord.Color.red()
            )
            await channel.send(embed=embed)


# --------------------------------#
# Build matchup buttons view      #
# --------------------------------#
def build_picks_view(games: list, week_number: int, week_id: int):
    view = discord.ui.View(timeout=None)

    for game in games:
        view.add_item(PickButton(
            game_id=game["id"],
            team=game["home_team"],
            week_number=week_number,
            week_id=week_id,
            is_mnf=game["is_mnf"]
        ))
        view.add_item(PickButton(
            game_id=game["id"],
            team=game["away_team"],
            week_number=week_number,
            week_id=week_id,
            is_mnf=game["is_mnf"]
        ))

    return view


# --------------------------------#
# Pick Button                     #
# --------------------------------#
class PickButton(discord.ui.Button):
    def __init__(self, game_id: int, team: str, week_number: int, week_id: int, is_mnf: bool):
        super().__init__(
            label=team,
            style=discord.ButtonStyle.primary,
            custom_id=f"pick_{game_id}_{team}"
        )
        self.game_id = game_id
        self.team = team
        self.week_number = week_number
        self.week_id = week_id
        self.is_mnf = is_mnf

    async def callback(self, interaction: discord.Interaction):
        if is_week_locked(self.week_number):
            await interaction.response.send_message(
                "🔒 Picks are locked for this week.", ephemeral=True
            )
            return

        if self.is_mnf:
            await interaction.response.send_modal(
                TiebreakerModal(
                    game_id=self.game_id,
                    team=self.team,
                    week_number=self.week_number,
                    week_id=self.week_id
                )
            )
        else:
            save_pick(
                user_id=str(interaction.user.id),
                username=str(interaction.user.display_name),
                game_id=self.game_id,
                week_id=self.week_id,
                picked_team=self.team
            )
            await interaction.response.send_message(
                f"✅ You picked **{self.team}**!", ephemeral=True
            )


# --------------------------------#
# Tiebreaker Modal (MNF)          #
# --------------------------------#
class TiebreakerModal(discord.ui.Modal, title="Monday Night Football Tiebreaker"):
    tiebreaker = discord.ui.TextInput(
        label="Predict the total combined score",
        placeholder="e.g. 47",
        required=True,
        max_length=4
    )

    def __init__(self, game_id: int, team: str, week_number: int, week_id: int):
        super().__init__()
        self.game_id = game_id
        self.team = team
        self.week_number = week_number
        self.week_id = week_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            score = int(self.tiebreaker.value.strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Please enter a valid number for the tiebreaker.", ephemeral=True
            )
            return

        save_pick(
            user_id=str(interaction.user.id),
            username=str(interaction.user.display_name),
            game_id=self.game_id,
            week_id=self.week_id,
            picked_team=self.team,
            tiebreaker_score=score
        )

        await interaction.response.send_message(
            f"✅ You picked **{self.team}** with a tiebreaker of **{score}**!", ephemeral=True
        )


# --------------------------------#
# Build matchup embed             #
# --------------------------------#
def build_matchups_embed(week_number: int, games: list) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏈 NFL Pick'Em — Week {week_number}",
        description="Click a team to make your pick. MNF picks will ask for a tiebreaker score.",
        color=discord.Color.dark_gold()
    )

    for game in games:
        kickoff_pt = game["kickoff_time"]
        if isinstance(kickoff_pt, datetime):
            if kickoff_pt.tzinfo is None:
                kickoff_pt = kickoff_pt.replace(tzinfo=timezone.utc)
            kickoff_pt = kickoff_pt.astimezone(PT)
            time_str = kickoff_pt.strftime("%a %b %d • %I:%M %p PT")
        else:
            time_str = "TBD"

        mnf_tag = " 🌙 MNF" if game["is_mnf"] else ""
        embed.add_field(
            name=f"{game['away_team']} @ {game['home_team']}{mnf_tag}",
            value=time_str,
            inline=False
        )

    embed.set_footer(text=f"Picks lock at first kickoff • Week {week_number}")
    return embed


# --------------------------------#
# Build results embed             #
# --------------------------------#
def build_results_embed(week_number: int, leaderboard: list) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏆 Week {week_number} Results",
        color=discord.Color.gold()
    )

    medals = ["🥇", "🥈", "🥉"]

    for i, entry in enumerate(leaderboard):
        medal = medals[i] if i < 3 else f"`{i + 1}.`"
        tiebreaker = f" (TB: {entry['tiebreaker_score']})" if entry.get("tiebreaker_score") else ""
        embed.add_field(
            name=f"{medal} {entry['username']}",
            value=f"{entry['weekly_points']} pts{tiebreaker}",
            inline=False
        )

    embed.set_footer(text=f"Week {week_number} • NFC West Pick'Em")
    return embed


# --------------------------------#
# Build overall leaderboard embed #
# --------------------------------#
def build_overall_leaderboard_embed(leaderboard: list) -> discord.Embed:
    embed = discord.Embed(
        title="🏆 Overall Leaderboard",
        color=discord.Color.dark_gold()
    )

    medals = ["🥇", "🥈", "🥉"]

    for i, entry in enumerate(leaderboard):
        medal = medals[i] if i < 3 else f"`{i + 1}.`"
        embed.add_field(
            name=f"{medal} {entry['username']}",
            value=f"{entry['total_points']} total pts",
            inline=False
        )

    embed.set_footer(text="NFC West Pick'Em • All-Time Standings")
    return embed


# --------------------------------#
# Post Tuesday results            #
# --------------------------------#
async def post_results(client, week_number: int):
    channel = client.get_channel(get_channel_id(PICKEM_CHANNEL))

    if not channel:
        print(f"[PickEm] Could not find {PICKEM_CHANNEL} channel.")
        return

    # check if all games have scores
    games = get_games(week_number)
    missing = [g for g in games if g["home_score"] is None or g["away_score"] is None]

    if missing:
        print(f"[PickEm] {len(missing)} games still missing scores, retrying in 30 min...")
        return False

    calculate_and_save_scores(week_number)

    weekly_lb = get_weekly_leaderboard(week_number)
    overall_lb = get_overall_leaderboard()

    await channel.send(embed=build_results_embed(week_number, weekly_lb))
    await channel.send(embed=build_overall_leaderboard_embed(overall_lb))

    mark_results_posted(week_number)
    print(f"[PickEm] Results posted for week {week_number}")
    return True


# --------------------------------#
# Tuesday results scheduler       #
# --------------------------------#
async def results_scheduler(client):
    await client.wait_until_ready()

    while not client.is_closed():
        now = datetime.now(PT)

        # next Tuesday 9AM PT
        days_ahead = (1 - now.weekday()) % 7
        if days_ahead == 0 and now.hour >= 9:
            days_ahead = 7

        next_tuesday = (now + timedelta(days=days_ahead)).replace(
            hour=9, minute=0, second=0, microsecond=0
        )

        sleep_seconds = (next_tuesday - now).total_seconds()
        print(f"[PickEm] Next results post: {next_tuesday}")
        await asyncio.sleep(max(sleep_seconds, 0))

        # figure out which week just ended
        week_number = now.isocalendar()[1]

        posted = False
        while not posted:
            posted = await post_results(client, week_number)
            if not posted:
                await asyncio.sleep(RESULTS_RETRY_INTERVAL)


# --------------------------------#
# Command handler                 #
# --------------------------------#
async def handle_pickem_command(message, client):
    content = message.content.strip().lower()
    channel = message.channel

    pickem_channel_id = get_channel_id(PICKEM_CHANNEL)

    # ── !weekN ──────────────────────────────────────
    if content.startswith("!week"):
        if channel.id != int(pickem_channel_id):
            await message.channel.send(f"❌ Use <#{pickem_channel_id}> for pick'em commands.")
            return True

        try:
            week_number = int(content.replace("!week", "").strip())
        except ValueError:
            await message.channel.send("❌ Invalid week. Usage: `!week2`")
            return True

        games = get_games(week_number)

        if not games:
            await message.channel.send(f"⏳ No games found for week {week_number}. Try `!fetchschedule {week_number}` first.")
            return True

        week_id = get_or_create_week(week_number)
        embed = build_matchups_embed(week_number, games)
        view = build_picks_view(games, week_number, week_id)
        await channel.send(embed=embed, view=view)

        # schedule auto-lock
        asyncio.create_task(schedule_auto_lock(client, week_number))
        return True

    # ── !fetchschedule N ────────────────────────────
    if content.startswith("!fetchschedule"):
        try:
            week_number = int(content.split()[1])
        except (IndexError, ValueError):
            await message.channel.send("❌ Usage: `!fetchschedule 2`")
            return True

        await message.channel.send(f"⏳ Fetching schedule for week {week_number}...")
        games = await fetch_and_save_schedule(week_number)

        if games:
            await message.channel.send(f"✅ Saved {len(games)} games for week {week_number}.")
        else:
            await message.channel.send(f"❌ No games found for week {week_number}.")
        return True

    # ── !lock weekN ─────────────────────────────────
    if content.startswith("!lock"):
        try:
            week_number = int(content.split()[1].replace("week", ""))
        except (IndexError, ValueError):
            await message.channel.send("❌ Usage: `!lock week2`")
            return True

        lock_week(week_number)
        await message.channel.send(f"🔒 Week {week_number} picks have been locked.")
        return True

    # ── !setscore ───────────────────────────────────
    if content.startswith("!setscore"):
        # usage: !setscore <game_id> <home_score> <away_score>
        try:
            parts = content.split()
            game_id = int(parts[1])
            home_score = int(parts[2])
            away_score = int(parts[3])
        except (IndexError, ValueError):
            await message.channel.send("❌ Usage: `!setscore <game_id> <home_score> <away_score>`")
            return True

        set_game_score(game_id, home_score, away_score)
        await message.channel.send(f"✅ Score set for game {game_id}: {home_score} - {away_score}")
        return True

    # ── !results weekN ──────────────────────────────
    if content.startswith("!results"):
        try:
            week_number = int(content.split()[1].replace("week", ""))
        except (IndexError, ValueError):
            await message.channel.send("❌ Usage: `!results week2`")
            return True

        await message.channel.send(f"⏳ Calculating results for week {week_number}...")
        posted = await post_results(client, week_number)

        if not posted:
            await message.channel.send("⚠️ Some scores are still missing. Use `!setscore` to enter them manually.")
        return True

    # ── !leaderboard ────────────────────────────────
    if content.startswith("!leaderboard"):
        overall_lb = get_overall_leaderboard()
        embed = build_overall_leaderboard_embed(overall_lb)
        await channel.send(embed=embed)
        return True

    # ── !mypicks weekN ──────────────────────────────
    if content.startswith("!mypicks"):
        try:
            week_number = int(content.split()[1].replace("week", ""))
        except (IndexError, ValueError):
            await message.channel.send("❌ Usage: `!mypicks week2`")
            return True

        picks = get_user_picks(str(message.author.id), week_number)

        if not picks:
            await message.channel.send(f"You haven't made any picks for week {week_number} yet.", ephemeral=True)
            return True

        embed = discord.Embed(
            title=f"📋 Your Week {week_number} Picks",
            color=discord.Color.blurple()
        )

        for pick in picks:
            mnf_tag = " 🌙 MNF" if pick["is_mnf"] else ""
            tb = f"\nTiebreaker: {pick['tiebreaker_score']}" if pick.get("tiebreaker_score") else ""
            embed.add_field(
                name=f"{pick['away_team']} @ {pick['home_team']}{mnf_tag}",
                value=f"Your pick: **{pick['picked_team']}**{tb}",
                inline=False
            )

        await message.channel.send(embed=embed)
        return True

    return False