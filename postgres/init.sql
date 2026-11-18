CREATE TABLE scores (
    transaction_id TEXT PRIMARY KEY,
    score DOUBLE PRECISION NOT NULL CHECK (score BETWEEN 0 AND 1),
    fraud_flag SMALLINT NOT NULL CHECK (fraud_flag IN (0, 1)),
    model_version TEXT NOT NULL,
    transaction_time TIMESTAMPTZ NOT NULL,
    scored_at TIMESTAMPTZ NOT NULL,
    written_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    amt DOUBLE PRECISION NOT NULL CHECK (amt >= 0),
    us_state TEXT NOT NULL,
    merch TEXT NOT NULL,
    cat_id TEXT NOT NULL
);
CREATE INDEX scores_scored_at_idx ON scores (scored_at DESC, transaction_id);
CREATE INDEX scores_segments_idx ON scores (us_state, merch, scored_at);
CREATE ROLE grafana_reader LOGIN PASSWORD 'grafana_readonly';
GRANT CONNECT ON DATABASE fraud TO grafana_reader;
GRANT USAGE ON SCHEMA public TO grafana_reader;
GRANT SELECT ON scores TO grafana_reader;
