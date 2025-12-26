# AI Platform Backend

AI Platform is a FastAPI service that powers a Telegram Mini App for AI-assisted task execution.
It exposes HTTP APIs for task creation, status tracking, and file retrieval, with optional
Postgres persistence and Telegram bot integration.

## Local development (Python)

1. Install dependencies:

```bash
cd ai-platform/backend
pip install -r requirements.txt
```

2. Configure environment variables (example):

```bash
export ENVIRONMENT=development
export DATABASE_URL=postgresql://user:pass@localhost:5432/aiplatform
export SECRET_KEY=dev-secret-key-change-in-production
export ALLOWED_ORIGINS=http://localhost:3000
export ENABLE_FILE_PERSISTENCE=true
```

3. Start the API:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Local development (Docker Compose)

From the `ai-platform` directory:

```bash
docker compose up --build
```

The backend listens on `http://localhost:8000` and the health check is available at `/health`.

## Production (Railway)

- **Root directory:** `ai-platform/backend`
- **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Healthcheck:** `/health`

Required environment variables:

- `ENVIRONMENT=production`
- `DATABASE_URL`
- `SECRET_KEY`
- `ALLOWED_ORIGINS`
- `ENABLE_FILE_PERSISTENCE=false` (recommended)
- `TELEGRAM_TOKEN` (only if the bot is enabled)
- `WEB_APP_URL` (only if the bot is enabled)

## Troubleshooting

- **ModuleNotFoundError:** confirm Railway root directory is `ai-platform/backend`.
- **Port binding errors:** ensure the start command uses `$PORT`.
- **Database connection errors:** verify `DATABASE_URL` and network access to the database.
