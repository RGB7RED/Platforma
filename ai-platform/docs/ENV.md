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

### MAX_CONCURRENT_TASKS
- **Purpose:** Cap on concurrent task execution slots.
- **Example:** `MAX_CONCURRENT_TASKS=4`
- **Required in production?:** Optional
- **Notes:** Defaults to 4. Tasks beyond the limit remain in `queued` status until a slot frees up.

### RATE_LIMIT_CREATE_TASKS_PER_MIN
- **Purpose:** Per-API-key rate limit for task creation.
- **Example:** `RATE_LIMIT_CREATE_TASKS_PER_MIN=10`
- **Required in production?:** Optional
- **Notes:** Defaults to 0 (disabled). Returns HTTP 429 with `Retry-After` when exceeded.

### RATE_LIMIT_RERUN_REVIEW_PER_MIN
- **Purpose:** Per-API-key rate limit for `/api/tasks/{task_id}/rerun-review`.
- **Example:** `RATE_LIMIT_RERUN_REVIEW_PER_MIN=5`
- **Required in production?:** Optional
- **Notes:** Defaults to 0 (disabled). Returns HTTP 429 with `Retry-After` when exceeded.

### RATE_LIMIT_DOWNLOADS_PER_MIN
- **Purpose:** Per-API-key rate limit for task download endpoints.
- **Example:** `RATE_LIMIT_DOWNLOADS_PER_MIN=20`
- **Required in production?:** Optional
- **Notes:** Defaults to 0 (disabled). Returns HTTP 429 with `Retry-After` when exceeded.

### MAX_TOKENS_PER_DAY
- **Purpose:** Daily token cap (input + output) per API key.
- **Example:** `MAX_TOKENS_PER_DAY=200000`
- **Required in production?:** Optional
- **Notes:** Defaults to 0 (disabled). Enforced at task start and before each LLM call.

### MAX_COMMAND_RUNS_PER_DAY
- **Purpose:** Daily command execution cap per API key.
- **Example:** `MAX_COMMAND_RUNS_PER_DAY=200`
- **Required in production?:** Optional
- **Notes:** Defaults to 0 (disabled). Enforced at task start and before each LLM call.

### TASK_TTL_DAYS
- **Purpose:** Optional retention window (days) for cleaning up old tasks in Postgres.
- **Example:** `TASK_TTL_DAYS=30`
- **Required in production?:** Optional
- **Notes:** Defaults to 30. On startup, tasks/events/artifacts/files/snapshots older than the
  TTL are purged.

### WORKSPACE_ROOT
- **Purpose:** Base directory for per-task workspaces on disk.
- **Example:** `WORKSPACE_ROOT=data/workspaces`
- **Required in production?:** Optional
- **Notes:** Defaults to `data/workspaces` when unset.

### WORKSPACE_TTL_DAYS
- **Purpose:** Cleanup threshold (days) for removing old task workspaces on startup.
- **Example:** `WORKSPACE_TTL_DAYS=7`
- **Required in production?:** Optional
- **Notes:** Defaults to `TASK_TTL_DAYS` when unset. When set to `0`, workspaces are retained.

### TEMPLATES_ROOT
- **Purpose:** Filesystem path for project templates used to seed new task workspaces.
- **Example:** `TEMPLATES_ROOT=ai-platform/templates`
- **Required in production?:** Optional
- **Notes:** Defaults to `ai-platform/templates` relative to the repo root.

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

### AUTH_MODE
- **Purpose:** Selects the authentication strategy for API access.
- **Example:** `AUTH_MODE=apikey` or `AUTH_MODE=hybrid` or `AUTH_MODE=auth`
- **Required in production?:** Recommended
- **Notes:** `apikey` enforces the existing API key flow, `auth` requires JWT access tokens, and
  `hybrid` allows either. In `auth`/`hybrid` mode, tasks created with access tokens are bound to the
  authenticated user ID (`owner_user_id`) and cannot be accessed via API keys.

### AUTH_JWT_SECRET
- **Purpose:** Secret key used to sign access tokens.
- **Example:** `AUTH_JWT_SECRET=super-long-random-string`
- **Required in production?:** Yes (when using `AUTH_MODE=auth` or `AUTH_MODE=hybrid`)
- **Notes:** Must be kept private. Rotating this secret invalidates existing access tokens.

### AUTH_REFRESH_TOKEN_SECRET
- **Purpose:** HMAC secret for hashing refresh tokens before storing them in the database.
- **Example:** `AUTH_REFRESH_TOKEN_SECRET=another-long-random-string`
- **Required in production?:** Yes (when using refresh tokens)
- **Notes:** Defaults to `AUTH_JWT_SECRET` if unset.

### AUTH_ACCESS_TOKEN_TTL_MINUTES
- **Purpose:** Access token lifetime in minutes.
- **Example:** `AUTH_ACCESS_TOKEN_TTL_MINUTES=15`
- **Required in production?:** Optional
- **Notes:** Defaults to 15 minutes.

### AUTH_REFRESH_TOKEN_TTL_DAYS
- **Purpose:** Refresh token lifetime in days.
- **Example:** `AUTH_REFRESH_TOKEN_TTL_DAYS=30`
- **Required in production?:** Optional
- **Notes:** Defaults to 30 days and is reset on each refresh rotation.

### AUTH_REFRESH_COOKIE_NAME
- **Purpose:** Cookie name for the refresh token.
- **Example:** `AUTH_REFRESH_COOKIE_NAME=refresh_token`
- **Required in production?:** Optional
- **Notes:** Defaults to `refresh_token`.

### AUTH_REFRESH_COOKIE_PATH
- **Purpose:** Cookie path for refresh token storage.
- **Example:** `AUTH_REFRESH_COOKIE_PATH=/auth`
- **Required in production?:** Optional
- **Notes:** Defaults to `/auth`.

### AUTH_REFRESH_COOKIE_DOMAIN
- **Purpose:** Cookie domain for refresh token storage.
- **Example:** `AUTH_REFRESH_COOKIE_DOMAIN=your-domain.com`
- **Required in production?:** Optional
- **Notes:** Leave unset to default to the current host.

### AUTH_REFRESH_COOKIE_SAMESITE
- **Purpose:** SameSite attribute for the refresh token cookie.
- **Example:** `AUTH_REFRESH_COOKIE_SAMESITE=lax`
- **Required in production?:** Optional
- **Notes:** Defaults to `lax`. Use `none` only when required and with HTTPS.

### AUTH_JWT_ISSUER
- **Purpose:** Optional issuer claim for access tokens.
- **Example:** `AUTH_JWT_ISSUER=ai-platform`
- **Required in production?:** Optional
- **Notes:** When set, tokens must include this issuer.

### AUTH_JWT_AUDIENCE
- **Purpose:** Optional audience claim for access tokens.
- **Example:** `AUTH_JWT_AUDIENCE=ai-platform-clients`
- **Required in production?:** Optional
- **Notes:** When set, tokens must include this audience.

### Clarification loop endpoints
- **Purpose:** `/api/tasks/{task_id}/questions`, `/input`, and `/resume` use the same API key enforcement.
- **Example:** No additional environment variables.
- **Required in production?:** No
- **Notes:** Uses `APP_API_KEY` when set.
