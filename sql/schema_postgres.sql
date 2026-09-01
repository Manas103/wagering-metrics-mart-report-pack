-- Real PostgreSQL DDL for the wagering mart. Executed for real against a
-- live PostgreSQL 14.24 instance during this build (see README, "Honest
-- framing"); DuckDB is what actually processes the 25M-row batch, this
-- schema is what the mart_metrics table (and, for verification, the raw
-- fact tables) look like when they land in Postgres.
--
-- Stand-up commands used on this machine (WSL2 Ubuntu 22.04):
--   sudo service postgresql start
--   sudo -u postgres psql -c "CREATE USER wagering_app WITH PASSWORD 'wagering_app_pw';"
--   sudo -u postgres psql -c "CREATE DATABASE wagering_mart OWNER wagering_app;"
--   psql "postgresql://wagering_app:wagering_app_pw@localhost:5432/wagering_mart" -f sql/schema_postgres.sql

CREATE TABLE IF NOT EXISTS fact_bet_legs (
    leg_id            BIGINT PRIMARY KEY,
    bet_id            BIGINT NOT NULL,
    leg_no            SMALLINT NOT NULL,
    state             CHAR(2) NOT NULL,
    product           TEXT NOT NULL,
    placed_ts         TIMESTAMP NOT NULL,
    currency          CHAR(3) NOT NULL,
    true_win_prob     DOUBLE PRECISION NOT NULL,
    vig               DOUBLE PRECISION NOT NULL,
    implied_prob      DOUBLE PRECISION NOT NULL,
    decimal_odds      DOUBLE PRECISION NOT NULL,
    american_odds     DOUBLE PRECISION,
    leg_structural_hold DOUBLE PRECISION NOT NULL,
    leg_outcome       TEXT NOT NULL CHECK (leg_outcome IN ('win', 'loss', 'push'))
);
CREATE INDEX IF NOT EXISTS idx_legs_bet_id ON fact_bet_legs (bet_id);
CREATE INDEX IF NOT EXISTS idx_legs_state_product ON fact_bet_legs (state, product);

CREATE TABLE IF NOT EXISTS fact_settlements (
    bet_id            BIGINT PRIMARY KEY,
    customer_id       BIGINT,
    state             TEXT,
    product           TEXT,
    is_parlay         BOOLEAN NOT NULL,
    num_legs          SMALLINT NOT NULL,
    currency          TEXT NOT NULL,
    stake             DOUBLE PRECISION NOT NULL,
    placed_ts         TIMESTAMP NOT NULL,
    settled_ts        TIMESTAMP NOT NULL,
    bet_outcome       TEXT NOT NULL,
    payout            DOUBLE PRECISION NOT NULL,
    structural_hold   DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_settle_state_product ON fact_settlements (state, product);
CREATE INDEX IF NOT EXISTS idx_settle_customer ON fact_settlements (customer_id);
CREATE INDEX IF NOT EXISTS idx_settle_placed_ts ON fact_settlements (placed_ts);

-- The one flat, pivot-ready mart table: (year_month, state, product) grain.
-- Every column here has exactly one definition, see docs/METRIC_DEFINITIONS.md.
CREATE TABLE IF NOT EXISTS mart_metrics (
    year_month        CHAR(7) NOT NULL,
    state             TEXT NOT NULL,
    product           TEXT NOT NULL,
    bet_count         BIGINT NOT NULL,
    handle            NUMERIC(18, 2) NOT NULL,
    payout            NUMERIC(18, 2) NOT NULL,
    net_revenue       NUMERIC(18, 2) NOT NULL,
    actual_hold       DOUBLE PRECISION,
    structural_hold   DOUBLE PRECISION,
    parlay_handle     NUMERIC(18, 2) NOT NULL,
    parlay_mix        DOUBLE PRECISION,
    unique_payers     BIGINT NOT NULL,
    revenue_per_mup   NUMERIC(18, 2),
    PRIMARY KEY (year_month, state, product)
);
