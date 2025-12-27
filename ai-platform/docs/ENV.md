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
- **Purpose:** Enables Postgres persistence for tasks.
- **Example:** `DATABASE_URL=postgresql://user:pass@host:5432/dbname`
- **Required in production?:** Optional
- **Notes:** When unset, the backend uses in-memory storage.

### ENABLE_FILE_PERSISTENCE
- **Purpose:** Toggle file persistence to local disk.
- **Example:** `ENABLE_FILE_PERSISTENCE=true`
- **Required in production?:** Optional
- **Notes:** Defaults to enabled outside production; defaults to disabled in production.

### CODEX_PATH
- **Purpose:** Override the JSON codex loaded by the orchestrator.
- **Example:** `CODEX_PATH=ai-platform/backend/app/codex.json`
- **Required in production?:** Optional
- **Notes:** Defaults to `backend/app/codex.json` relative to the backend source.
