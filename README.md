# SQL AI Agent — Safe & Scalable Text-to-SQL

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi&logoColor=white" />
  <img src="https://img.shields.io/badge/LangChain-Core-1C3C3C?style=flat-square&logo=chainlink&logoColor=white" />
  <img src="https://img.shields.io/badge/SQLAlchemy-2.x-D71F00?style=flat-square" />
  <img src="https://img.shields.io/badge/NeMo_Guardrails-0.24-76B900?style=flat-square&logo=nvidia&logoColor=white" />
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white" />
  <img src="https://img.shields.io/badge/EX_Rate-100%25-22c55e?style=flat-square" />
  <img src="https://img.shields.io/badge/Tests-93_passed-22c55e?style=flat-square" />
  <img src="https://img.shields.io/badge/License-MIT-71717a?style=flat-square" />
</p>

> A **production-grade, read-only** natural-language SQL interface. Ask business questions in French, get validated SQL, live results, and full observability — with three independent safety layers preventing any write operation.

---

## Why this project

Most text-to-SQL demos stop at "the LLM generated a query." This project treats that as the _start_ of the problem:

- **What if the LLM generates a `DROP TABLE`?** → AST validator rejects it before execution.
- **What if the query times out on a large table?** → The agent retries with a repaired query.
- **What if a user asks something the database can't answer?** → The agent explicitly says so instead of hallucinating.
- **How do you know the system is healthy in production?** → Real-time observability dashboard with latency percentiles, token costs, and repair-loop metrics.

---

## Live demo

| Interface | URL |
|---|---|
| Chat (SQL Agent) | `http://localhost:8501` |
| Observability Dashboard | `http://localhost:8502` |
| REST API (Swagger) | `http://localhost:8000/docs` |

<!-- Screenshots -->
> _Screenshots of the chat UI and observability dashboard below (added after deployment)._

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Client Layer                        │
│   Streamlit Chat UI (:8501)   Observability UI (:8502)  │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP
┌────────────────────▼────────────────────────────────────┐
│                  FastAPI  (:8000)                        │
│  POST /v1/query   GET /v1/metrics   GET /health          │
│  X-Request-ID propagation · JSON structured logging      │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                   Agent Loop                             │
│                                                          │
│  ① Guardrails check (NeMo)                              │
│       ↓ pass                                             │
│  ② LLM call (ChatOpenAI-compatible)                     │
│       ↓ SQL extracted                                    │
│  ③ AST Validation (sqlglot)  ←──────────────┐           │
│       ↓ pass                                 │ repair    │
│  ④ Execution (read-only engine, timeout)     │           │
│       ↓ error ───────────────────────────────┘           │
│       ↓ success                                          │
│  ⑤ Result returned + metrics recorded                   │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│               Data & Safety Layer                        │
│  SQLite (local) / Azure SQL (prod)                       │
│  • Connection: mode=ro + PRAGMA query_only=ON            │
│  • Validator: SELECT-only, no CTEs with writes, LIMIT    │
│  • Executor: per-query timeout + row cap                 │
└─────────────────────────────────────────────────────────┘
```

---

## Key features

### Safety — three independent layers
No single point of failure can allow a write operation through.

| Layer | Mechanism | What it blocks |
|---|---|---|
| **Connection** | `mode=ro&uri=true` + `PRAGMA query_only=ON` | Any write at the driver level |
| **Validation** | sqlglot AST parser | Multi-statements, DDL, DML, subquery writes, missing LIMIT |
| **Execution** | Timeout + row cap | runaway queries, resource exhaustion |

### Self-healing agent loop
When a query fails validation or execution, the agent enters a **repair loop**: it sends the original question, the failed SQL, and the error message back to the LLM for correction — up to `max_repairs` times. Recovery rate tracked in real time.

### Observability — production-grade metrics
Thread-safe in-memory `MetricsStore` exposes `/v1/metrics` with:
- Request counters: success / error / unanswerable / guardrails-blocked
- Latency percentiles: p50 / p95 / p99 (total, LLM, execution, validation)
- Token usage and estimated cost per request
- Repair loop: attempts, recovered, exhausted, recovery rate
- Minute-bucket throughput time series
- Error distribution by type and validation failures by rule

### Session memory
Multi-session support with TTL-based eviction (default 30 min, 1 000 concurrent sessions). Follow-up questions reference prior turns automatically.

### LLM-provider agnostic
Uses `ChatOpenAI` with a configurable `base_url` — works with OpenAI, Azure OpenAI, Mistral, or any OpenAI-compatible endpoint without code changes.

---

## Evaluation results

Evaluated on 30 business questions across easy / medium / hard difficulty levels.

```
EX rate (answerable)      : 100.0%   (29 / 29)
UNANSWERABLE accuracy     : 100.0%   (1  / 1 )

By difficulty:
  easy    11/11   100%
  medium  12/12   100%
  hard     6/6    100%

Latency p50               : ~3 700 ms
Latency p95               : ~12 600 ms
```

> Latency is dominated by the LLM provider round-trip. The agent itself (validation + execution) adds < 50 ms.

---

## Tech stack

| Concern | Choice | Rationale |
|---|---|---|
| Language | Python 3.11 | `tomllib`, `StrEnum`, `ExceptionGroup` |
| Package manager | `uv` | 10-100× faster than pip, lock file committed |
| API framework | FastAPI 0.115 | async, typed, OpenAPI out of the box |
| LLM client | LangChain Core + `langchain-openai` | Provider-agnostic, no heavy agent framework |
| SQL parsing | sqlglot | AST-level validation, dialect-aware |
| DB access | SQLAlchemy 2.x | Typed, async-ready, dialect abstraction |
| Guardrails | NeMo Guardrails 0.24 (Colang 1.0) | Input filtering without prompt hacks |
| UI | Streamlit | Fast iteration, no frontend build step |
| Type checking | mypy (strict) | Zero `Any` leakage in production paths |
| Linting | Ruff | Single tool for lint + format |
| Tests | pytest + coverage | 93 tests, 0 LLM calls in CI |
| Target infra | Azure Container Apps + Azure SQL | Scale-to-zero, managed identity |

---

## Project structure

```
src/sql_ai_agent/
├── config.py                  # Single source of config (pydantic-settings)
├── domain/
│   ├── models.py              # Shared Pydantic models
│   └── errors.py              # Business exceptions → HTTP codes
├── db/
│   ├── engine.py              # Read-only SQLAlchemy engine
│   ├── schema.py              # Schema introspection (tables, PKs, FKs, samples)
│   └── executor.py            # Query execution with timeout + row cap
├── safety/
│   └── validator.py           # sqlglot AST validator
├── llm/
│   ├── client.py              # ChatOpenAI factory
│   ├── parsing.py             # SQL extraction from LLM output
│   └── prompts/               # Versioned prompt templates (.md)
│       ├── generate.md
│       └── repair.md
├── agent/
│   ├── sql_agent.py           # Core loop: generate → validate → execute → repair
│   ├── context.py             # Schema + values + skills context builder
│   ├── memory.py              # Session store (TTL, LRU eviction)
│   └── skills.py              # Domain skill loader
├── guardrails/
│   └── rails.py               # NeMo Guardrails integration
├── observability/
│   ├── metrics.py             # Thread-safe MetricsStore
│   ├── logger.py              # Structured JSON log_event()
│   ├── logging.py             # JSON formatter + request context
│   ├── context.py             # ContextVar request propagation
│   └── events.py              # Event slug constants
└── api/
    ├── main.py                # FastAPI app + lifespan
    ├── errors.py              # Exception → HTTP response mapping
    └── routes/
        ├── query.py           # POST /v1/query
        ├── sessions.py        # DELETE /v1/sessions/{id}
        ├── metrics.py         # GET /v1/metrics, DELETE /v1/metrics/reset
        └── health.py          # GET /health, GET /ready

ui/
├── app.py                     # Chat interface (Streamlit)
└── observability.py           # Metrics dashboard (Streamlit)

evals/
├── questions.yaml             # 30 labelled questions (easy/medium/hard)
├── run_evals.py               # EX rate + UNANSWERABLE accuracy runner
└── results/                   # JSON result snapshots (gitignored)

tests/
├── unit/                      # No network, no LLM (FakeListChatModel)
├── integration/               # TestClient + in-memory SQLite, LLM mocked
└── regression/                # Golden-set regression suite
```

---

## Quick start

### With Docker (recommended)

```bash
git clone https://github.com/kpatc/ai-safe-and-scalable-sql-ai-agents
cd ai-safe-and-scalable-sql-ai-agents
cp .env.example .env          # set LLM_API_KEY
docker compose up --build     # db-init + api (:8000) + ui (:8501)
```

### Local development

```bash
# 1. Install dependencies
uv sync

# 2. Configure environment
cp .env.example .env
# → set LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

# 3. Build the database from CSV files
uv run sql-agent-build-db --csv-dir data/raw --output data/boutique.db

# 4. Start the API
uv run uvicorn sql_ai_agent.api.main:app --reload

# 5. Start the chat UI (separate terminal)
uv run streamlit run ui/app.py --server.port 8501

# 6. Start the observability dashboard (separate terminal)
uv run streamlit run ui/observability.py --server.port 8502
```

### Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `LLM_API_KEY` | ✅ | — | API key for LLM provider |
| `LLM_BASE_URL` | ✅ | — | OpenAI-compatible endpoint URL |
| `LLM_MODEL` | ✅ | — | Model identifier (e.g. `gpt-4o`) |
| `DATABASE_URL` | ✅ | — | `sqlite:///file:path.db?mode=ro&uri=true` |
| `MAX_REPAIRS` | ✗ | `2` | Max repair loop iterations |
| `MAX_ROWS` | ✗ | `500` | Row cap per query |
| `QUERY_TIMEOUT_SECONDS` | ✗ | `10` | Per-query execution timeout |
| `SESSION_TTL_SECONDS` | ✗ | `1800` | Session inactivity timeout |
| `GUARDRAILS_DIR` | ✗ | — | Path to NeMo Guardrails config |
| `ENVIRONMENT` | ✗ | `development` | `development` / `production` |

---

## API reference

### `POST /v1/query`

```json
{
  "question": "Quels sont les 5 produits les plus chers ?",
  "session_id": "optional-uuid-for-follow-up"
}
```

**Success response (200)**
```json
{
  "sql": "SELECT nom, prix_unitaire FROM produits ORDER BY prix_unitaire DESC LIMIT 5",
  "columns": ["nom", "prix_unitaire"],
  "rows": [["Produit A", 299.99], ["Produit B", 249.50]],
  "row_count": 5,
  "truncated": false,
  "attempts": 1,
  "latency_ms": 843.2,
  "session_id": "abc-123"
}
```

**Unanswerable response (200)**
```json
{
  "unanswerable": true,
  "reason": "La base ne contient pas de données météorologiques."
}
```

**Error codes**

| Code | Meaning |
|---|---|
| `422` | SQL failed validation or repair exhausted |
| `503` | LLM provider unavailable |
| `504` | Query execution timeout |

### `GET /v1/metrics`
Returns a full observability snapshot (requests, latency, tokens, cost, repair loop, model distribution).

### `DELETE /v1/metrics/reset`
Resets all counters — for testing only.

---

## Running tests

```bash
uv run pytest                          # all tests
uv run pytest -m "not llm"            # CI mode (no real LLM calls)
uv run pytest -m llm                  # end-to-end with real LLM
uv run pytest --cov=sql_ai_agent      # with coverage
```

## Running evals

```bash
# API must be running on :8000
uv run python evals/run_evals.py

# Subset
uv run python evals/run_evals.py --ids q001,q005,q018

# Custom API URL
uv run python evals/run_evals.py --api-url http://staging:8000
```

---

## Safety & security decisions

**Read-only is enforced at three independent layers** — not by trusting the LLM prompt. Removing any one layer is explicitly prohibited in the codebase rules (`CLAUDE.md`).

**LLM output is treated as untrusted input.** Every query produced by the model passes through the AST validator before reaching the database, including queries generated during repair loops.

**No PII in logs.** Questions, IPs, and error messages are SHA-256 hashed before logging. Result rows are never logged — only row counts and column names.

**Secrets come from the environment only.** No credentials in code, config files, or test fixtures.

---


## License

MIT — see [LICENSE](LICENSE).

---

<p align="center">
  Built as a production-grade academic project · <a href="https://github.com/kpatc">@kpatc</a>
</p>
