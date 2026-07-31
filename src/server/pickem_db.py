import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()


# --------------------------------#
# Connection                      #
# --------------------------------#
def get_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "db"),  # Changed default from "127.0.0.1" to "db"
        port=int(os.getenv("DB_PORT", 3306)),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "nfcw_bot")
    )


# --------------------------------#
# Weeks                           #
# --------------------------------#
def get_or_create_week(week_number: int) -> int:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM weeks WHERE week_number = %s", (week_number,))
    row = cursor.fetchone()

    if row:
        week_id = row[0]
    else:
        cursor.execute(
            "INSERT INTO weeks (week_number, locked, results_posted) VALUES (%s, FALSE, FALSE)",
            (week_number,)
        )
        conn.commit()
        week_id = cursor.lastrowid

    cursor.close()
    conn.close()
    return week_id


def lock_week(week_number: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE weeks SET locked = TRUE WHERE week_number = %s", (week_number,))
    conn.commit()
    cursor.close()
    conn.close()


def unlock_week(week_number: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE weeks SET locked = FALSE WHERE week_number = %s", (week_number,))
    conn.commit()
    cursor.close()
    conn.close()


def is_week_locked(week_number: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT locked FROM weeks WHERE week_number = %s", (week_number,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row[0] if row else False


def mark_results_posted(week_number: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE weeks SET results_posted = TRUE WHERE week_number = %s", (week_number,))
    conn.commit()
    cursor.close()
    conn.close()


# --------------------------------#
# Games                           #
# --------------------------------#
def save_games(week_number: int, games: list):
    """
    games: list of dicts with keys:
      home_team, away_team, kickoff_time (datetime), is_mnf (bool)
    """
    conn = get_connection()
    cursor = conn.cursor()

    week_id = get_or_create_week(week_number)

    # clear existing games for this week before re-inserting
    cursor.execute("DELETE FROM picks WHERE week_id = %s", (week_id,))
    cursor.execute("DELETE FROM games WHERE week_id = %s", (week_id,))

    for game in games:
        cursor.execute(
            """
            INSERT INTO games (week_id, home_team, away_team, kickoff_time, is_mnf)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (week_id, game["home_team"], game["away_team"], game["kickoff_time"], game["is_mnf"])
        )

    conn.commit()
    cursor.close()
    conn.close()


def get_games(week_number: int) -> list:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT g.* FROM games g
        JOIN weeks w ON g.week_id = w.id
        WHERE w.week_number = %s
        ORDER BY g.kickoff_time ASC
        """,
        (week_number,)
    )

    games = cursor.fetchall()
    cursor.close()
    conn.close()
    return games


def set_game_score(game_id: int, home_score: int, away_score: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE games SET home_score = %s, away_score = %s WHERE id = %s",
        (home_score, away_score, game_id)
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_mnf_game(week_number: int) -> dict:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT g.* FROM games g
        JOIN weeks w ON g.week_id = w.id
        WHERE w.week_number = %s AND g.is_mnf = TRUE
        LIMIT 1
        """,
        (week_number,)
    )
    game = cursor.fetchone()
    cursor.close()
    conn.close()
    return game


# --------------------------------#
# Picks                           #
# --------------------------------#
def save_pick(user_id: str, username: str, game_id: int, week_id: int, picked_team: str, tiebreaker_score: int = None):
    conn = get_connection()
    cursor = conn.cursor()

    # upsert — update if pick already exists for this game
    cursor.execute(
        """
        INSERT INTO picks (user_id, username, game_id, week_id, picked_team, tiebreaker_score)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            picked_team = VALUES(picked_team),
            tiebreaker_score = VALUES(tiebreaker_score)
        """,
        (user_id, username, game_id, week_id, picked_team, tiebreaker_score)
    )

    conn.commit()
    cursor.close()
    conn.close()


def get_user_picks(user_id: str, week_number: int) -> list:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT p.*, g.home_team, g.away_team, g.is_mnf
        FROM picks p
        JOIN games g ON p.game_id = g.id
        JOIN weeks w ON p.week_id = w.id
        WHERE p.user_id = %s AND w.week_number = %s
        """,
        (user_id, week_number)
    )

    picks = cursor.fetchall()
    cursor.close()
    conn.close()
    return picks


def get_all_picks_for_week(week_number: int) -> list:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT p.*, g.home_team, g.away_team, g.home_score, g.away_score, g.is_mnf
        FROM picks p
        JOIN games g ON p.game_id = g.id
        JOIN weeks w ON p.week_id = w.id
        WHERE w.week_number = %s
        """,
        (week_number,)
    )

    picks = cursor.fetchall()
    cursor.close()
    conn.close()
    return picks


# --------------------------------#
# Scores                          #
# --------------------------------#
def calculate_and_save_scores(week_number: int):
    """
    Scoring rules:
      - Outright most correct picks in the week -> 3 points (Win)
      - If tied for the TOP spot, tiebreaker (closest to actual MNF combined score) decides:
            tiebreaker winner among the tied group -> 2 points
            remaining tied-for-first users           -> 1 point
      - Any other tie (not for first place)          -> 1 point each
      - Everyone else (strictly lower, not tied)       -> 0 points
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    week_id_cursor = conn.cursor()
    week_id_cursor.execute("SELECT id FROM weeks WHERE week_number = %s", (week_number,))
    week_row = week_id_cursor.fetchone()
    week_id_cursor.close()

    if not week_row:
        conn.close()
        return

    week_id = week_row[0]

    # get all picks with game results
    cursor.execute(
        """
        SELECT p.user_id, p.username, p.picked_team, p.tiebreaker_score,
               g.home_team, g.away_team, g.home_score, g.away_score, g.is_mnf
        FROM picks p
        JOIN games g ON p.game_id = g.id
        WHERE p.week_id = %s AND g.home_score IS NOT NULL AND g.away_score IS NOT NULL
        """,
        (week_id,)
    )

    picks = cursor.fetchall()

    # tally correct picks per user, and capture their MNF tiebreaker guess + actual MNF total
    user_data = {}
    mnf_actual_total = None

    for pick in picks:
        uid = pick["user_id"]
        username = pick["username"]

        if pick["home_score"] > pick["away_score"]:
            winner = pick["home_team"]
        else:
            winner = pick["away_team"]

        correct = pick["picked_team"] == winner

        if uid not in user_data:
            user_data[uid] = {"username": username, "correct": 0, "tiebreaker_guess": None}

        if correct:
            user_data[uid]["correct"] += 1

        if pick["is_mnf"]:
            if pick["tiebreaker_score"] is not None:
                user_data[uid]["tiebreaker_guess"] = pick["tiebreaker_score"]
            if mnf_actual_total is None:
                mnf_actual_total = pick["home_score"] + pick["away_score"]

    if not user_data:
        conn.close()
        return

    # rank users by correct picks, descending
    ranked = sorted(user_data.items(), key=lambda kv: kv[1]["correct"], reverse=True)

    # group users by their correct-pick count (tiers)
    top_score = ranked[0][1]["correct"]

    final_points = {}

    # find everyone tied for the top score
    top_tier = [uid for uid, data in ranked if data["correct"] == top_score]

    if len(top_tier) == 1:
        # outright winner, no tie
        winner_uid = top_tier[0]
        final_points[winner_uid] = 3
    else:
        # tied for first -> resolve with tiebreaker (closest to actual MNF total)
        if mnf_actual_total is not None:
            def distance(uid):
                guess = user_data[uid]["tiebreaker_guess"]
                if guess is None:
                    return float("inf")
                return abs(guess - mnf_actual_total)

            tiebreak_winner = min(top_tier, key=distance)
            final_points[tiebreak_winner] = 2

            for uid in top_tier:
                if uid != tiebreak_winner:
                    final_points[uid] = 1
        else:
            # no MNF data available to break the tie, everyone tied gets 1 point
            for uid in top_tier:
                final_points[uid] = 1

    # handle ties at lower tiers (not first place) -> 1 point each
    remaining = [(uid, data) for uid, data in ranked if uid not in final_points]

    # group remaining by correct count
    from itertools import groupby
    remaining.sort(key=lambda kv: kv[1]["correct"], reverse=True)

    for correct_count, group in groupby(remaining, key=lambda kv: kv[1]["correct"]):
        group = list(group)
        if len(group) > 1:
            for uid, _ in group:
                final_points[uid] = 1
        else:
            uid, _ = group[0]
            final_points[uid] = 0

    # map points to result type: 3=Win, 2=Win(tiebreak), 1=Tie, 0=Loss
    def result_type(points):
        if points in (3, 2):
            return "W"
        elif points == 1:
            return "T"
        else:
            return "L"

    # save weekly scores and update totals
    update_cursor = conn.cursor()

    for uid, data in user_data.items():
        points = final_points.get(uid, 0)
        username = data["username"]
        result = result_type(points)

        update_cursor.execute(
            """
            INSERT INTO scores (user_id, username, week_id, weekly_points, total_points, result)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                weekly_points = VALUES(weekly_points),
                username = VALUES(username),
                result = VALUES(result)
            """,
            (uid, username, week_id, points, points, result)
        )

        update_cursor.execute(
            """
            UPDATE scores SET total_points = (
                SELECT total FROM (
                    SELECT SUM(weekly_points) as total FROM scores WHERE user_id = %s
                ) AS tmp
            )
            WHERE user_id = %s
            """,
            (uid, uid)
        )

    conn.commit()
    update_cursor.close()
    cursor.close()
    conn.close()

def get_weekly_leaderboard(week_number: int) -> list:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT s.user_id, s.username, s.weekly_points, s.result,
               p.tiebreaker_score
        FROM scores s
        JOIN weeks w ON s.week_id = w.id
        LEFT JOIN picks p ON p.user_id = s.user_id AND p.week_id = w.id
        LEFT JOIN games g ON p.game_id = g.id AND g.is_mnf = TRUE
        WHERE w.week_number = %s
        ORDER BY s.weekly_points DESC, p.tiebreaker_score ASC
        """,
        (week_number,)
    )

    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results


def get_overall_leaderboard() -> list:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute(
        """
        SELECT
            user_id,
            username,
            SUM(weekly_points) as total_points,
            SUM(CASE WHEN result = 'W' THEN 1 ELSE 0 END) as wins,
            SUM(CASE WHEN result = 'L' THEN 1 ELSE 0 END) as losses,
            SUM(CASE WHEN result = 'T' THEN 1 ELSE 0 END) as ties
        FROM scores
        GROUP BY user_id, username
        ORDER BY total_points DESC
        """
    )

    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results