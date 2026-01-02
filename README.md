# Platforma Repository Guide

Этот README описывает текущую структуру и работу платформы, чтобы ИИ мог
быстро понять, какие компоненты существуют, как они связаны и как протекают
основные процессы.

## 1. Общая картина

Платформа состоит из двух основных частей:

1. **AI Platform (Telegram Mini App + backend orchestration)** — находится в каталоге
   `ai-platform/` и включает FastAPI backend, статический frontend и инфраструктурные
   конфигурации для локального запуска/продакшена.
2. **Todo API (демо/шаблонный сервис)** — набор модулей `api/`, `models/`,
   `repositories/`, `services/` и `todo_main.py`, реализующий CRUD API для задач.

Корневая структура репозитория:

```
/README.md              <- этот файл
/ai-platform/           <- основная платформа
/workflows/ai-agent.yml <- workflow для CI/automation
```

## Troubleshooting: Final review failed (pytest/ruff)

**Что означает "Final review failed":** стадия reviewer завершилась ошибкой, потому что
инструментальные проверки (pytest/ruff) вернули неуспешный статус, и ревью-пайплайн
не смог подтвердить корректность изменений.

**Два частых источника проблем, показанные в этом репозитории:**

- **Pytest ImportError при collection** — отсутствует или переименован символ, который
  импортируют тесты (в нашем случае `TodoService`).
- **Ruff F401** — неиспользуемые импорты, которые блокируют lint-проверку.

**Какая конкретно правка сделана здесь:**

- Восстановлен/добавлен экспорт `TodoService` в `services/todo_service.py` и добавлены
  тонкие алиасы методов, ожидаемые тестами.
- Удалены неиспользуемые импорты, которые отмечал ruff.

**Проверка локально (скопировать и выполнить):**

```bash
python -m pytest -q
ruff check .
```

> Даже для задач, которые выглядят как "текстовые", ревью всё равно может упасть,
> если тесты/линтеры в репозитории сломаны (если платформа не реализует правило
> "skip review for non-code changes").

## 2. AI Platform: ключевые компоненты

### 2.1 Backend (FastAPI)

**Путь:** `ai-platform/backend/`

Главная точка входа — `ai-platform/backend/app/main.py`.

Основные задачи backend:

- предоставляет HTTP API для управления задачами и проектами;
- реализует WebSocket-канал для стриминга прогресса;
- управляет оркестрацией задач через набор LLM-агентов;
- хранит события, артефакты, состояние задач и проекты (в памяти и/или в БД);
- поддерживает авторизацию (API key и/или auth) + интеграцию с Telegram-ботом.

#### Важные модули backend

- `app/main.py`
  - FastAPI приложение, роуты, WebSocket, контроль задач.
  - Создание, резюмирование и мониторинг задач.
  - Хранилище `Storage` для runtime-данных.
- `app/orchestrator.py`
  - Класс `AIOrchestrator` — главный цикл выполнения задачи.
  - Загружает codex (`app/codex.json`), инициализирует роли (researcher/design/coder/reviewer).
- `app/agents.py`
  - Реализация агентов и безопасного запуска команд (`SafeCommandRunner`).
  - Интеграция с LLM через `app/llm.py`.
- `app/llm.py`
  - Абстракция провайдера LLM, трекинг токенов и лимитов.
- `app/db.py`
  - Работа с базой данных (если задан `DATABASE_URL`).
- `app/auth/`
  - Авторизация, bootstrap администратора, OAuth Google.
- `app/telegram_bot.py`
  - Интеграция с Telegram-ботом.

#### Контейнеры задач и состояние

- Основные структуры данных — `Container`, `ProjectState` в `app/models.py`.
- Состояние задачи хранится в памяти, а при наличии `DATABASE_URL`
  сохраняется в Postgres.
- Хранилище также ведёт события (`events`), артефакты (`artifacts`) и снапшоты.

### 2.2 Frontend (Telegram Mini App UI)

**Путь:** `ai-platform/frontend/`

- Статическое приложение, управляется через `frontend/app.js`.
- `index.html`, `styles.css` и `assets/` описывают интерфейс.
- UI взаимодействует с backend через REST и WebSocket.
- Поддерживаются разные режимы авторизации:
  - API ключ (`apikey`)
  - полноценная auth (`auth`)
  - комбинированный (`hybrid`)

Конфигурация подставляется через:

- `window.__APP_CONFIG__` или метатеги (`meta[name="api-base-url"]`).

### 2.3 Инфраструктура и запуск

- Docker Compose: `ai-platform/docker-compose.yml`
  - сервисы: `backend`, `frontend`, `nginx`
- Nginx конфигурация: `ai-platform/nginx/`
- Переменные окружения: `ai-platform/docs/ENV.md`

## 3. Todo API (демо-сервис)

Это независимый REST сервис в корневых модулях репозитория.

### Архитектура

- `todo_main.py` — FastAPI приложение
- `api/routes.py` — CRUD маршруты `/todos`
- `services/todo_service.py` — бизнес-логика
- `repositories/todo_repository.py` — in-memory хранилище
- `models/todo.py` — Pydantic модели

### Поток данных

1. **HTTP запрос** → `api/routes.py`
2. **Service слой** → `services/todo_service.py`
3. **Repository** → `repositories/todo_repository.py`
4. Ответ возвращается клиенту

## 4. Основной поток обработки AI-задачи

1. Клиент отправляет задачу через API (`POST /api/tasks`).
2. В `main.py` создаётся `Container`, сохраняется в `Storage`.
3. `AIOrchestrator` запускает роль `researcher`, затем `designer`, `coder`, `reviewer`.
4. Каждый агент может:
   - генерировать планы/шаги;
   - писать код и править файлы;
   - запускать безопасные команды (`SafeCommandRunner`).
5. Статус, события и артефакты сохраняются в памяти/БД и стримятся через WebSocket.
6. Клиент периодически опрашивает или получает WebSocket-обновления.

### 4.1 Последовательность ролей и границы ответственности

Порядок стадий определяется `ai-platform/backend/app/orchestrator.py` и кодексом
`ai-platform/backend/app/codex.json`:

1. **research** → `AIResearcher`
2. **design** → `AIDesigner`
3. **implementation** → `AICoder`
4. **review** → `AIReviewer`

Кодекс задаёт рамки каждой роли (см. `codex.json`):

- **Researcher**
  - Цель: анализ задачи и формирование требований.
  - Ограничения: не предлагает архитектуру и не пишет код.
  - Артефакты: `requirements.md`, `user_stories.md`.
- **Designer**
  - Цель: архитектура на основе требований.
  - Ограничения: не меняет требования, не оптимизирует преждевременно.
  - Артефакты: `architecture.md`, `implementation_plan.md`.
- **Coder**
  - Цель: реализация по архитектуре.
  - Ограничения: следует style guide, не меняет архитектуру, пишет тесты.
  - Артефакты: записи о сгенерированном коде + `code_summary` или `implementation_plan`.
- **Reviewer**
  - Цель: контроль качества и соответствия правилам.
  - Ограничения: не вносит изменения, не добавляет фичи.
  - Артефакты: `review_report` (детальный отчёт ревью).

### 4.2 Что возвращает каждая роль (внутренний формат)

Ниже — фактические структуры, которые генерируют агенты в `app/agents.py`
и которые затем записываются в контейнер (артефакты и файлы).

#### Researcher (`AIResearcher.execute`)

Возвращает объект требований и одновременно сохраняет:

- `requirements.md`
- `user_stories.md`

Пример структуры результата (упрощено):

```json
{
  "user_task": "...",
  "requirements": [{"id": "REQ-001", "description": "..."}],
  "user_stories": ["...", "..."],
  "questions_to_user": ["..."],
  "technical_constraints": ["..."]
}
```

#### Designer (`AIDesigner.execute`)

Возвращает архитектуру и сохраняет:

- `architecture.md`
- `implementation_plan.md`

Пример структуры результата:

```json
{
  "components": [
    {"name": "API Layer", "files": ["api/routes.py", "..."]}
  ],
  "api_endpoints": [{"method": "GET", "path": "/todos"}],
  "data_model": {"Todo": {"id": "int", "title": "str"}},
  "progress_metrics": {"expected_files": 12}
}
```

#### Coder (`AICoder.execute`)

Запрашивает LLM, ожидает **строго JSON** и пишет файлы в контейнер.
Ответ LLM должен иметь формат:

```json
{
  "files": [{"path": "path/to/file.py", "content": "..."}],
  "artifacts": {"code_summary": "Updated files: ..."}
}
```

## 5. Known issues / Diagnostics

- `finish_reason` в `usage_report` может быть `null` (например, при chunking-ответах),
  но ключ всегда присутствует.
- Ранее в `AICoder.execute` был крэш из-за unbound local variable для `finish_reason`;
  фикс подтверждается запуском `pytest -q` (см. тесты backend).

После записи файлов кодер возвращает метаданные выполнения:

```json
{
  "file": "path/to/file.py",
  "files": ["path/to/file.py", "..."],
  "artifact_type": "code_summary",
  "llm_usage": {"tokens_in": 123, "tokens_out": 456}
}
```

### LLM Output Format: Files To Write (Required)

**Exact required format (JSON only):**

```json
{
  "files": [
    { "path": "relative/path.txt", "content": "file contents as a JSON string" }
  ],
  "artifacts": {
    "code_summary": "Optional summary string (or implementation_plan)"
  }
}
```

**Rules (enforced by backend parsing in `ai-platform/backend/app/agents.py`):**

- Output must be valid JSON. The parser accepts raw JSON, JSON inside a single markdown fence, or the first JSON payload embedded in the response.
- **Required**: at least one file entry. Each file entry must include:
  - `path`: relative path (no leading `/`, no `..`, no `~`)
  - `content`: full file contents as a JSON string (newlines preserved)
- Multiple files are supported via the `files` array (extra entries beyond `max_files_per_iteration` are truncated).
- No-op/empty output is **not supported**: if no file entries are present, the backend raises an error.
- The coder now auto-retries up to 3 attempts when JSON parsing fails or no files are found.
  If it still fails, the error includes a short diagnostic (`invalid JSON`, `files missing`, `files empty`),
  a 400-character response preview, and the model/provider identifiers when available.

**Minimal valid example (one file):**

```json
{
  "files": [
    { "path": "RadJab.txt", "content": "Moama" }
  ],
  "artifacts": { "code_summary": "Added RadJab.txt" }
}
```

**Two-file example:**

```json
{
  "files": [
    { "path": "RadJab.txt", "content": "Moama" },
    { "path": "Notes.txt", "content": "Second file" }
  ],
  "artifacts": { "code_summary": "Added RadJab.txt and Notes.txt" }
}
```

**No-op guidance:** not supported — always return at least one file entry. If the model returns normal text without this format, the platform will raise: `LLM response did not include any files to write.`

#### Reviewer (`AIReviewer.execute`)

Выполняет проверки кода, архитектуры и тестов.
Возвращает объект отчёта вида:

```json
{
  "status": "approved|approved_with_warnings|rejected",
  "passed": true,
  "issues": ["..."],
  "warnings": ["..."],
  "ruff": {"ran": true, "exit_code": 0},
  "pytest": {"ran": true, "exit_code": 0}
}
```

### 4.3 Итеративный цикл внутри implementation

Во время **implementation** оркестратор повторяет цикл:

1. Планировщик выбирает следующий шаг (`_get_next_task`).
2. `AICoder` генерирует/обновляет файлы.
3. `AIReviewer` валидирует изменения.
4. Если ревью не прошло, оркестратор создаёт исправляющую задачу
   (`_build_fix_task`) и запускает новый виток.

Ограничения итераций и времени задаются в `codex.json` и env-переменными:

- `workflow.max_iterations`
- `LLM_MAX_CALLS_PER_TASK`
- `LLM_MAX_RETRIES_PER_STEP`

## 6. Где смотреть ключевую логику

| Область | Ключевые файлы |
|---|---|
| Backend API | `ai-platform/backend/app/main.py` |
| Оркестрация | `ai-platform/backend/app/orchestrator.py` |
| LLM провайдер | `ai-platform/backend/app/llm.py` |
| Агенты | `ai-platform/backend/app/agents.py` |
| Авторизация | `ai-platform/backend/app/auth/*` |
| Telegram бот | `ai-platform/backend/app/telegram_bot.py` |
| Frontend UI | `ai-platform/frontend/app.js` |
| Docker | `ai-platform/docker-compose.yml` |
| Todo API | `todo_main.py`, `api/routes.py` |

## 7. Как определить текущее состояние платформы

ИИ может определить состояние платформы, анализируя:

- **Backend**
  - Содержимое `Storage` в `app/main.py` (task/event/artifact/state).
  - Внешние статусы задач через API (`/api/tasks/...`).
  - Подключение к БД (наличие `DATABASE_URL`).
- **Orchestrator**
  - Codex (`app/codex.json`) определяет правила и этапы.
  - `Container.metadata` хранит историю, текущее состояние, лимиты.
- **Frontend**
  - Визуальное состояние отражает данные API (`task status`, `progress`).
- **Docker/Env**
  - Переменные окружения в `docs/ENV.md` описывают, какие функции включены.

## 8. Быстрый старт (локально)

```bash
cd ai-platform
docker compose up --build
```

Frontend будет доступен на `http://localhost`, backend — на `http://localhost:8000`.

---

Если требуется уточнение по конкретному модулю или расширение описания
(например, добавление диаграмм взаимодействия или описания API эндпоинтов),
можно расширить этот README дополнительными секциями.
