# SQL AI Agent

Project scaffold for a safe SQL agent over the boutique dataset.

## Structure

- `src/sql_ai_agent/`: package source
- `ui/app.py`: Streamlit front-end
- `config/agent.yaml`: non-secret runtime settings
- `data/raw/`: source CSV files
- `evals/`: evaluation questions and runner
- `tests/`: unit and integration tests

## Quick start

```bash
uv sync
cp .env.example .env
sql-agent-build-db --source-dir data/raw --database-path data/boutique.db
uv run uvicorn sql_ai_agent.api.main:app --reload
```

## API

- `POST /v1/query`
- `GET /health`
- `GET /ready`
