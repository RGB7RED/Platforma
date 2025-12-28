# Environment variables (P0)

This document covers only the environment variables required for the P0 local and production setup.

## Local quickstart

```bash
docker compose up --build
```

Open `http://localhost` in your browser.

## Variables

### PORT
- **Purpose:** Port to bind the backend server.
- **Example:** `PORT=8080`
- **Required in production?:** Yes (Railway assigns this value)
- **Notes:** Defaults to `8080` when unset. Used by `backend/run.py` to bind Uvicorn.

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
- **Notes:** Defaults to `mock` when unset. The OpenAI provider enforces JSON mode and a strict
  system instruction to return JSON-only output for reliable parsing.

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

### LLM_MAX_TOKENS_CODER
- **Purpose:** Cap on output tokens for the coder agent (falls back to `LLM_MAX_TOKENS`).
- **Example:** `LLM_MAX_TOKENS_CODER=800`
- **Required in production?:** Optional
- **Notes:** Defaults to `LLM_MAX_TOKENS` when unset.

### LLM_CHUNKING_ENABLED
- **Purpose:** Toggle chunked JSON output for large file generation.
- **Example:** `LLM_CHUNKING_ENABLED=1`
- **Required in production?:** Optional
- **Notes:** Defaults to enabled (`1`).

### LLM_MAX_CHUNKS
- **Purpose:** Max number of JSON chunks allowed for a single file generation.
- **Example:** `LLM_MAX_CHUNKS=8`
- **Required in production?:** Optional
- **Notes:** Defaults to 8.

### LLM_MAX_FILE_CHARS
- **Purpose:** Hard cap on total characters generated per file (prevents runaway costs).
- **Example:** `LLM_MAX_FILE_CHARS=12000`
- **Required in production?:** Optional
- **Notes:** Defaults to 12,000.

### LLM_RESPONSE_FORMAT
- **Purpose:** Controls OpenAI JSON enforcement mode.
- **Example:** `LLM_RESPONSE_FORMAT=json_object` or `LLM_RESPONSE_FORMAT=json_schema`
- **Required in production?:** Optional
- **Notes:** Defaults to `json_object`. When set to `json_schema`, the provider sends structured
  outputs JSON schema (recommended for models that support Structured Outputs such as
  `gpt-4o-mini` or `gpt-4o-2024-08-06`).

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

### LLM_MAX_CALLS_PER_TASK
- **Purpose:** Hard cap on total LLM calls per task execution.
- **Example:** `LLM_MAX_CALLS_PER_TASK=10`
- **Required in production?:** Optional
- **Notes:** Defaults to 10. When exceeded, tasks fail fast with `llm_budget_exhausted`.

### LLM_MAX_RETRIES_PER_STEP
- **Purpose:** Cap on corrective retries per step when an LLM response is invalid.
- **Example:** `LLM_MAX_RETRIES_PER_STEP=1`
- **Required in production?:** Optional
- **Notes:** Defaults to 1. Applies to JSON parsing retries.

### LLM_MAX_TOTAL_TOKENS_PER_TASK
- **Purpose:** Max total LLM tokens per task (input + output) to prevent runaway usage.
- **Example:** `LLM_MAX_TOTAL_TOKENS_PER_TASK=5000`
- **Required in production?:** Optional
- **Notes:** Defaults to 5000. When exceeded, tasks fail fast with `llm_budget_exceeded`.

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

### BOOTSTRAP_ADMIN_ENABLED
- **Purpose:** Automatically creates the first admin user on startup.
- **Example:** `BOOTSTRAP_ADMIN_ENABLED=true`
- **Required in production?:** Optional
- **Notes:** Requires `DATABASE_URL` and `AUTH_MODE=auth` or `AUTH_MODE=hybrid`. When enabled,
  `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` must be provided.

### BOOTSTRAP_ADMIN_EMAIL
- **Purpose:** Email address for the bootstrap admin user.
- **Example:** `BOOTSTRAP_ADMIN_EMAIL=admin@example.com`
- **Required in production?:** Required if `BOOTSTRAP_ADMIN_ENABLED=true`
- **Notes:** The email is normalized to lowercase before insertion.

### BOOTSTRAP_ADMIN_PASSWORD
- **Purpose:** Password for the bootstrap admin user.
- **Example:** `BOOTSTRAP_ADMIN_PASSWORD=ChangeMe123!`
- **Required in production?:** Required if `BOOTSTRAP_ADMIN_ENABLED=true`
- **Notes:** Stored as a bcrypt hash in Postgres. Bcrypt only uses the first 72 bytes of the
  password, so keep this value under 72 bytes and prefer ASCII to avoid multi-byte surprises.

### PUBLIC_REGISTRATION_ENABLED
- **Purpose:** Allows anyone to register with `/auth/register`.
- **Example:** `PUBLIC_REGISTRATION_ENABLED=true`
- **Required in production?:** Optional
- **Notes:** When disabled, registration requires valid invite tokens (see `INVITE_REGISTRATION_ENABLED`).

### INVITE_REGISTRATION_ENABLED
- **Purpose:** Allows registration with invite tokens instead of open sign-ups.
- **Example:** `INVITE_REGISTRATION_ENABLED=true`
- **Required in production?:** Optional
- **Notes:** Requires `INVITE_TOKEN_SECRET` when enabled.

### INVITE_TOKEN_SECRET
- **Purpose:** HMAC/JWT signing secret for invite tokens.
- **Example:** `INVITE_TOKEN_SECRET=super-long-random-string`
- **Required in production?:** Required if `INVITE_REGISTRATION_ENABLED=true`
- **Notes:** Invite tokens are validated as JWTs; include an `email` claim to bind a token to a
  specific recipient.

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

### AUTH_ACTION_TOKEN_SECRET
- **Purpose:** HMAC secret for hashing email verification and password reset tokens.
- **Example:** `AUTH_ACTION_TOKEN_SECRET=another-long-random-string`
- **Required in production?:** Recommended
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

### AUTH_EMAIL_VERIFY_TTL_HOURS
- **Purpose:** Lifetime in hours for email verification tokens.
- **Example:** `AUTH_EMAIL_VERIFY_TTL_HOURS=24`
- **Required in production?:** Optional
- **Notes:** Defaults to 24 hours.

### AUTH_PASSWORD_RESET_TTL_HOURS
- **Purpose:** Lifetime in hours for password reset tokens.
- **Example:** `AUTH_PASSWORD_RESET_TTL_HOURS=2`
- **Required in production?:** Optional
- **Notes:** Defaults to 2 hours.

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

### GOOGLE_CLIENT_ID
- **Purpose:** Google OAuth client ID for "Sign in with Google".
- **Example:** `GOOGLE_CLIENT_ID=1234567890-abcdefg.apps.googleusercontent.com`
- **Required in production?:** Yes (when enabling Google OAuth)
- **Notes:** Configure this in the Google Cloud Console OAuth credentials.

### GOOGLE_CLIENT_SECRET
- **Purpose:** Google OAuth client secret for exchanging authorization codes.
- **Example:** `GOOGLE_CLIENT_SECRET=your-google-client-secret`
- **Required in production?:** Yes (when enabling Google OAuth)
- **Notes:** Keep this secret secure; rotate if compromised.

### GOOGLE_REDIRECT_URL
- **Purpose:** Redirect URL registered with Google that points to the backend callback.
- **Example:** `GOOGLE_REDIRECT_URL=https://your-domain.com/auth/google/callback`
- **Required in production?:** Yes (when enabling Google OAuth)
- **Notes:** Must exactly match the authorized redirect URI in Google Cloud Console.

### PUBLIC_BASE_URL
- **Purpose:** Base URL used to generate email verification and password reset links.
- **Example:** `PUBLIC_BASE_URL=https://your-domain.com`
- **Required in production?:** Recommended
- **Notes:** Defaults to `http://localhost` when unset.

### SMTP_HOST
- **Purpose:** SMTP server host for sending auth emails.
- **Example:** `SMTP_HOST=smtp.mailgun.org`
- **Required in production?:** Recommended
- **Notes:** When unset, emails are logged instead of sent.

### SMTP_PORT
- **Purpose:** SMTP server port for sending auth emails.
- **Example:** `SMTP_PORT=587`
- **Required in production?:** Optional
- **Notes:** Defaults to 25. Port 465 uses implicit TLS.

### SMTP_USER
- **Purpose:** SMTP username for sending auth emails.
- **Example:** `SMTP_USER=postmaster@your-domain.com`
- **Required in production?:** Optional
- **Notes:** Used with `SMTP_PASS` for authenticated SMTP.

### SMTP_PASS
- **Purpose:** SMTP password for sending auth emails.
- **Example:** `SMTP_PASS=super-secret`
- **Required in production?:** Optional
- **Notes:** Used with `SMTP_USER` for authenticated SMTP.

### SMTP_FROM
- **Purpose:** Sender address for auth emails.
- **Example:** `SMTP_FROM=no-reply@your-domain.com`
- **Required in production?:** Optional
- **Notes:** Defaults to `SMTP_USER` or `no-reply@localhost` when unset.

### Clarification loop endpoints
- **Purpose:** `/api/tasks/{task_id}/questions`, `/input`, and `/resume` use the same API key enforcement.
- **Example:** No additional environment variables.
- **Required in production?:** No
- **Notes:** Uses `APP_API_KEY` when set.
