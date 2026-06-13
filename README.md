# Agromaly — AI-Powered Agricultural Monitoring Platform

**Bachelor Thesis Project** · Artificial Intelligence · Babeș-Bolyai University (UBB FMI)

Agromaly is a full-stack platform that monitors crop health using satellite imagery, weather data, and machine learning — then provides proactive agronomic recommendations in Romanian through a conversational AI agronomist. It is designed for Romanian farmers and targets common crops such as corn, wheat, sunflower, rapeseed, and sugar beet.

---

## What the App Does

### Satellite NDVI Monitoring
The platform automatically fetches Sentinel-2 satellite imagery for each registered parcel via the Copernicus Data Space Ecosystem (Sentinel Hub). It computes the Normalized Difference Vegetation Index (NDVI) — a measure of vegetation health — and stores a time-series per parcel, filtering out cloud-contaminated readings.

### LSTM Anomaly Detection
A PyTorch LSTM Autoencoder is trained on historical NDVI sequences. When the reconstruction error on recent NDVI data exceeds a learned threshold (99th percentile of training errors), the model flags the parcel as anomalous. The anomaly score (0 = healthy, 1 = severe) is computed daily by a Celery background task.

### AI Agronomist (RAG)
When an anomaly is detected, the platform generates an AI recommendation using a Retrieval-Augmented Generation (RAG) pipeline: relevant excerpts are retrieved from a local ChromaDB vector store (populated from Romanian agricultural manuals), and gpt-4o produces a concrete action plan in Romanian — no technical jargon, just practical field advice.

The same AI agronomist is available interactively in the app as "Dr. Agro": farmers can ask crop-specific questions in a chat interface, either globally or in the context of a specific parcel with its current satellite and weather data injected into the prompt.

### Weather Integration
Open-Meteo provides free real-time and forecast weather data. The app uses the last 30 days of weather to give the AI context for anomaly diagnosis (drought, frost, excessive rain) and the upcoming 7-day forecast to generate a weekly field-operations plan (spraying windows, irrigation advice, frost warnings).

### Alerts & Notifications
Detected anomalies create alerts that are visible in the Alerts Hub screen. Each alert contains the detected anomaly score, the affected parcel details, the weather context, and the AI-generated recommendation. A bulk scan endpoint allows re-running anomaly detection across all active parcels on demand.

### Parcel Management
Farmers register parcels by drawing a polygon on a satellite map (Mapbox) or importing a GPX track. The parcel geometry is stored in PostGIS. Each parcel has a name, crop type, and area. NDVI sync and anomaly detection are triggered automatically after registration.

---

## Architecture

The backend follows **Hexagonal (Ports & Adapters) Architecture**:

```
backend/app/
├── domain/          # Pure Python dataclasses (entities) + abstract interfaces (ports)
├── application/     # Services (use cases) + Celery async tasks
├── infrastructure/  # SQLAlchemy ORM, PostgreSQL repositories, external API clients
└── presentation/    # FastAPI routers, Pydantic schemas, dependency injection
```

The frontend is a **Flutter** mobile/web app that communicates with the backend exclusively through the REST API.

### Technology Stack

| Layer | Technology |
|---|---|
| Backend API | Python 3.12, FastAPI, Uvicorn |
| Database | PostgreSQL 16 + PostGIS 3.4 (spatial queries via SQLAlchemy async + asyncpg) |
| Task Queue | Celery 5 + Redis 7 (broker and result backend) |
| ML Model | PyTorch — LSTM Autoencoder for NDVI time-series anomaly detection |
| AI / RAG | LangChain, OpenAI gpt-4o, text-embedding-3-small, ChromaDB (local vector store) |
| Satellite Data | Sentinel Hub / Copernicus Data Space Ecosystem |
| Weather | Open-Meteo (free, no API key required) |
| Auth | JWT (access + refresh tokens), argon2 password hashing |
| Frontend | Flutter (Dart), targeting Android and web |
| Maps | Mapbox GL (satellite tiles + polygon drawing) |
| Infrastructure | Docker, Docker Compose, Flower (Celery monitoring) |

---

## Project Structure

```
agromaly-thesis/
├── backend/
│   ├── app/
│   │   ├── core/           # Config, security, exceptions, Celery setup
│   │   ├── domain/         # Entities (parcel, user, alert, ndvi_record) + interfaces
│   │   ├── application/    # Services (analysis, parcel, rag, user) + Celery tasks
│   │   ├── infrastructure/ # DB models, repositories, Sentinel/weather clients
│   │   ├── ml/             # LSTM Autoencoder model definition + inference
│   │   └── presentation/   # FastAPI routers + Pydantic schemas
│   ├── alembic/            # Database migrations
│   ├── data/
│   │   ├── models/         # Trained model artifacts (.pt, .json)
│   │   ├── chroma/         # ChromaDB vector store (populated by ingestor)
│   │   └── knowledge_base/ # Source PDFs / text files for RAG ingestion
│   ├── scripts/
│   │   └── ingest_knowledge_base.py  # Populate ChromaDB from local documents
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example        # Template — copy to .env and fill in values
├── frontend/
│   ├── lib/
│   │   ├── screens/        # All UI screens (map, parcels, analysis, chat, alerts)
│   │   ├── models/         # Dart model classes
│   │   ├── providers/      # State management (Riverpod)
│   │   └── core/           # API client, constants, routing
│   └── pubspec.yaml
└── docker-compose.yml
```

---

## Running the App

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose)
- [Flutter SDK](https://docs.flutter.dev/get-started/install) 3.x (for the mobile app)
- An OpenAI API key (for the AI agronomist features)
- A Sentinel Hub account on [Copernicus Data Space](https://dataspace.copernicus.eu/) (or use mock mode — see below)
- A Mapbox public token (for satellite map tiles in the frontend)

### 1. Configure Environment Variables

```bash
cd backend
cp .env.example .env
```

Open `.env` and fill in the required values:

| Variable | Description |
|---|---|
| `SECRET_KEY` | Random hex string for JWT signing. Generate with: `python -c "import secrets; print(secrets.token_hex(64))"` |
| `POSTGRES_PASSWORD` | Strong password for the PostgreSQL database |
| `REDIS_PASSWORD` | Strong password for the Redis broker |
| `OPENAI_API_KEY` | Your OpenAI API key (`sk-...`) |
| `SENTINEL_CLIENT_ID` | Sentinel Hub OAuth2 client ID |
| `SENTINEL_CLIENT_SECRET` | Sentinel Hub OAuth2 client secret |
| `MAPBOX_ACCESS_TOKEN` | Mapbox public token (`pk.*`) |
| `USE_MOCK_SATELLITE` | Set to `true` to skip real Sentinel calls during development |

> **Development shortcut:** Set `USE_MOCK_SATELLITE=true` in your `.env` to use synthetic NDVI data. This lets you run the full app without Sentinel Hub credentials. The AI and anomaly detection features still work — only the satellite data source is mocked.

### 2. Start the Backend (Docker)

```bash
# From the project root — starts PostgreSQL, Redis, FastAPI, Celery worker, Celery beat, and Flower
docker compose --env-file backend/.env up --build
```

On first run, the database schema is applied automatically via Alembic. Wait for the `agromaly_api` container to print "Application startup complete" before using the app.

**Service URLs:**

| Service | URL |
|---|---|
| FastAPI (REST API + Swagger docs) | http://localhost:8000/docs |
| Flower (Celery task monitor) | http://localhost:5555 |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |

### 3. Ingest the Knowledge Base (optional but recommended)

The RAG pipeline retrieves relevant passages from Romanian agricultural guides stored in ChromaDB. To populate the vector store, add PDF or text files to `backend/data/knowledge_base/` and run:

```bash
docker exec -it agromaly_api python scripts/ingest_knowledge_base.py
```

If skipped, the AI agronomist falls back to its pretrained knowledge and still works — it just won't cite local documents.

### 4. Run the Flutter Frontend

```bash
cd frontend
flutter pub get

# Run on a connected Android device or emulator
flutter run

# Or build a release APK
flutter build apk
```

The app points to `http://10.0.2.2:8000` by default (Android emulator localhost alias). For a physical device on the same network, update `API_BASE_URL` in `frontend/lib/core/constants.dart` to your machine's local IP (e.g., `http://192.168.1.x:8000`).

---

## API Reference

All endpoints are under `/api/v1`. The full interactive documentation is available at `http://localhost:8000/docs` when running in development mode.

| Method | Endpoint | Description |
|---|---|---|
| POST | `/users/register` | Create a new account |
| POST | `/users/login` | Obtain access + refresh tokens |
| POST | `/users/refresh` | Refresh access token |
| GET | `/parcels` | List user's parcels |
| POST | `/parcels` | Register a new parcel (GeoJSON polygon) |
| GET | `/parcels/{id}` | Get parcel details |
| DELETE | `/parcels/{id}` | Delete a parcel |
| GET | `/analysis/parcels/{id}/ndvi` | NDVI time-series for a parcel |
| GET | `/analysis/parcels/{id}/anomaly` | Latest anomaly result |
| GET | `/analysis/parcels/{id}/forecast` | 7-day weather forecast |
| GET | `/analysis/parcels/{id}/weekly-advice` | AI weekly operations plan |
| GET | `/alerts` | List all alerts for the user |
| POST | `/alerts/scan-all` | Trigger anomaly scan across all parcels |
| POST | `/chat/ask` | Global AI agronomist chat |
| POST | `/chat/parcels/{id}/ask` | Parcel-specific AI agronomist chat |
| POST | `/upload/{token}/files` | Import parcel boundary via GPX |
| GET | `/health` | Liveness probe |

---

## Background Tasks (Celery)

Three periodic tasks run automatically:

- **NDVI Sync** (`sync_ndvi_tasks.py`): Fetches new Sentinel-2 NDVI observations for all parcels that haven't been updated recently.
- **Weather Sync** (`sync_weather_tasks.py`): Updates the 30-day weather history used for anomaly context.
- **Anomaly Detection** (`anomaly_detection_task.py`): Runs the LSTM model on each parcel's NDVI time-series, updates the anomaly score, and creates alerts with AI recommendations when anomalies are detected.

Task schedules are configured in `backend/app/core/celery_app.py`. Celery Beat drives the scheduler; Flower provides a web UI to inspect task history and queue state.

---

## Database Migrations

```bash
# Apply all pending migrations
docker exec -it agromaly_api alembic upgrade head

# Auto-generate a new migration after changing SQLAlchemy models
docker exec -it agromaly_api alembic revision --autogenerate -m "describe the change"
```

---

## Running Tests

```bash
cd backend
pytest                        # run all tests
pytest --cov=app              # with coverage report
pytest tests/path/test_file.py::test_name  # single test
```

---

## Key Design Decisions

- **No framework imports in domain entities** — `domain/entities/` contains pure Python frozen dataclasses. SQLAlchemy, FastAPI, and Pydantic only appear in their respective layers, keeping the core business logic portable and testable.
- **Geometry at the boundary** — Parcel geometry is stored as WKT strings in domain entities and converted to/from PostGIS geometry types only inside the repository implementations.
- **NDVI-only LSTM** — The anomaly detection model takes a single feature (NDVI) as input, trained on a sliding window of observations. This keeps the model simple, interpretable, and robust to missing weather or auxiliary data.
- **Graceful degradation** — If `OPENAI_API_KEY` is not set, all AI endpoints return HTTP 503 with a clear message instead of crashing. If ChromaDB is empty, the LLM falls back to its pretrained agricultural knowledge.
- **Romanian-first AI** — All AI system prompts are written in Romanian and explicitly instruct the model to respond in Romanian, use farmer-friendly language (no technical ML terms), and avoid Markdown formatting (which would look bad in plain-text mobile UI).
