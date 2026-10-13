-- Databases with legacy encrypted credentials must be converted before adoption.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
        WHERE table_schema=current_schema() AND table_name='science_agent_s3_credentials'
          AND column_name='encrypted_keys') THEN
        RAISE EXCEPTION 'Convert legacy S3 credentials before initializing migration history.';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS science_agent_users (
    subject text PRIMARY KEY,
    tenant_id text NOT NULL,
    username text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen timestamptz
);
CREATE TABLE IF NOT EXISTS science_agent_sessions (
    id uuid PRIMARY KEY,
    owner_subject text REFERENCES science_agent_users(subject),
    source text NOT NULL,
    data jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (data->>'id' = id::text),
    CHECK (data->'metadata'->>'source' = source),
    CHECK (COALESCE(data->'metadata'->>'user_id', '') = COALESCE(owner_subject, ''))
);
CREATE INDEX IF NOT EXISTS science_agent_sessions_owner_updated
    ON science_agent_sessions (owner_subject, updated_at DESC);
CREATE TABLE IF NOT EXISTS science_agent_attachments (
    id uuid PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES science_agent_sessions(id) ON DELETE CASCADE,
    filename text NOT NULL,
    content_type text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    sha256 text NOT NULL CHECK (length(sha256) = 64),
    content bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, filename),
    CHECK (octet_length(content) = size_bytes)
);
CREATE TABLE IF NOT EXISTS science_agent_s3_credentials (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_subject text NOT NULL REFERENCES science_agent_users(subject) ON DELETE CASCADE,
    name text NOT NULL,
    endpoint text NOT NULL,
    bucket text NOT NULL,
    region text NOT NULL,
    access_key_id text NOT NULL,
    secret_access_key text NOT NULL,
    is_selected boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE science_agent_s3_credentials ADD COLUMN IF NOT EXISTS id uuid NOT NULL DEFAULT gen_random_uuid();
ALTER TABLE science_agent_s3_credentials ADD COLUMN IF NOT EXISTS name text NOT NULL DEFAULT 'Imported S3';
ALTER TABLE science_agent_s3_credentials ADD COLUMN IF NOT EXISTS is_selected boolean NOT NULL DEFAULT false;
ALTER TABLE science_agent_s3_credentials ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

-- Preserve the previous user-owned credential and its selection during migration.
DO $$
DECLARE legacy_primary_key text;
BEGIN
    SELECT conname INTO legacy_primary_key FROM pg_constraint
    WHERE conrelid='science_agent_s3_credentials'::regclass AND contype='p'
      AND pg_get_constraintdef(oid)='PRIMARY KEY (owner_subject)';
    IF legacy_primary_key IS NOT NULL THEN
        EXECUTE format('ALTER TABLE science_agent_s3_credentials DROP CONSTRAINT %I', legacy_primary_key);
        ALTER TABLE science_agent_s3_credentials ADD PRIMARY KEY (id);
        UPDATE science_agent_s3_credentials SET is_selected=true;
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS science_agent_s3_credentials_owner_name
    ON science_agent_s3_credentials(owner_subject, name);
CREATE UNIQUE INDEX IF NOT EXISTS science_agent_s3_credentials_selected
    ON science_agent_s3_credentials(owner_subject) WHERE is_selected;
