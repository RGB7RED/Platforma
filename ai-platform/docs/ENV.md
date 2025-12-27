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

### WORKSPACE_ROOT
- **Purpose:** Base directory for per-task workspaces on disk.
- **Example:** `WORKSPACE_ROOT=data/workspaces`
- **Required in production?:** Optional
- **Notes:** Defaults to `data/workspaces` when unset.

### WORKSPACE_TTL_DAYS
- **Purpose:** Cleanup threshold (days) for removing old task workspaces on startup.
- **Example:** `WORKSPACE_TTL_DAYS=7`
- **Required in production?:** Optional
- **Notes:** When unset or `0`, workspaces are retained.

### ALLOWED_COMMANDS
- **Purpose:** Allowlist for safe command runner executables.
- **Example:** `ALLOWED_COMMANDS=ruff,pytest,python`
- **Required in production?:** Optional
- **Notes:** Defaults to `ruff,pytest,python,python3` when unset.

### COMMAND_TIMEOUT_SECONDS
- **Purpose:** Timeout (seconds) for safe command execution.
- **Example:** `COMMAND_TIMEOUT_SECONDS=60`
- **Required in production?:** Optional
- **Notes:** Defaults to 60 seconds.

### COMMAND_MAX_OUTPUT_BYTES
- **Purpose:** Max output bytes captured per stdout/stderr stream.
- **Example:** `COMMAND_MAX_OUTPUT_BYTES=20000`
- **Required in production?:** Optional
- **Notes:** Defaults to 20KB.

### CODEX_PATH
- **Purpose:** Override the JSON codex loaded by the orchestrator.
- **Example:** `CODEX_PATH=ai-platform/backend/app/codex.json`
- **Required in production?:** Optional
- **Notes:** Defaults to `backend/app/codex.json` relative to the backend source.

### LLM_PROVIDER
- **Purpose:** Selects the LLM backend implementation.
- **Example:** `LLM_PROVIDER=mock` or `LLM_PROVIDER=openai`
- **Required in production?:** Yes (set to `openai` for real calls, `mock` for offline)
- **Notes:** Defaults to `mock` when unset.

### LLM_MODEL
- **Purpose:** Model identifier passed to the provider.
- **Example:** `LLM_MODEL=gpt-4o-mini`
- **Required in production?:** Yes (when using a real provider)
- **Notes:** Used by the provider selected in `LLM_PROVIDER`.

### LLM_API_KEY
- **Purpose:** API key for the configured provider.
- **Example:** `LLM_API_KEY=sk-...`
- **Required in production?:** Yes (when using `LLM_PROVIDER=openai`)
- **Notes:** Never store this value in artifacts or output files.

### LLM_MAX_TOKENS
- **Purpose:** Cap on output tokens returned by the provider.
- **Example:** `LLM_MAX_TOKENS=2048`
- **Required in production?:** Optional
- **Notes:** Defaults to 1024.

### LLM_TIMEOUT_SECONDS
- **Purpose:** Hard timeout for provider requests.
- **Example:** `LLM_TIMEOUT_SECONDS=30`
- **Required in production?:** Optional
- **Notes:** Defaults to 30 seconds. Requests are retried up to two times on transient errors.

### LLM_TEMPERATURE
- **Purpose:** Sampling temperature used by the provider.
- **Example:** `LLM_TEMPERATURE=0.2`
- **Required in production?:** Optional
- **Notes:** Defaults to 0.2.

### APP_API_KEY
- **Purpose:** Require an API key for all task endpoints (including rerun review).
- **Example:** `APP_API_KEY=super-secret-token`
- **Required in production?:** Recommended
- **Notes:** Clients must send `X-API-Key` with the configured value.
