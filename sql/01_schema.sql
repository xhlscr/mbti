-- ============================================================================
-- 01_schema.sql · MBTI 测试站建表脚本（PostgreSQL 15 / 16）
-- 幂等：可重复执行。执行顺序：01 → 02 → 03
-- ============================================================================

-- 题库：bank → version → question --------------------------------------------
CREATE TABLE IF NOT EXISTS question_bank (
    id                  BIGSERIAL    PRIMARY KEY,
    slug                VARCHAR(64)  NOT NULL UNIQUE,
    name                VARCHAR(64)  NOT NULL,
    current_version_id  BIGINT
);

CREATE TABLE IF NOT EXISTS bank_version (
    id              BIGSERIAL    PRIMARY KEY,
    bank_id         BIGINT       NOT NULL REFERENCES question_bank(id),
    version         INTEGER      NOT NULL,
    status          VARCHAR(16)  NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'published', 'archived')),
    question_count  INTEGER      NOT NULL DEFAULT 0,
    content_hash    VARCHAR(64)  NOT NULL DEFAULT '',
    published_at    TIMESTAMPTZ,
    UNIQUE (bank_id, version)
);

CREATE INDEX IF NOT EXISTS ix_bank_version_bank_status ON bank_version (bank_id, status);

CREATE TABLE IF NOT EXISTS question (
    id              BIGSERIAL    PRIMARY KEY,
    bank_version_id BIGINT       NOT NULL REFERENCES bank_version(id) ON DELETE CASCADE,
    code            VARCHAR(32)  NOT NULL,
    dim             VARCHAR(2)   NOT NULL CHECK (dim IN ('EI', 'SN', 'TF', 'JP')),
    type            VARCHAR(32)  NOT NULL,
    stem            TEXT         NOT NULL,
    payload         JSONB        NOT NULL,
    tags            TEXT[]       NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_question_version_code ON question (bank_version_id, code);
CREATE INDEX IF NOT EXISTS ix_question_dim  ON question (dim);
CREATE INDEX IF NOT EXISTS ix_question_tags ON question USING gin (tags);

-- 测试会话与作答 -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS test_session (
    id              UUID         PRIMARY KEY,
    bank_version_id BIGINT       NOT NULL REFERENCES bank_version(id),
    question_ids    BIGINT[]     NOT NULL,
    seed            BIGINT       NOT NULL DEFAULT 0,
    client          TEXT,
    started_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ  NOT NULL,
    finished_at     TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS answer (
    session_id  UUID         NOT NULL REFERENCES test_session(id) ON DELETE CASCADE,
    question_id BIGINT       NOT NULL,
    value       JSONB        NOT NULL,
    answered_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, question_id)
);

CREATE TABLE IF NOT EXISTS result (
    id          BIGSERIAL    PRIMARY KEY,
    session_id  UUID         NOT NULL UNIQUE REFERENCES test_session(id) ON DELETE CASCADE,
    share_id    VARCHAR(32)  NOT NULL UNIQUE,
    code        CHAR(4)      NOT NULL,
    ratios      JSONB        NOT NULL,
    answered    INTEGER      NOT NULL DEFAULT 0,
    total       INTEGER      NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_result_share ON result (share_id);

-- 历史名人（阶段二） ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS celebrity (
    id              VARCHAR(64)  PRIMARY KEY,
    name            VARCHAR(64)  NOT NULL,
    alias           VARCHAR(64),
    era             VARCHAR(64),
    region          VARCHAR(64),
    field           VARCHAR(64),
    type            VARCHAR(4)   NOT NULL,
    basis           VARCHAR(16)  NOT NULL DEFAULT 'inferred',
    confidence      REAL         NOT NULL DEFAULT 0.5,
    vector          JSONB        NOT NULL,
    traits          JSONB        NOT NULL DEFAULT '[]'::jsonb,
    why             TEXT         NOT NULL DEFAULT '',
    quote           TEXT,
    quote_source    VARCHAR(128),
    note            TEXT,
    portrait        JSONB        NOT NULL DEFAULT '{}'::jsonb,
    sources         JSONB        NOT NULL DEFAULT '[]'::jsonb,
    status          VARCHAR(16)  NOT NULL DEFAULT 'published',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_celebrity_type        ON celebrity (type);
CREATE INDEX IF NOT EXISTS ix_celebrity_type_status ON celebrity (type, status);
CREATE INDEX IF NOT EXISTS ix_celebrity_name        ON celebrity (name);

CREATE TABLE IF NOT EXISTS result_celebrity (
    id                BIGSERIAL    PRIMARY KEY,
    result_id         VARCHAR(32)  NOT NULL,
    algorithm_version VARCHAR(16)  NOT NULL DEFAULT 'v1',
    primary_id        VARCHAR(64),
    primary_score     REAL,
    payload           JSONB        NOT NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_result_celebrity_result ON result_celebrity (result_id);
