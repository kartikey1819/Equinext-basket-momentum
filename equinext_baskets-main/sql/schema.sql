-- Equinext shared schema.
-- Written portable: runs on SQLite (now) and is close to the Postgres target.
-- The raw `ohlcv` + index tables already live in nifty500_hrp.db (the source DB).
-- These are the tables WE create in the project DB.

CREATE TABLE IF NOT EXISTS securities (
    symbol TEXT PRIMARY KEY,
    name   TEXT,
    sector TEXT,
    isin   TEXT
);

-- the valuation series behind screener's charts (derive: price x fundamentals)
CREATE TABLE IF NOT EXISTS valuation_series (
    symbol    TEXT REFERENCES securities,
    date      DATE,
    pe        NUMERIC,
    pb        NUMERIC,
    ev_ebitda NUMERIC,
    PRIMARY KEY (symbol, date)
);

-- monthly point-in-time fundamentals snapshot (stamp the date you captured it)
CREATE TABLE IF NOT EXISTS fundamentals_snapshot (
    symbol         TEXT REFERENCES securities,
    captured_on    DATE,    -- when WE snapshotted it (the PIT stamp)
    period_end     DATE,    -- the fiscal period the numbers refer to
    roce           NUMERIC,
    roe            NUMERIC,
    debt_equity    NUMERIC,
    interest_cover NUMERIC,
    cfo            NUMERIC,
    pat            NUMERIC,
    eps            NUMERIC,
    book_value     NUMERIC,
    PRIMARY KEY (symbol, captured_on, period_end)
);

-- as-of index membership (so past universes are correct, not survivorship-biased)
CREATE TABLE IF NOT EXISTS universe_membership (
    symbol     TEXT REFERENCES securities,
    index_name TEXT,        -- e.g. 'NIFTY500'
    from_date  DATE,
    to_date    DATE         -- NULL = still a member
);

-- every basket's output, in the standard schema (the allocator's input contract)
CREATE TABLE IF NOT EXISTS basket_holdings (
    basket TEXT,
    as_of  DATE,
    symbol TEXT REFERENCES securities,
    weight NUMERIC,
    score  NUMERIC,
    PRIMARY KEY (basket, as_of, symbol)
);
