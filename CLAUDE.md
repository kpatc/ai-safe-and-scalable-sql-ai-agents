# CLAUDE.md

Agent text-to-SQL en lecture seule : une question en français entre, une requête SQL validée est générée par un LLM, exécutée sur une base, et le résultat revient par une API FastAPI. Cible finale : Azure Container Apps + Azure SQL. Phase actuelle : développement local sur SQLite.

Projet académique traité comme un service de production : tests, typage strict, sécurité en profondeur, configuration par variables d'environnement.

Le plan d'implémentation détaillé, phase par phase, est dans `docs/ROADMAP.md`. Le schéma et les pièges du dataset sont dans `docs/DATASET.md`. Lis le fichier concerné avant de commencer une phase.

## Stack

- Python 3.11, gestion d'environnement avec uv (`pyproject.toml` + `uv.lock` commité)
- LangChain : `langchain-core` + `langchain-openai` uniquement. Le LLM est appelé via `ChatOpenAI` avec un `base_url` configurable, pour fonctionner avec n'importe quel fournisseur compatible API OpenAI
- SQLAlchemy 2.x pour l'accès base (SQLite en local, Azure SQL via pyodbc plus tard)
- sqlglot pour l'analyse et la validation du SQL généré
- FastAPI + uvicorn pour l'API, pydantic-settings pour la configuration
- Streamlit pour l'UI, qui n'est qu'un client HTTP de l'API
- pytest, ruff (lint + format), mypy en mode strict

Pas d'ibis, pas de LangGraph, pas d'agents LangChain "prêts à l'emploi" (`create_sql_agent`, toolkits) : la boucle de l'agent est écrite explicitement pour garder le contrôle sur la validation et les logs.

## Commandes

```bash
uv sync                                    # installe dépendances + groupe dev
uv sync --group ui                         # ajoute Streamlit
uv run sql-agent-build-db --csv-dir data/raw --output data/boutique.db
uv run pytest                              # tests unitaires + intégration (LLM mocké)
uv run pytest -m "not llm"                 # ce que lance la CI
uv run pytest -m llm                       # tests avec vrai LLM, à la demande
uv run ruff check --fix . && uv run ruff format .
uv run mypy src
uv run uvicorn sql_ai_agent.api.main:app --reload
uv run python evals/run_evals.py           # évaluation de précision, appelle le vrai LLM
docker compose up --build                  # db-init + api (:8000) + ui (:8501)
```

Après chaque modification de code : `ruff check`, `ruff format`, `mypy src`, `pytest -m "not llm"`. Une tâche n'est terminée que si les quatre passent.

## Structure

```
src/sql_ai_agent/
  config.py              Settings (pydantic-settings), seule source de configuration
  domain/models.py       Modèles Pydantic partagés : QueryRequest, QueryResult, AgentTrace, Turn
  domain/errors.py       Exceptions métier (voir "Erreurs")
  db/engine.py           Création de l'engine SQLAlchemy lecture seule
  db/schema.py           Introspection : tables, colonnes, PK, FK, valeurs distinctes
  db/executor.py         Exécution avec timeout et plafond de lignes
  safety/validator.py    Validation AST du SQL avec sqlglot
  llm/client.py          Fabrique ChatOpenAI + fallback
  llm/parsing.py         Extraction du SQL depuis la réponse du LLM
  llm/prompts/*.md       Templates de prompts versionnés
  agent/context.py       Assemblage du contexte (schéma, valeurs, skills)
  agent/memory.py        Mémoire de session (follow-up questions)
  agent/skills.py        Chargement des fichiers skills/*.md
  agent/sql_agent.py     Boucle générer -> valider -> exécuter -> réparer
  observability/logging.py  Logs JSON, request_id, tokens, latences
  api/main.py            App FastAPI, lifespan
  api/routes/            query.py, sessions.py, health.py
  api/dependencies.py    Injection : settings, engine, agent
  api/errors.py          Mapping exceptions métier -> HTTP
  cli/build_db.py        CSV -> SQLite
ui/app.py                Streamlit
skills/boutique.md       Règles métier injectées dans le prompt
config/agent.yaml        Paramètres non secrets
data/raw/*.csv           Dataset (le .db est généré, gitignoré)
evals/                   questions.yaml, run_evals.py, results/ (gitignoré)
tests/unit/, tests/integration/, tests/conftest.py
```

Les dépendances entre couches vont dans un seul sens : `api -> agent -> (llm, db, safety) -> domain`. `domain` n'importe rien du projet. `db`, `llm` et `safety` ne s'importent pas entre eux. Aucun module hors de `api/` n'importe FastAPI.

## Règles de sécurité (non négociables)

La lecture seule est garantie par trois verrous indépendants. Aucun ne doit être retiré ou contourné, même pour faire passer un test.

1. Connexion : SQLite ouvert avec `?mode=ro&uri=true` et `PRAGMA query_only = ON` sur chaque connexion (event `connect` de SQLAlchemy). En Azure : utilisateur `db_datareader` uniquement.
2. Validation : `safety/validator.py` rejette tout ce qui n'est pas une seule instruction de lecture (voir ROADMAP phase 2).
3. Exécution : timeout par requête et plafond de lignes, toujours appliqués.

Autres règles :
- Jamais de SQL construit par f-string ou concaténation avec une donnée externe. Paramètres liés (`text(...).bindparams`) ou identifiants issus de l'introspection et quotés par le dialecte.
- Le SQL produit par le LLM est une donnée non fiable : il passe toujours par le validateur avant exécution, y compris dans la boucle de réparation.
- Les secrets viennent de l'environnement (`.env` en local). Ne jamais lire, modifier ou afficher `.env`. Ne jamais écrire de clé dans le code, les tests ou les logs.
- Les logs ne contiennent pas les lignes de résultat, seulement leur nombre et les noms de colonnes.
- Ne jamais affaiblir ou supprimer un test de `tests/unit/test_validator.py` pour faire passer du code. Si un test semble faux, s'arrêter et demander.

## Conventions de code

- Identifiants, docstrings et commentaires en anglais. Les noms de tables et colonnes du dataset restent en français tels quels. Messages d'erreur renvoyés à l'utilisateur final en français.
- Typage complet, `mypy --strict` sans `# type: ignore` non justifié.
- Fonctions pures quand c'est possible. Les objets coûteux (engine, client LLM, schéma) sont créés une fois dans le `lifespan` FastAPI et injectés, jamais en variables globales de module.
- Configuration lue uniquement via `config.Settings`. Aucun `os.environ` ailleurs.
- Les prompts vivent dans `llm/prompts/*.md`, pas dans des chaînes Python.
- Une PR ou un commit = une étape de la roadmap. Messages de commit au format Conventional Commits (`feat:`, `fix:`, `test:`, `refactor:`, `docs:`, `chore:`).
- Ajouter une dépendance avec `uv add` uniquement après avoir demandé. Préférer la bibliothèque standard.

## Erreurs

Hiérarchie dans `domain/errors.py`, toutes dérivées de `AgentError` :
- `ValidationRejected` : le SQL viole une règle de sécurité (HTTP 422)
- `QueryExecutionError` : erreur SQLite/SQL Server à l'exécution (déclenche une réparation)
- `QueryTimeout` : dépassement du timeout (HTTP 504 si persistant)
- `LLMUnavailable` : fournisseur injoignable après fallback (HTTP 503)
- `RepairExhausted` : nombre max de tentatives atteint (HTTP 422, avec le dernier SQL et la dernière erreur)
- `UnanswerableQuestion` : le LLM indique que la base ne permet pas de répondre (HTTP 200, réponse explicite)

## Tests

- `tests/unit/` : aucun réseau, aucun LLM réel. Le LLM est remplacé par `FakeListChatModel` de `langchain_core.language_models`.
- `tests/integration/` : base SQLite construite depuis un sous-ensemble des CSV dans une fixture, API testée avec `fastapi.testclient.TestClient`, LLM toujours mocké. Marqueur `integration`.
- Tests marqués `llm` : appellent un vrai modèle, exclus de la CI.
- Le validateur a des tests exhaustifs écrits avant son implémentation (liste dans ROADMAP phase 2).

## Façon de travailler

- Avancer phase par phase selon `docs/ROADMAP.md`. À la fin de chaque phase : lancer toutes les vérifications, résumer ce qui a été fait, ce qui reste ouvert, et s'arrêter pour validation humaine avant la phase suivante.
- Avant une modification qui touche plus de trois fichiers, proposer un plan court et attendre l'accord.
- En cas d'ambiguïté sur une règle métier du dataset, consulter `docs/DATASET.md`, puis demander plutôt que supposer.
- Mettre à jour la section "État d'avancement" ci-dessous à la fin de chaque phase.

## État d'avancement

- [x] Structure du repo, pyproject, Dockerfile, docker-compose
- [x] Phase 1 : base locale (build_db, engine, schema)
- [x] Phase 2 : validateur et exécuteur
- [x] Phase 3 : agent minimal LangChain (génération + réparation)
- [x] Phase 4 : contexte additionnel (relations, valeurs distinctes, skills)
- [x] Phase 5 : mémoire de session et follow-up questions
- [x] Phase 6 : API FastAPI
- [x] Phase 7 : observabilité
- [x] Phase 8 : guardrails (NeMo Guardrails 0.24.1, Colang 1.0) + évaluations (offline, online, regression)
- [x] Phase 9 : UI Streamlit
- [ ] Phase 10 : préparation Azure