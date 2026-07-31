import discord
import aiohttp
import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytz

from server.pickem_db import (
    get_or_create_week,
    lock_week,
    unlock_week,
    is_week_locked,
    mark_results_posted,
    save_games,
    get_games,
    set_game_score,
    get_mnf_game,
    save_pick,
    get_user_picks,
    get_all_picks_for_week,
    calculate_and_save_scores,
    get_weekly_leaderboard,
    get_overall_leaderboard,
)
from countdown import get_channel_id
from channel_control import open_channel, close_channel

PT = pytz.timezone("America/Los_Angeles")
PICKEM_CHANNEL = "pick_ems"

RESULTS_RETRY_INTERVAL = 30 * 60  # 30 minutes
PICKING_LOCK_TIMEOUT = 5 * 60  # 5 minutes

# maps ESPN displayName to the custom emoji name uploaded in the server
def _load_json_config(filename: str) -> dict:
    config_path = Path("config") / filename
    with open(config_path, "r") as f:
        return json.load(f)


TEAM_EMOJI_NAMES = _load_json_config("team-emoji-names.json")
TEAM_ABBREVIATIONS = _load_json_config("team-abbreviations.json")


def get_team_emoji(guild, team_name: str):
    """Look up the custom emoji for a team by its full ESPN display name."""
    emoji_name = TEAM_EMOJI_NAMES.get(team_name)
    if not emoji_name or not guild:
        return None
    return discord.utils.get(guild.emojis, name=emoji_name)


def get_team_abbreviation(team_name: str) -> str:
    """Get the short label for buttons; falls back to full name if not found."""
    return TEAM_ABBREVIATIONS.get(team_name, team_name)


# --------------------------------#
# ESPN Schedule Fetch             #
# --------------------------------#
async def fetch_nfl_schedule(week_number: int) -> list:
    """
    NOTE: ESPN's scoreboard endpoint has a known CDN caching bug when queried
    with `seasontype` + `week` params together — it can silently return a
    stale/previous season's data instead of 404ing or erroring. To avoid it,
    we first hit the bare scoreboard endpoint (which is reliably live) to read
    the season's `calendar`, find the actual date range for the requested
    week, then re-query using `dates=YYYYMMDD-YYYYMMDD`, which isn't affected
    by that caching issue.
    """
    async with aiohttp.ClientSession() as session:
        # Step 1: get current season + calendar (always fresh)
        async with session.get(
            "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
        ) as response:
            base_data = await response.json(content_type=None)

        # Find the "Regular Season" calendar block, then the matching week entry
        week_entry = None
        for block in base_data.get("leagues", [{}])[0].get("calendar", []):
            if block.get("label") == "Regular Season":
                for entry in block.get("entries", []):
                    if entry.get("value") == str(week_number):
                        week_entry = entry
                        break
                break

        if not week_entry:
            print(f"[PickEm] Could not find calendar entry for week {week_number}")
            return []

        start = datetime.fromisoformat(week_entry["startDate"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(week_entry["endDate"].replace("Z", "+00:00"))
        dates_param = f"{start:%Y%m%d}-{end:%Y%m%d}"

        # Step 2: query by explicit date range instead of seasontype/week
        url = f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={dates_param}&limit=1000"
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

        kickoff_pt = kickoff.astimezone(PT)
        is_mnf = kickoff_pt.weekday() == 0

        games.append({
            "home_team": home["team"]["displayName"],
            "away_team": away["team"]["displayName"],
            "kickoff_time": kickoff,
            "is_mnf": is_mnf,
        })

    games.sort(key=lambda g: g["kickoff_time"])
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

    if wait_seconds <= 0:
        print(f"[PickEm] Kickoff for week {week_number} already passed, skipping auto-lock scheduling.")
        return

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
def build_picks_view(games: list, week_number: int, week_id: int, owner_id: int, guild=None, done_button: discord.ui.Button = None):
    view = discord.ui.View(timeout=None)

    for i, game in enumerate(games):
        row = i  # each game gets its own row (max 5 rows = 5 games per message)
        away_emoji = get_team_emoji(guild, game["away_team"])
        home_emoji = get_team_emoji(guild, game["home_team"])

        view.add_item(PickButton(
            game_id=game["id"],
            team=game["away_team"],
            week_number=week_number,
            week_id=week_id,
            is_mnf=game["is_mnf"],
            owner_id=owner_id,
            row=row,
            emoji=away_emoji
        ))
        view.add_item(PickButton(
            game_id=game["id"],
            team=game["home_team"],
            week_number=week_number,
            week_id=week_id,
            is_mnf=game["is_mnf"],
            owner_id=owner_id,
            row=row,
            emoji=home_emoji
        ))

    if done_button:
        view.add_item(done_button)

    return view


# --------------------------------#
# Pick Button                     #
# --------------------------------#
class PickButton(discord.ui.Button):
    def __init__(self, game_id: int, team: str, week_number: int, week_id: int, is_mnf: bool, owner_id: int, row: int = 0, emoji=None):
        super().__init__(
            label=get_team_abbreviation(team),
            style=discord.ButtonStyle.primary,
            custom_id=f"pick_{game_id}_{team}",
            row=row,
            emoji=emoji
        )
        self.game_id = game_id
        self.team = team
        self.week_number = week_number
        self.week_id = week_id
        self.is_mnf = is_mnf
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "It's not your turn to pick right now.", ephemeral=True
            )
            return

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
                    week_id=self.week_id,
                    pick_button=self
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
            await self.lock_matchup_row(interaction)

    async def lock_matchup_row(self, interaction: discord.Interaction):
        """Disable both buttons in this matchup row and highlight the picked team."""
        for item in self.view.children:
            if isinstance(item, PickButton) and item.game_id == self.game_id:
                item.disabled = True
                if item.team == self.team:
                    item.style = discord.ButtonStyle.success
                else:
                    item.style = discord.ButtonStyle.secondary

        await interaction.response.edit_message(view=self.view)


# --------------------------------#
# Tiebreaker Modal (MNF)          #
# --------------------------------#
class TiebreakerModal(discord.ui.Modal, title="Monday Night Football Tiebreaker"):
    tiebreaker = discord.ui.TextInput(
        label="Predict the total combined score",
        style=discord.TextStyle.short,
        placeholder="e.g. 47",
        required=True,
        max_length=4
    )

    def __init__(self, game_id: int, team: str, week_number: int, week_id: int, pick_button: "PickButton"):
        super().__init__()
        self.game_id = game_id
        self.team = team
        self.week_number = week_number
        self.week_id = week_id
        self.pick_button = pick_button

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

        # disable both buttons in this matchup row, highlight the picked team
        view = self.pick_button.view
        for item in view.children:
            if isinstance(item, PickButton) and item.game_id == self.game_id:
                item.disabled = True
                if item.team == self.team:
                    item.style = discord.ButtonStyle.success
                    item.label = f"{get_team_abbreviation(item.team)} ({score})"
                else:
                    item.style = discord.ButtonStyle.secondary

        await interaction.response.edit_message(view=view)


# --------------------------------#
# Done Button + channel unlock    #
# --------------------------------#
class DoneButton(discord.ui.Button):
    def __init__(self, user_id: int, week_number: int, all_messages: list = None):
        super().__init__(
            label="✅ Done Picking",
            style=discord.ButtonStyle.success,
            custom_id=f"done_{user_id}_{week_number}"
        )
        self.target_user_id = user_id
        self.week_number = week_number
        self.all_messages = all_messages or []

    async def callback(self, interaction: discord.Interaction):
        print("[PickEm] Done button clicked")

        if interaction.user.id != self.target_user_id:
            await interaction.response.send_message(
                "Only the person who ran the command can finish up.", ephemeral=True
            )
            return

        try:
            # remove buttons from every matchup message for this session
            for msg in self.all_messages:
                try:
                    await msg.edit(view=None)
                except discord.NotFound:
                    pass

            # remove the Done button itself from this message
            await interaction.response.edit_message(view=None)
            print("[PickEm] Cleared button views")

            # post the thank you + picks summary
            picks = get_user_picks(str(interaction.user.id), self.week_number)
            print(f"[PickEm] Retrieved {len(picks)} picks for summary")

            embed = build_thanks_embed(interaction.user, self.week_number, picks)
            await interaction.followup.send(embed=embed)
            print("[PickEm] Sent thanks embed")

            await unlock_pickem_channel(interaction.guild, interaction.client, self.week_number)
            print("[PickEm] Channel unlocked")

        except Exception as e:
            import traceback
            print(f"[PickEm] ERROR in DoneButton callback: {e}")
            traceback.print_exc()


def build_thanks_embed(user, week_number: int, picks: list) -> discord.Embed:
    embed = discord.Embed(
        title="🏈 Thanks for playing!",
        description=f"Here's what **{user.display_name}** picked for Week {week_number}:",
        color=discord.Color.green()
    )

    for pick in picks:
        mnf_tag = " 🌙 MNF" if pick.get("is_mnf") else ""
        tb = f" (Tiebreaker: {pick['tiebreaker_score']})" if pick.get("tiebreaker_score") else ""
        embed.add_field(
            name=f"{pick['away_team']} @ {pick['home_team']}{mnf_tag}",
            value=f"Picked: **{pick['picked_team']}**{tb}",
            inline=False
        )

    embed.set_footer(text=f"Week {week_number} • NFC West Pick'Em")
    return embed


async def unlock_pickem_channel(guild, client, week_number: int):
    channel_id = int(get_channel_id(PICKEM_CHANNEL))
    channel = client.get_channel(channel_id)

    if not channel:
        return

    await open_channel(guild, channel)
    print(f"[PickEm] Channel unlocked after week {week_number} picks session")


async def auto_unlock_after_timeout(guild, client, week_number: int, locked_by: int):
    await asyncio.sleep(PICKING_LOCK_TIMEOUT)

    channel_id = int(get_channel_id(PICKEM_CHANNEL))
    channel = client.get_channel(channel_id)

    if not channel:
        return

    overwrite = channel.overwrites_for(channel.guild.default_role)

    # only auto-unlock if it's still locked (avoid reopening if user already finished)
    if overwrite.send_messages is False:
        await open_channel(guild, channel)
        print(f"[PickEm] Channel auto-unlocked after {PICKING_LOCK_TIMEOUT}s timeout")


# --------------------------------#
# Build matchup embed             #
# --------------------------------#
def build_matchups_embed(week_number: int, games: list, part: int = 1, total: int = 1) -> discord.Embed:
    part_tag = f" (Part {part}/{total})" if total > 1 else ""
    embed = discord.Embed(
        title=f"🏈 NFL Pick'Em — Week {week_number}{part_tag}",
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
# Build rules embed               #
# --------------------------------#
def build_rules_embed() -> discord.Embed:
    embed = discord.Embed(
        title="📋 NFC West Pick'Em Rules",
        description="How scoring works each week:",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🥇 Most Correct Picks",
        value="The player with the most correct picks for the week earns **3 points** (Win).",
        inline=False
    )
    embed.add_field(
        name="🌙 Tiebreaker Win",
        value="If players are tied for the most correct picks, whoever is closest to the actual combined score of Monday Night Football wins the tiebreaker and earns **2 points** (Win).",
        inline=False
    )
    embed.add_field(
        name="🤝 Tie",
        value="Any other tie earns **1 point** each.",
        inline=False
    )
    embed.add_field(
        name="❌ Otherwise",
        value="No points earned.",
        inline=False
    )

    embed.set_footer(text="NFC West Pick'Em")
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

        # lock channel chat while this user makes their picks (prevents clutter)
        await close_channel(message.guild, channel)

        # split into chunks of 4 games (8 buttons) per message to stay under Discord 25 button limit
        chunk_size = 5
        chunks = [games[i:i + chunk_size] for i in range(0, len(games), chunk_size)]

        sent_messages = []
        done_button = None

        for i, chunk in enumerate(chunks):
            embed = build_matchups_embed(week_number, chunk, part=i + 1, total=len(chunks))
            is_last_chunk = (i == len(chunks) - 1)

            if is_last_chunk:
                done_button = DoneButton(message.author.id, week_number)

            view = build_picks_view(chunk, week_number, week_id, owner_id=message.author.id, guild=message.guild, done_button=done_button if is_last_chunk else None)
            sent_msg = await channel.send(embed=embed, view=view)
            sent_messages.append(sent_msg)

        # now that all messages are sent, give the Done button the full list to clean up later
        # (exclude the last message since its own response.edit_message call handles that one)
        if done_button:
            done_button.all_messages = sent_messages[:-1]

        # auto-unlock if the user never clicks Done
        asyncio.create_task(auto_unlock_after_timeout(message.guild, client, week_number, message.author.id))

        # schedule auto-lock for picks (separate from the chat lock above)
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

    # ── !unlock weekN ───────────────────────────────
    if content.startswith("!unlock"):
        try:
            week_number = int(content.split()[1].replace("week", ""))
        except (IndexError, ValueError):
            await message.channel.send("❌ Usage: `!unlock week2`")
            return True

        unlock_week(week_number)
        await message.channel.send(f"🔓 Week {week_number} picks have been unlocked.")
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

    # ── !pickemrules ────────────────────────────────
    if content.startswith("!pickemrules"):
        embed = build_rules_embed()
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