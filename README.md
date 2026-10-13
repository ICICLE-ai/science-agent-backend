# Science Agent Backend (FastAPI)

Initial migration: cookie authentication, PostgreSQL conversations and attachments,
WebSocket conversation restore/commands/progress, and the remote agent pod.

## Run

Configure `.env` using `.env.example`, then:

```bash
uv sync
uv run uvicorn science_agent_backend.main:app --host 127.0.0.1 --port 8000
```

Use one worker in this initial version. The frontend's existing `/api` proxy
targets port 8000. API documentation is at `/docs`.
`/health` is the CI/CD health endpoint. `/healthcheck` remains available for
existing clients. Both report application availability, not remote pod readiness.

## Source Layout

```text
src/science_agent_backend/
    __init__.py
    main.py                  # FastAPI app, lifespan, middleware, router wiring
    api/
        __init__.py
        health.py            # /health and /healthcheck
        account.py           # Tapis account and S3 credential settings
        sessions.py          # Conversation creation, listing, validation, deletion
        files.py             # PostgreSQL attachment upload/download/deletion
        execution.py         # Agent WebSocket commands and progress
        tasks.py             # Conversation detail and gallery compatibility
        storage.py           # Existing S3 browser endpoint (currently 501)
        dependencies.py      # Shared authenticated-user dependency
    auth.py
    config.py
    database.py
    agent_runtime.py
    runtime_state.py         # Shared active-request state
    pod_files.py
    pod_receiver.py
    pod_terminal.py
    s3_credentials.py
    migrations/
        __init__.py          # Migration runner and history checks
        __main__.py          # Optional migration CLI
        0001_initial_schema.sql
    skills/                  # Instructions and scripts sent to the remote pod
```

The installed package includes the migration SQL and skill resources. `uv build`
creates the deployment wheel. Production configuration comes from environment
variables; local development also loads the project-root `.env`.

## Database Migrations

Set `DATABASE_URL` when the deployment's PostgreSQL connection details become
available. The backend applies migrations during startup before accepting API
requests. The connection user needs permission to create and alter the service's
tables in the configured schema.

On first connection, if `science_agent_migration_history` does not exist, the
backend creates it, applies `0001_initial_schema.sql`, and records version **1**.
Each history row contains `version`, `name`, `checksum`, and `applied_at`.
Existing development tables without migration history are adopted by this
initial migration; their data is preserved.

On later startups, recorded versions are checked and only pending migrations
are applied. Schema changes and their history rows commit together; failure
rolls back that initialization attempt. A PostgreSQL advisory lock ensures that
concurrent backend instances initialize the DB only once.

For a future schema change, add `0002_description.sql`, then `0003_description.sql`,
and so on under `src/science_agent_backend/migrations/`. Keep applied SQL files
unchanged; their SHA-256 checksums are verified. The runner owns the transaction,
so migration files must not contain BEGIN, COMMIT, or ROLLBACK commands.

Optional manual application and history display:

```bash
uv run python -m science_agent_backend.migrations
```

Migration checks use isolated temporary schemas in the configured test database:

```bash
SCIENCE_AGENT_TEST_DATABASE=1 uv run pytest -q src/science_agent_backend/test/test_migrations.py
```

The local `.env` was initialized privately from existing development DB and pod
settings. No runtime imports from the old backend are required. Existing database
tables and conversations are retained. Existing S3 credentials are migrated to
named entries and retain their previous selection.

## Isolated checks

```bash
uv run pytest -q
```

These checks mock authentication, persistence, and transport; they are not proof
of real Tapis/pod connectivity. Real integration results are reported separately.

To explicitly run the attachment lifecycle checks against the configured
PostgreSQL database (temporary test records are removed afterward):

```bash
SCIENCE_AGENT_TEST_DATABASE=1 uv run pytest -q src/science_agent_backend/test/test_attachments.py
```

The multiple-credential lifecycle and owner isolation checks can also be run
against the configured DB with `SCIENCE_AGENT_TEST_DATABASE=1 uv run pytest -q
src/science_agent_backend/test/test_s3_credentials.py`. They create temporary test accounts and clean them up.
