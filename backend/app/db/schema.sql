-- Idempotent schema. Applied on API startup and by the ingest job.
-- {EMBED_DIM} is substituted from settings (768 for nomic-embed-text).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------- Conversations ----------
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    display_name  TEXT,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT 'New chat',
    provider    TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_user_updated_idx ON sessions (user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    route       TEXT,                                   -- qa | essay | artifact | no_answer
    provider    TEXT,
    model       TEXT,
    sources     JSONB NOT NULL DEFAULT '[]'::jsonb,     -- citations shown with the answer
    meta        JSONB NOT NULL DEFAULT '{}'::jsonb,     -- latency, retrieval stats, engine, errors
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_session_created_idx ON messages (session_id, created_at);

CREATE TABLE IF NOT EXISTS artifacts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    message_id  UUID REFERENCES messages(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL CHECK (kind IN ('markdown', 'html')),
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    sanitizer   JSONB NOT NULL DEFAULT '{}'::jsonb,     -- what was stripped and why
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS artifacts_session_idx ON artifacts (session_id, created_at DESC);

-- ---------- Knowledge base ----------
CREATE TABLE IF NOT EXISTS episodes (
    id            SERIAL PRIMARY KEY,
    slug          TEXT UNIQUE NOT NULL,
    guest         TEXT,
    title         TEXT NOT NULL,
    youtube_url   TEXT,
    publish_date  DATE,
    source_path   TEXT NOT NULL,
    source_url    TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    chunk_count   INT NOT NULL DEFAULT 0,
    embedded      BOOLEAN NOT NULL DEFAULT false,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunks (
    id             BIGSERIAL PRIMARY KEY,
    episode_id     INT NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    ord            INT NOT NULL,
    speakers       TEXT[] NOT NULL DEFAULT '{}',
    start_ts       TEXT,
    start_seconds  INT,
    text           TEXT NOT NULL,
    tsv            TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    embedding      VECTOR({EMBED_DIM}),
    UNIQUE (episode_id, ord)
);
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING GIN (tsv);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id           SERIAL PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    status       TEXT NOT NULL DEFAULT 'running',
    stats        JSONB NOT NULL DEFAULT '{}'::jsonb
);
