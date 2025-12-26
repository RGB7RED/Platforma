# Environment variables

Use `backend/.env.example` as the template for local development and production configuration.

## Variables

### ENVIRONMENT
- **Purpose:** Controls runtime defaults (e.g., CORS warnings and file persistence behavior).
- **Example:** `ENVIRONMENT=development`
- **Required in production?:** Yes
- **Notes:** Use `production` in deployed environments.

### PORT
- **Purpose:** HTTP port the API binds to.
- **Example:** `PORT=8000`
- **Required in production?:** Yes
- **Notes:** Railway injects `PORT`; locally defaults to 8000.

### DATABASE_URL
- **Purpose:** Enables Postgres persistence for tasks.
- **Example:** `DATABASE_URL=postgresql://user:pass@host:5432/dbname`
- **Required in production?:** Yes
- **Notes:** When unset, the backend uses in-memory storage.

### SECRET_KEY
- **Purpose:** Secret used for signing/auth features.
- **Example:** `SECRET_KEY=change-me`
- **Required in production?:** Yes
- **Notes:** Use a strong, unique value; never commit real secrets.

### ALLOWED_ORIGINS
- **Purpose:** CORS allowlist for browser clients.
- **Example:** `ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000,https://web.telegram.org,https://telegram.org`
- **Required in production?:** Yes
- **Notes:** Comma-separated list; `*` is ignored. An empty list in production blocks all cross-origin requests.

### ENABLE_FILE_PERSISTENCE
- **Purpose:** Toggle file persistence to local disk.
- **Example:** `ENABLE_FILE_PERSISTENCE=true`
- **Required in production?:** No
- **Notes:** Defaults to enabled outside production; defaults to disabled in production.

### TELEGRAM_TOKEN
- **Purpose:** Auth token for the Telegram bot.
- **Example:** `TELEGRAM_TOKEN=REDACTED`
- **Required in production?:** No (Yes if the bot is enabled)
- **Notes:** If unset, the bot will not start.

### WEB_APP_URL
- **Purpose:** Base URL for the Telegram Web App.
- **Example:** `WEB_APP_URL=http://localhost:3000`
- **Required in production?:** No (Yes if the bot is enabled)
- **Notes:** Used to build deep links from the bot.
