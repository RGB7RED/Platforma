# Environment variables (P0)

This document covers only the environment variables required for the P0 local and production setup.

## Local quickstart

```bash
docker compose up --build
```

Open `http://localhost` in your browser.

## Variables

### ALLOWED_ORIGINS
- **Purpose:** CORS allowlist for browser clients.
- **Example:** `ALLOWED_ORIGINS=http://localhost,https://your-domain.com`
- **Required in production?:** Yes
- **Notes:** Comma-separated list. Values are trimmed and empty entries are ignored.

### DATABASE_URL
- **Purpose:** Enables Postgres persistence for tasks (required for DB-backed task files/snapshots).
- **Example:** `DATABASE_URL=postgresql://user:pass@host:5432/dbname`
- **Required in production?:** Optional (required to persist tasks/files across restarts)
- **Notes:** When unset, the backend uses in-memory storage and local JSON file persistence only.

### ENABLE_FILE_PERSISTENCE
- **Purpose:** Toggle file persistence to local disk.
- **Example:** `ENABLE_FILE_PERSISTENCE=true`
- **Required in production?:** Optional
- **Notes:** Defaults to enabled outside production; defaults to disabled in production.

### MAX_TASK_BYTES
- **Purpose:** Max total bytes stored per task in Postgres file persistence.
- **Example:** `MAX_TASK_BYTES=52428800`
- **Required in production?:** Optional
- **Notes:** Defaults to 50MB. Exceeding this limit will fail the task with a clear error.

### MAX_TASK_FILES
- **Purpose:** Max number of files stored per task in Postgres file persistence.
- **Example:** `MAX_TASK_FILES=2000`
- **Required in production?:** Optional
- **Notes:** Defaults to 2000. Exceeding this limit will fail the task with a clear error.

### TASK_TTL_DAYS
- **Purpose:** Optional retention window (days) for cleaning up old tasks in Postgres.
- **Example:** `TASK_TTL_DAYS=30`
- **Required in production?:** Optional
- **Notes:** No automatic cleanup is scheduled. Use this value when running a manual cleanup
  script (e.g., delete tasks older than `TASK_TTL_DAYS` along with related rows).

### CODEX_PATH
- **Purpose:** Override the JSON codex loaded by the orchestrator.
- **Example:** `CODEX_PATH=ai-platform/backend/app/codex.json`
- **Required in production?:** Optional
- **Notes:** Defaults to `backend/app/codex.json` relative to the backend source.
