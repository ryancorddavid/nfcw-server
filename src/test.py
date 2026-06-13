import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from server.pickem_db import (
    get_or_create_week,
    lock_week,
    is_week_locked,
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
from pickem import fetch_nfl_schedule

WEEK = 1  # test week number


# --------------------------------#
# Helpers                         #
# --------------------------------#
def section(title):
    print(f"\n{'=' * 50}")
    print(f"  {title}")
    print('=' * 50)

def ok(msg):
    print(f"  ✅ {msg}")

def fail(msg):
    print(f"  ❌ {msg}")


# --------------------------------#
# Test 1: DB Connection           #
# --------------------------------#
def test_db_connection():
    section("Test 1: Database Connection")
    try:
        from server.pickem_db import get_connection
        conn = get_connection()
        conn.close()
        ok("Connected to MySQL successfully")
    except Exception as e:
        fail(f"Could not connect: {e}")
        sys.exit(1)


# --------------------------------#
# Test 2: Week creation           #
# --------------------------------#
def test_week_creation():
    section("Test 2: Week Creation")
    try:
        week_id = get_or_create_week(WEEK)
        ok(f"Week {WEEK} created/found with id={week_id}")
    except Exception as e:
        fail(f"Week creation failed: {e}")


# --------------------------------#
# Test 3: Save mock games         #
# --------------------------------#
def test_save_games():
    section("Test 3: Save Mock Games")
    from datetime import datetime, timezone

    mock_games = [
        {
            "home_team": "San Francisco 49ers",
            "away_team": "Seattle Seahawks",
            "kickoff_time": datetime(2026, 9, 10, 20, 15, tzinfo=timezone.utc),
            "is_mnf": False,
        },
        {
            "home_team": "Los Angeles Rams",
            "away_team": "Arizona Cardinals",
            "kickoff_time": datetime(2026, 9, 11, 20, 15, tzinfo=timezone.utc),
            "is_mnf": False,
        },
        {
            "home_team": "Dallas Cowboys",
            "away_team": "New York Giants",
            "kickoff_time": datetime(2026, 9, 14, 23, 15, tzinfo=timezone.utc),
            "is_mnf": True,
        },
    ]

    try:
        save_games(WEEK, mock_games)
        ok(f"Saved {len(mock_games)} mock games for week {WEEK}")
    except Exception as e:
        fail(f"Save games failed: {e}")


# --------------------------------#
# Test 4: Get games               #
# --------------------------------#
def test_get_games():
    section("Test 4: Get Games")
    try:
        games = get_games(WEEK)
        ok(f"Retrieved {len(games)} games for week {WEEK}")
        for g in games:
            mnf = " 🌙 MNF" if g["is_mnf"] else ""
            print(f"    [{g['id']}] {g['away_team']} @ {g['home_team']}{mnf} — {g['kickoff_time']}")
        return games
    except Exception as e:
        fail(f"Get games failed: {e}")
        return []


# --------------------------------#
# Test 5: Save picks              #
# --------------------------------#
def test_save_picks(games):
    section("Test 5: Save Picks")

    if not games:
        fail("No games to pick from, skipping")
        return

    week_id = get_or_create_week(WEEK)

    mock_users = [
        {"id": "111111111", "name": "TestUser1"},
        {"id": "222222222", "name": "TestUser2"},
        {"id": "333333333", "name": "TestUser3"},
    ]

    try:
        for user in mock_users:
            for game in games:
                picked = game["home_team"] if mock_users.index(user) % 2 == 0 else game["away_team"]
                tb = 47 if game["is_mnf"] else None
                save_pick(
                    user_id=user["id"],
                    username=user["name"],
                    game_id=game["id"],
                    week_id=week_id,
                    picked_team=picked,
                    tiebreaker_score=tb
                )

        ok(f"Saved picks for {len(mock_users)} users across {len(games)} games")
    except Exception as e:
        fail(f"Save picks failed: {e}")


# --------------------------------#
# Test 6: Get user picks          #
# --------------------------------#
def test_get_user_picks():
    section("Test 6: Get User Picks")
    try:
        picks = get_user_picks("111111111", WEEK)
        ok(f"Retrieved {len(picks)} picks for TestUser1")
        for p in picks:
            print(f"    {p['away_team']} @ {p['home_team']} → picked: {p['picked_team']}")
    except Exception as e:
        fail(f"Get user picks failed: {e}")


# --------------------------------#
# Test 7: Lock week               #
# --------------------------------#
def test_lock_week():
    section("Test 7: Lock Week")
    try:
        lock_week(WEEK)
        locked = is_week_locked(WEEK)
        if locked:
            ok(f"Week {WEEK} is now locked")
        else:
            fail("Week did not lock correctly")
    except Exception as e:
        fail(f"Lock week failed: {e}")


# --------------------------------#
# Test 8: Set game scores         #
# --------------------------------#
def test_set_scores(games):
    section("Test 8: Set Game Scores")

    if not games:
        fail("No games to score, skipping")
        return

    mock_scores = [
        (games[0]["id"], 24, 17),  # home wins
        (games[1]["id"], 10, 31),  # away wins
        (games[2]["id"], 28, 21),  # home wins (MNF)
    ]

    try:
        for game_id, home, away in mock_scores:
            set_game_score(game_id, home, away)
        ok(f"Set scores for {len(mock_scores)} games")
    except Exception as e:
        fail(f"Set scores failed: {e}")


# --------------------------------#
# Test 9: Calculate scores        #
# --------------------------------#
def test_calculate_scores():
    section("Test 9: Calculate & Save Scores")
    try:
        calculate_and_save_scores(WEEK)
        ok(f"Scores calculated for week {WEEK}")
    except Exception as e:
        fail(f"Score calculation failed: {e}")


# --------------------------------#
# Test 10: Weekly leaderboard     #
# --------------------------------#
def test_weekly_leaderboard():
    section("Test 10: Weekly Leaderboard")
    try:
        lb = get_weekly_leaderboard(WEEK)
        ok(f"Retrieved {len(lb)} entries for week {WEEK} leaderboard")
        for i, entry in enumerate(lb, 1):
            tb = f" (TB: {entry['tiebreaker_score']})" if entry.get("tiebreaker_score") else ""
            print(f"    {i}. {entry['username']} — {entry['weekly_points']} pts{tb}")
    except Exception as e:
        fail(f"Weekly leaderboard failed: {e}")


# --------------------------------#
# Test 11: Overall leaderboard    #
# --------------------------------#
def test_overall_leaderboard():
    section("Test 11: Overall Leaderboard")
    try:
        lb = get_overall_leaderboard()
        ok(f"Retrieved {len(lb)} entries for overall leaderboard")
        for i, entry in enumerate(lb, 1):
            print(f"    {i}. {entry['username']} — {entry['total_points']} total pts")
    except Exception as e:
        fail(f"Overall leaderboard failed: {e}")


# --------------------------------#
# Test 12: ESPN schedule fetch    #
# --------------------------------#
async def test_espn_fetch():
    section("Test 12: ESPN Schedule Fetch (Week 1)")
    try:
        games = await fetch_nfl_schedule(1)
        if games:
            ok(f"Fetched {len(games)} games from ESPN for week 1")
            for g in games[:3]:
                mnf = " 🌙 MNF" if g["is_mnf"] else ""
                print(f"    {g['away_team']} @ {g['home_team']}{mnf} — {g['kickoff_time']}")
            if len(games) > 3:
                print(f"    ... and {len(games) - 3} more")
        else:
            fail("No games returned from ESPN (offseason?)")
    except Exception as e:
        fail(f"ESPN fetch failed: {e}")


# --------------------------------#
# Run all tests                   #
# --------------------------------#
async def main():
    print("\n🏈 Pick'Em Feature Test Suite")

    test_db_connection()
    test_week_creation()
    test_save_games()
    games = test_get_games()
    test_save_picks(games)
    test_get_user_picks()
    test_lock_week()
    test_set_scores(games)
    test_calculate_scores()
    test_weekly_leaderboard()
    test_overall_leaderboard()
    await test_espn_fetch()

    print(f"\n{'=' * 50}")
    print("  ✅ All tests complete")
    print('=' * 50 + "\n")


if __name__ == "__main__":
    asyncio.run(main())