from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sql_ai_agent.agent.context import build_context
from sql_ai_agent.agent.memory import InMemorySessionStore
from sql_ai_agent.agent.sql_agent import SqlAgent
from sql_ai_agent.config import Settings
from sql_ai_agent.db.engine import create_readonly_engine
from sql_ai_agent.db.schema import load_schema

# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_db_path(tmp_path: Path) -> Path:
    db_path = tmp_path / "boutique.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE categories (
            categorie_id INTEGER PRIMARY KEY,
            nom TEXT NOT NULL
        );
        CREATE TABLE produits (
            produit_id INTEGER PRIMARY KEY,
            nom TEXT NOT NULL,
            categorie_id INTEGER NOT NULL REFERENCES categories(categorie_id),
            prix_unitaire REAL NOT NULL,
            cout_achat REAL NOT NULL,
            stock INTEGER NOT NULL,
            actif INTEGER NOT NULL,
            date_ajout TEXT NOT NULL
        );
        CREATE TABLE clients (
            client_id INTEGER PRIMARY KEY,
            prenom TEXT, nom TEXT, email TEXT,
            ville TEXT, region TEXT, date_naissance TEXT,
            date_inscription TEXT NOT NULL,
            canal_acquisition TEXT
        );
        CREATE TABLE commandes (
            commande_id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL REFERENCES clients(client_id),
            date_commande TEXT NOT NULL,
            statut TEXT NOT NULL,
            mode_paiement TEXT,
            remise_pct INTEGER NOT NULL,
            frais_livraison REAL NOT NULL
        );
        CREATE TABLE lignes_commande (
            ligne_id INTEGER PRIMARY KEY,
            commande_id INTEGER NOT NULL REFERENCES commandes(commande_id),
            produit_id INTEGER NOT NULL REFERENCES produits(produit_id),
            quantite INTEGER NOT NULL,
            prix_unitaire_paye REAL NOT NULL
        );
        CREATE TABLE avis (
            avis_id INTEGER PRIMARY KEY,
            client_id INTEGER NOT NULL REFERENCES clients(client_id),
            produit_id INTEGER NOT NULL REFERENCES produits(produit_id),
            note INTEGER NOT NULL CHECK (note BETWEEN 1 AND 5),
            date_avis TEXT NOT NULL
        );

        INSERT INTO categories VALUES (1, 'Électronique');
        INSERT INTO produits VALUES (1, 'Produit A', 1, 10.0, 5.0, 100, 1, '2023-01-01');
        INSERT INTO produits VALUES (2, 'Produit B', 1, 20.0, 8.0, 50, 1, '2023-06-01');
        INSERT INTO clients VALUES (1, 'Alice', 'Dupont', 'alice@example.com',
                                    'Lyon', 'ARA', '1990-01-01', '2023-01-15', 'direct');
        INSERT INTO commandes VALUES (1, 1, '2024-03-10', 'livree', 'carte', 0, 4.99);
        INSERT INTO lignes_commande VALUES (1, 1, 1, 2, 10.0);
        INSERT INTO avis VALUES (1, 1, 1, 5, '2024-03-15');
    """)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture()
def engine(sample_db_path: Path) -> Any:
    return create_readonly_engine(f"sqlite:///file:{sample_db_path}?mode=ro&uri=true")


@pytest.fixture()
def schema(engine: Any) -> Any:
    return load_schema(engine)


@pytest.fixture()
def test_settings(sample_db_path: Path, tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # never read .env in tests
        database_url=f"sqlite:///file:{sample_db_path}?mode=ro&uri=true",
        llm_api_key=None,
        max_rows=100,
        query_timeout_seconds=5.0,
        max_repairs=2,
        skills_dir=tmp_path / "no_skills",
        prompts_dir=Path("src/sql_ai_agent/llm/prompts"),
        session_ttl_seconds=60,
        session_max_turns=3,
        session_max_count=10,
    )


# ---------------------------------------------------------------------------
# LLM stubs
# ---------------------------------------------------------------------------


def make_fake_llm(*responses: str) -> FakeListChatModel:
    """Return a FakeListChatModel that cycles through the given SQL responses."""
    sql_blocks = [f"```sql\n{r}\n```" for r in responses]
    return FakeListChatModel(responses=list(sql_blocks))


# ---------------------------------------------------------------------------
# Agent fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def agent(engine: Any, schema: Any, test_settings: Settings) -> SqlAgent:
    fake_llm = make_fake_llm("SELECT * FROM produits LIMIT 10")
    ctx = build_context(schema=schema, engine=engine, skills="")
    return SqlAgent(
        chat_model=fake_llm,
        engine=engine,
        schema=schema,
        settings=test_settings,
        context=ctx,
        session_store=InMemorySessionStore(),
    )


# ---------------------------------------------------------------------------
# API fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_with_agent(engine: Any, schema: Any, test_settings: Settings) -> Any:
    """Create a FastAPI app with state pre-populated — lifespan skipped."""
    from sql_ai_agent.api.main import create_app

    fake_llm = make_fake_llm("SELECT 1 AS value")
    ctx = build_context(schema=schema, engine=engine, skills="")
    session_store = InMemorySessionStore()
    test_agent = SqlAgent(
        chat_model=fake_llm,
        engine=engine,
        schema=schema,
        settings=test_settings,
        context=ctx,
        session_store=session_store,
    )

    application = create_app()
    application.state.settings = test_settings
    application.state.engine = engine
    application.state.session_store = session_store
    application.state.agent = test_agent
    return application


@pytest.fixture()
def client(app_with_agent: Any) -> TestClient:
    return TestClient(app_with_agent, raise_server_exceptions=True)
