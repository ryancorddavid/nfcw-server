-- --------------------------------------------------------------
-- NFC West Pick'Em schema
-- Reconstructed from src/server/pickem_db.py query usage since
-- no original CREATE TABLE / migration file existed in the repo.
-- --------------------------------------------------------------

CREATE TABLE IF NOT EXISTS weeks (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    week_number     INT NOT NULL,
    locked          BOOLEAN NOT NULL DEFAULT FALSE,
    results_posted  BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE KEY uq_week_number (week_number)
);

CREATE TABLE IF NOT EXISTS games (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    week_id        INT NOT NULL,
    home_team      VARCHAR(255) NOT NULL,
    away_team      VARCHAR(255) NOT NULL,
    kickoff_time   DATETIME NOT NULL,
    is_mnf         BOOLEAN NOT NULL DEFAULT FALSE,
    home_score     INT NULL,
    away_score     INT NULL,
    FOREIGN KEY (week_id) REFERENCES weeks(id) ON DELETE CASCADE,
    KEY idx_games_week_id (week_id)
);

CREATE TABLE IF NOT EXISTS picks (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    user_id            VARCHAR(32) NOT NULL,
    username           VARCHAR(255) NOT NULL,
    game_id            INT NOT NULL,
    week_id            INT NOT NULL,
    picked_team        VARCHAR(255) NOT NULL,
    tiebreaker_score   INT NULL,
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
    FOREIGN KEY (week_id) REFERENCES weeks(id) ON DELETE CASCADE,
    UNIQUE KEY uq_user_game (user_id, game_id),
    KEY idx_picks_week_id (week_id)
);

CREATE TABLE IF NOT EXISTS scores (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    user_id        VARCHAR(32) NOT NULL,
    username       VARCHAR(255) NOT NULL,
    week_id        INT NOT NULL,
    weekly_points  INT NOT NULL DEFAULT 0,
    total_points   INT NOT NULL DEFAULT 0,
    result         VARCHAR(1) NOT NULL,
    FOREIGN KEY (week_id) REFERENCES weeks(id) ON DELETE CASCADE,
    UNIQUE KEY uq_user_week (user_id, week_id),
    KEY idx_scores_week_id (week_id)
);