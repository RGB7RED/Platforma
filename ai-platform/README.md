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

## Auth bootstrap & registration

- To create the first admin user automatically, set `BOOTSTRAP_ADMIN_ENABLED=true` along with
  `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` (requires `DATABASE_URL` and
  `AUTH_MODE=auth` or `AUTH_MODE=hybrid`).
- To allow public sign-ups, set `PUBLIC_REGISTRATION_ENABLED=true` and use `/auth/register`.

## Container persistence v1 (read-only)

When `DATABASE_URL` is configured, the backend stores container events, artifacts, and state in
Postgres. Read-only endpoints:

- `GET /api/tasks/{task_id}/events?limit=200&order=desc`
- `GET /api/tasks/{task_id}/artifacts?type=&limit=200&order=desc`
- `GET /api/tasks/{task_id}/state`

## Troubleshooting

- **ModuleNotFoundError:** confirm Railway root directory is `ai-platform/backend`.
- **Port binding errors:** ensure the start command uses `$PORT`.
- **Database connection errors:** verify `DATABASE_URL` and network access to the database.
