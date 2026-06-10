# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Agromaly is an agricultural analytics platform that uses satellite NDVI data, weather APIs, and AI/ML to detect crop anomalies and provide agronomic recommendations. The backend is Python/FastAPI; the frontend is Flutter.

## Development Commands

### Backend (Docker-based — preferred)

```bash
# Start all services (PostgreSQL+PostGIS, Redis, FastAPI, Celery worker, Flower)
docker compose up --build

# Run only infrastructure (DB + Redis) and start FastAPI locally
docker compose up db redis -d
cd backend && uvicorn app.main:app --reload --port 8000
```

**Service ports:**
- FastAPI: `http://localhost:8000` (Swagger at `/docs`)
- Flower (Celery monitor): `http://localhost:5555`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

### Database Migrations (Alembic)

```bash
# Inside the backend container or venv:
alembic upgrade head
alembic revision --autogenerate -m "description"
```

### Flutter Frontend

```bash
cd frontend
flutter pub get
flutter run                   # requires a running backend
flutter build apk             # Android release build
```

### Python Tests

```bash
cd backend
pytest                        # all tests
pytest tests/path/test_file.py::test_name   # single test
pytest --cov=app              # with coverage
```

## Architecture

The backend uses **Hexagonal (Ports & Adapters) Architecture** with four layers:

```
app/
├── domain/          # Pure Python dataclasses (entities) + abstract interfaces (ports)
├── application/     # Services (use cases) + Celery async tasks
├── infrastructure/  # SQLAlchemy ORM, repositories, external API clients
└── presentation/    # FastAPI routers, Pydantic schemas, dependency injection
```

**Key rules to follow:**
- `domain/entities/` are frozen dataclasses — no framework imports (no SQLAlchemy, FastAPI, Pydantic)
- `domain/interfaces/` define abstract repository ports (ABC)
- `infrastructure/repositories/` are the concrete implementations using SQLAlchemy+PostGIS
- `infrastructure/external/` wraps Sentinel Hub, Open-Meteo, and OpenAI
- Services in `application/services/` orchestrate domain logic and are injected via `presentation/api/v1/dependencies.py`
- Endpoints in `presentation/api/v1/endpoints/` use `Depends()` for DI and never import infrastructure directly
- Domain exceptions (in `core/exceptions.py`) are caught by centralized handlers in `main.py` and converted to HTTP responses

## Key Technology Choices

- **Database:** PostgreSQL 16 + PostGIS 3.4 via SQLAlchemy async (`asyncpg`). Geometry stored as WKT strings in domain entities, converted to/from PostGIS at the repository boundary.
- **Task queue:** Celery 5 with Redis broker. Tasks for NDVI sync, weather sync, and anomaly detection live in `application/tasks/`.
- **ML:** PyTorch LSTM Autoencoder for NDVI time-series anomaly detection (`app/ml/`).
- **RAG:** LangChain + OpenAI (`gpt-4o-mini` / `text-embedding-3-small`) + ChromaDB local vector store for agronomic recommendations.
- **Auth:** JWT (access + refresh tokens) with argon2 password hashing.
- **Satellite:** `USE_MOCK_SATELLITE=true` in `.env` bypasses real Sentinel Hub calls during development.

## Configuration

Copy `.env.example` to `.env`. Required variables:
- `SECRET_KEY` — JWT signing key (≥32 chars)
- `POSTGRES_*` — database credentials
- `REDIS_PASSWORD`
- `OPENAI_API_KEY`, `SENTINEL_CLIENT_ID`, `SENTINEL_CLIENT_SECRET`
- `APP_ENV` — controls CORS strictness and whether `/docs` is exposed

## API Structure

All endpoints are under `/api/v1`:
- `/users` — registration, login, token refresh
- `/parcels` — CRUD for agricultural parcels (JWT required)
- `/analysis` — NDVI records, anomaly results, alerts
- `/upload/{token}/files` — GPX file import (token-gated, no JWT)
- `/health` — liveness probe
