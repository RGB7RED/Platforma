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

2. Configure environment variables using the template in
   [`backend/.env.example`](backend/.env.example). See
   [`docs/ENV.md`](docs/ENV.md) for details.

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

Required environment variables are documented in
[`docs/ENV.md`](docs/ENV.md) with examples and production requirements.

## Environment configuration

- Template: [`backend/.env.example`](backend/.env.example)
- Reference: [`docs/ENV.md`](docs/ENV.md)

## Troubleshooting

- **ModuleNotFoundError:** confirm Railway root directory is `ai-platform/backend`.
- **Port binding errors:** ensure the start command uses `$PORT`.
- **Database connection errors:** verify `DATABASE_URL` and network access to the database.
