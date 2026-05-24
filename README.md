# AI-Powered Autonomous Backend System
### Self-Learning Data Intelligence Platform

> Upload raw data → Auto-generate schemas & APIs → Query with natural language → Get AI-powered insights

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        CLIENT LAYER                              │
│          REST Clients │ NL Query UI │ CSV Upload │ APIs          │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│                      API GATEWAY (FastAPI)                        │
│    JWT Auth · Rate Limiting · Request Routing · Swagger Docs      │
└──┬──────────────┬─────────────────┬────────────────┬─────────────┘
   │              │                 │                │
┌──▼──┐     ┌────▼────┐      ┌─────▼────┐     ┌────▼────┐
│Ingest│    │ Schema  │      │ Auto API │     │  Auth   │
│Engine│    │  Gen    │      │Generator │     │ JWT/RBAC│
└──┬──┘     └────┬────┘      └─────┬────┘     └─────────┘
   │              │                 │
┌──▼──────────────▼─────────────────▼──────────────────────────────┐
│                        AI ENGINE                                  │
│   Insight Engine │ NL→SQL │ Prompt Templates │ Feedback Loop      │
└─────────────────────────────┬─────────────────────────────────────┘
                              │
                    ┌─────────▼─────────┐
                    │   OpenAI GPT-4o   │
                    │ Embeddings │ Tools │
                    └─────────┬─────────┘
                              │
┌─────────────────────────────▼─────────────────────────────────────┐
│                        DATA LAYER                                  │
│     PostgreSQL (SQLAlchemy) │ Redis Cache │ File Storage           │
└────────────────────────────────────────────────────────────────────┘
```

---

## Folder Structure

```
ai-backend-system/
├── app/
│   ├── main.py                     # FastAPI application factory
│   ├── api/v1/
│   │   ├── router.py               # Combines all routers
│   │   └── endpoints/
│   │       ├── auth.py             # Register, login, /me
│   │       ├── datasets.py         # Upload, analyze, CRUD
│   │       ├── ai.py               # Insights, NL query, feedback
│   │       └── health.py           # /health, /
│   ├── core/
│   │   ├── config.py               # Pydantic settings (env vars)
│   │   ├── exceptions.py           # Custom exception hierarchy
│   │   ├── logging.py              # Structured JSON logging
│   │   └── middleware.py           # Rate limiting, request logging
│   ├── db/
│   │   ├── session.py              # Async SQLAlchemy engine & session
│   │   └── redis.py                # Redis client + CacheService
│   ├── models/
│   │   └── models.py               # All SQLAlchemy ORM models
│   ├── schemas/
│   │   └── schemas.py              # Pydantic v2 request/response schemas
│   ├── repositories/
│   │   ├── user_repository.py      # User data access layer
│   │   └── dataset_repository.py   # Dataset data access layer
│   ├── services/
│   │   ├── auth/
│   │   │   └── auth_service.py     # JWT, password hashing, RBAC
│   │   ├── data/
│   │   │   ├── ingestion_engine.py # CSV/JSON/Excel parsing & cleaning
│   │   │   └── schema_generator.py # Raw schema → DB schema + model code
│   │   └── ai/
│   │       ├── insight_engine.py   # LLM-powered analytics
│   │       ├── nl_query_engine.py  # NL → SQL → results
│   │       └── feedback_service.py # Feedback loop & prompt tuning
│   ├── prompts/
│   │   └── prompt_library.py       # All prompt templates (versioned)
│   └── workers/
│       ├── celery_app.py           # Celery configuration
│       └── tasks.py                # Background task definitions
├── alembic/                        # Database migrations
├── tests/
│   ├── unit/test_core.py           # Unit tests (no DB/API needed)
│   └── integration/test_api.py     # Integration tests
├── data/samples/                   # Sample datasets for testing
├── docker/
│   ├── Dockerfile                  # Multi-stage production build
│   └── init.sql                    # PostgreSQL extensions + seed data
├── postman/                        # Postman collection
├── docker-compose.yml
├── requirements.txt
├── alembic.ini
└── .env.example
```

---

## Quick Start

### Option 1: Docker (Recommended)

```bash
# 1. Clone and configure
git clone <repo-url>
cd ai-backend-system
cp .env.example .env

# 2. Set your OpenAI API key in .env
echo "OPENAI_API_KEY=sk-your-key-here" >> .env

# 3. Start the full stack
docker-compose up -d

# 4. Verify everything is running
curl http://localhost:8000/health
```

Services started:
| Service | URL |
|---------|-----|
| API | http://localhost:8000 |
| Swagger Docs | http://localhost:8000/docs |
| Flower (Celery UI) | http://localhost:5555 |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |

---

### Option 2: Local Development

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL, OPENAI_API_KEY, etc.

# 4. Start PostgreSQL and Redis (via Docker or local)
docker run -d -p 5432:5432 -e POSTGRES_USER=aibackend -e POSTGRES_PASSWORD=aibackend_password -e POSTGRES_DB=aibackend_db postgres:16-alpine
docker run -d -p 6379:6379 redis:7-alpine

# 5. Run database migrations
alembic upgrade head

# 6. Start the API
uvicorn app.main:app --reload --port 8000

# 7. Start Celery worker (in another terminal)
celery -A app.workers.celery_app worker --loglevel=info
```

---

## API Reference

### Authentication

All protected endpoints require `Authorization: Bearer <token>` header.

```bash
# Register
POST /v1/auth/register
{"email": "user@example.com", "username": "myuser", "password": "SecurePass123"}

# Login → returns access_token
POST /v1/auth/login
{"email": "user@example.com", "password": "SecurePass123"}
```

---

### Dataset Ingestion

```bash
# Upload a CSV file
POST /v1/datasets/upload
Content-Type: multipart/form-data
  file: <your CSV/JSON/XLSX>
  name: "My Sales Data"

# Ingest from API/JSON
POST /v1/datasets/ingest-json?name=ApiData
Content-Type: application/json
[{"id": 1, "product": "Laptop", "sales": 50}, ...]

# Get analyzed schema
GET /v1/datasets/{id}/schema

# Get auto-generated SQLAlchemy model code
GET /v1/datasets/{id}/generated-tables
```

---

### AI Intelligence

```bash
# Generate AI insights
POST /v1/ai/datasets/{id}/insights
{"insight_type": "summary"}          # summary | trend | anomaly | recommendation

# Natural language query
POST /v1/ai/query
{"query": "Top 5 customers by revenue", "dataset_id": "...", "explain": true}

# Response includes:
# - generated_sql: the SQL query that was run
# - explanation: plain English explanation of the SQL
# - columns + rows: the actual results
# - execution_time_ms: performance metric

# Submit feedback to improve the AI
POST /v1/ai/feedback
{"query_id": "...", "rating": 5, "was_helpful": true}
```

---

## Core Features Deep Dive

### 1. Data Ingestion Engine
- Supports CSV (any encoding), JSON, XLSX
- Auto-detects column types: integers, floats, datetimes, categories
- Cleans data: normalises column names, strips whitespace, drops empties
- Handles API responses (unwraps `data`, `results`, `items` keys)
- Chunked reading for large files via background Celery task

### 2. Schema Generator
- Converts raw type analysis into optimized PostgreSQL DDL
- Auto-adds UUID primary keys
- Detects foreign key candidates (`*_id` columns with low cardinality)
- Generates index recommendations for commonly-queried columns
- Outputs ready-to-paste SQLAlchemy model Python code
- Provides human-readable optimization recommendations

### 3. AI Insight Engine
- **Summary**: Executive overview with data quality observations
- **Trends**: Time-series analysis with quantified growth rates
- **Anomaly**: Outlier detection and data quality scoring
- **Recommendations**: Business actions backed by data evidence
- Retry logic for OpenAI rate limits (exponential backoff via tenacity)
- Token usage tracked per request for cost monitoring

### 4. Natural Language Query
- Converts English questions → PostgreSQL SQL via GPT-4o
- Schema context injection ensures accurate table/column references
- SQL safety validation (blocks any non-SELECT operations)
- Optional plain-English explanation of the generated query
- All queries logged for the feedback loop

### 5. Feedback Loop System
- Users rate AI responses (1–5 stars)
- Ratings update prompt template performance scores (EMA)
- Templates flagged when score drops below 3.0
- Aggregated improvement suggestions surfaced to prompt engineers
- Celery task refreshes scores every 6 hours

### 6. Prompt Engineering Module
- All prompts centralized in `PromptLibrary` (no hardcoded strings)
- Templates are versioned (semver) and categorized
- `$variable` substitution with validation
- Performance score tracked per template version
- Easy A/B testing: register a new version, compare scores

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | ✅ | Your OpenAI API key |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `SECRET_KEY` | ✅ | App secret (min 32 chars) |
| `JWT_SECRET_KEY` | ✅ | JWT signing key (min 32 chars) |
| `REDIS_URL` | ✅ | Redis connection string |
| `OPENAI_MODEL` | ❌ | Default: `gpt-4o` |
| `RATE_LIMIT_PER_MINUTE` | ❌ | Default: 60 |
| `RATE_LIMIT_AI_PER_MINUTE` | ❌ | Default: 10 |
| `MAX_UPLOAD_SIZE_MB` | ❌ | Default: 100 |

---

## Running Tests

```bash
# Run all tests
pytest

# Unit tests only (no DB needed)
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# With coverage
pytest --cov=app --cov-report=html
```

---

## Production Checklist

- [ ] Set strong `SECRET_KEY` and `JWT_SECRET_KEY` (use `openssl rand -hex 32`)
- [ ] Set `ENVIRONMENT=production` and `DEBUG=false`
- [ ] Configure CORS origins (remove `*` wildcard)
- [ ] Use Alembic for migrations (don't rely on `create_all_tables`)
- [ ] Set up log aggregation (Datadog, CloudWatch, etc.)
- [ ] Configure OpenAI budget alerts
- [ ] Add HTTPS via Nginx or a load balancer
- [ ] Set up database backups
- [ ] Configure Sentry for error tracking

---

## Database Schema

```
users                 datasets              generated_tables
────────────────      ─────────────────     ─────────────────────
id (UUID PK)    ←─┐  id (UUID PK)    ←─┐  id (UUID PK)
email               └─ owner_id (FK)    └─ dataset_id (FK)
username             name                  table_name
hashed_password      source_type           columns (JSON)
role                 row_count             indexes (JSON)
is_active            column_count          sqlalchemy_model_code
created_at           raw_schema (JSON)     is_created
                     generated_schema
                     status

query_logs            insights              feedback
──────────────────    ─────────────────     ─────────────────────
id (UUID PK)          id (UUID PK)          id (UUID PK)
user_id (FK)          dataset_id (FK)       user_id (FK)
dataset_id (FK)       insight_type          query_id (FK)
natural_language      content               rating (1-5)
generated_sql         prompt_tokens         was_helpful
execution_time_ms     model_used            comment
prompt_version        created_at            suggested_improvement
```

---

## License

MIT
