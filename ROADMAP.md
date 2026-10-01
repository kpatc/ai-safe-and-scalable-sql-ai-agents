# Roadmap d'implémentation

Chaque phase se termine par : tests verts, `ruff` et `mypy --strict` propres, mise à jour de "État d'avancement" dans `CLAUDE.md`, puis arrêt pour validation humaine. Les critères d'acceptation sont des conditions de fin, pas des suggestions.

---

## Phase 1 : base locale

Objectif : une base SQLite reproductible et une couche d'accès en lecture seule capable de décrire son propre schéma.

### `cli/build_db.py`
- Commande `sql-agent-build-db --csv-dir PATH --output PATH` (entrée déjà déclarée dans `[project.scripts]`).
- Le schéma DDL est explicite dans le module (types, `PRIMARY KEY`, `REFERENCES`, `CHECK (note BETWEEN 1 AND 5)`), copié de `docs/DATASET.md`. Pas d'inférence de types par pandas.
- Ordre de chargement respectant les FK : categories, produits, clients, commandes, lignes_commande, avis. `PRAGMA foreign_keys = ON` pendant le chargement.
- Chaîne vide dans un CSV -> `NULL`.
- Index sur chaque colonne de clé étrangère et sur `commandes.date_commande`.
- Écriture atomique : construire dans `output + ".tmp"`, puis `os.replace`. Relancer la commande produit un fichier identique et ne laisse jamais de base à moitié écrite.
- `PRAGMA journal_mode = DELETE` à la fin (pas de WAL : le fichier doit pouvoir être ouvert sur un volume en lecture seule).
- Affiche le nombre de lignes par table. Code de sortie non nul en cas d'erreur.

### `db/engine.py`
- `create_readonly_engine(url: str) -> Engine`.
- Pour SQLite : refuser une URL sans `mode=ro` (lever une erreur au démarrage, pas un warning).
- Listener `connect` qui exécute `PRAGMA query_only = ON` et `PRAGMA foreign_keys = ON`.
- URL locale hors Docker : `sqlite:///file:data/boutique.db?mode=ro&uri=true`.

### `db/schema.py`
- Introspection via `sqlalchemy.inspect`, jamais via des requêtes sur `sqlite_master` construites à la main.
- Modèles Pydantic : `ColumnInfo(name, type, nullable, primary_key)`, `ForeignKey(column, ref_table, ref_column)`, `TableInfo(name, columns, foreign_keys, row_count)`, `DatabaseSchema(tables, dialect)`.
- `load_schema(engine, include: list[str] | None) -> DatabaseSchema`. Les tables internes (`sqlite_%`) sont exclues.
- `DatabaseSchema.allowed_tables` : ensemble des noms en minuscules, utilisé par le validateur.
- Le schéma est chargé une fois au démarrage et mis en cache.

### Critères d'acceptation
- `uv run sql-agent-build-db ...` crée la base avec 6 tables et les comptes de `docs/DATASET.md`.
- Test : une tentative d'`INSERT` via `create_readonly_engine` échoue (erreur SQLite "readonly" ou "query_only").
- Test : `load_schema` retourne 6 tables, et `lignes_commande` a deux FK (vers `commandes` et `produits`).

---

## Phase 2 : validateur et exécuteur

Objectif : rien d'autre qu'une lecture bornée ne peut atteindre la base.

### `safety/validator.py`
Écrire d'abord `tests/unit/test_validator.py`, puis l'implémentation.

`validate(sql: str, schema: DatabaseSchema, max_rows: int, dialect: str) -> ValidatedQuery` où `ValidatedQuery(sql: str, tables: set[str], limit_applied: bool)`. Lève `ValidationRejected(reason)`.

Règles, dans cet ordre :
1. Parse avec `sqlglot.parse(sql, read=dialect)`. Échec de parsing -> rejet.
2. Exactement une instruction non vide. Un `;` final seul est toléré.
3. La racine est `exp.Select`, `exp.Union`/`exp.Intersect`/`exp.Except`, ou un `WITH` dont la requête finale est un `SELECT`.
4. Aucun nœud de type écriture ou DDL n'apparaît dans l'arbre, y compris dans une CTE ou une sous-requête : `Insert`, `Update`, `Delete`, `Merge`, `Create`, `Drop`, `Alter`, `TruncateTable`, `Pragma`, `Attach`, `Detach`, `Command` (sqlglot range `VACUUM` dans `Command`). Ce parcours de l'arbre complet est indispensable : `WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x` a une racine `Select` pour sqlglot.
5. Toutes les tables référencées (`exp.Table`) appartiennent à `schema.allowed_tables`. Les noms de CTE définis dans la requête sont exclus de ce contrôle. `sqlite_master` et `sqlite_schema` sont toujours refusées.
6. Fonctions interdites : `load_extension`, `readfile`, `writefile`, `edit`, `fts3_tokenizer` (comparaison insensible à la casse).
7. Limite : sans `LIMIT`, en ajouter un égal à `max_rows`. Avec un `LIMIT` supérieur à `max_rows`, le ramener à `max_rows`. Régénérer le SQL avec `expression.sql(dialect=dialect)`.

Cas de test minimum (chacun un test paramétré) :
- acceptés : SELECT simple, jointure 3 tables, CTE, UNION, sous-requête corrélée, fenêtre `OVER`, `strftime`, alias de table, `;` final
- rejetés : INSERT, UPDATE, DELETE, DROP TABLE, CREATE TABLE, ALTER, PRAGMA, ATTACH DATABASE, deux SELECT séparés par `;`, `SELECT 1; DROP TABLE clients`, `WITH x AS (DELETE FROM clients RETURNING *) SELECT * FROM x`, VACUUM, DETACH, table inconnue, `sqlite_master`, `load_extension('x')`, chaîne vide, commentaire seul, SQL non parsable
- limite : ajout quand absente, réduction quand trop haute, conservation quand plus basse

### `db/executor.py`
- `execute(engine, query: ValidatedQuery, timeout_s: float) -> ExecutionResult(columns, rows, row_count, truncated, duration_ms)`.
- SQLite n'a pas de timeout de requête natif : installer `set_progress_handler` sur la connexion DBAPI brute avec une échéance calculée au début de l'exécution, retourner une valeur non nulle après l'échéance, et retirer le handler dans un `finally`. Convertir l'interruption en `QueryTimeout`.
- Toute autre erreur DBAPI devient `QueryExecutionError(message)` avec le message d'origine, qui servira au prompt de réparation.
- Les valeurs non sérialisables JSON (Decimal, date) sont converties à la frontière API, pas ici.

### Critères d'acceptation
- Tous les cas ci-dessus passent.
- Test : une requête lente artificielle (CTE récursive de comptage) est interrompue sous `timeout_s + 0.5` secondes.

---

## Phase 3 : agent minimal LangChain

Objectif : question -> SQL -> résultat, avec réparation automatique en cas d'échec.

### `llm/client.py`
- `build_chat_model(settings) -> BaseChatModel` : `ChatOpenAI(model, base_url, api_key, temperature=0, timeout, max_retries=2)`.
- Si `LLM_FALLBACK_MODEL` est défini : `primary.with_fallbacks([fallback])`.

### `llm/prompts/`
- `generate.md` : rôle, dialecte, règles de sortie, puis variables `{schema}`, `{context}`, `{question}`. Règles : un seul `SELECT`, pas de commentaire, répondre exactement `UNANSWERABLE: <raison>` si la base ne permet pas de répondre.
- `repair.md` : variables `{schema}`, `{question}`, `{failed_sql}`, `{error}`.
- Chargés avec `ChatPromptTemplate.from_messages`, le texte venant des fichiers. Un test vérifie que chaque template contient bien ses variables.

### `llm/parsing.py`
- Extrait le SQL d'un bloc ```sql``` s'il existe, sinon du texte brut. Détecte le préfixe `UNANSWERABLE:`.

### `agent/sql_agent.py`
- Classe `SqlAgent(chat_model, engine, schema, settings)`, méthode `ask(question: str, session_id: str | None) -> QueryResult`.
- Boucle : générer -> parser -> valider -> exécuter. Sur `ValidationRejected` ou `QueryExecutionError`, appeler le prompt de réparation avec l'erreur, jusqu'à `AGENT_MAX_REPAIR_ATTEMPTS`. Puis `RepairExhausted`.
- `QueryTimeout` n'est pas réparé automatiquement plus d'une fois (une tentative de simplification, puis erreur).
- Chaque tentative est enregistrée dans `AgentTrace` (sql, erreur, durée, tokens via `response.usage_metadata`).
- Dans cette phase, le contexte se limite au schéma brut (tables et colonnes).

### Critères d'acceptation
- Tests unitaires avec `FakeListChatModel` : succès direct, succès après une réparation, `RepairExhausted`, `UNANSWERABLE`, SQL dangereux renvoyé par le LLM rejeté puis réparé.
- Test marqué `llm` : "Combien de clients à Lyon ?" retourne une ligne avec une valeur entière.

---

## Phase 4 : contexte additionnel

Objectif : donner au LLM ce que le schéma brut ne dit pas, sans dépasser un budget de tokens.

### `agent/context.py`
`build_context(schema, distinct_values, skills, question) -> str`, assemblé dans cet ordre :
1. Schéma compact : une ligne par table, `table(col TYPE PK, col TYPE NULL, ...)`.
2. Relations explicites : `lignes_commande.commande_id -> commandes.commande_id`, etc.
3. Valeurs distinctes des colonnes texte à faible cardinalité (seuil configurable, défaut 25 valeurs) : `statut`, `mode_paiement`, `canal_acquisition`, `region`, `ville`, `categories.nom`. Calculées une fois au démarrage avec des requêtes paramétrées sur des identifiants issus de l'introspection.
4. Conventions du dialecte : dates stockées en TEXT ISO 8601, utiliser `strftime('%Y', col)` et `date()`.
5. Règles métier issues de `skills/boutique.md`.

- Budget : estimer les tokens (approximation 4 caractères par token suffit) et tronquer d'abord les valeurs distinctes, puis les skills, jamais le schéma ni les relations. Logguer la taille finale.
- Le contexte est mis en cache par processus, seule la question varie.

### `agent/skills.py` et `skills/boutique.md`
- Un skill = un fichier Markdown. Chargement de tous les fichiers de `skills/` au démarrage.
- `skills/boutique.md` contient les règles de `docs/DATASET.md`, section "Règles métier", reformulées en consignes courtes.

### Critères d'acceptation
- Test : le contexte généré contient les 6 relations FK et les 4 valeurs de `statut`.
- Test : avec un budget artificiellement bas, le schéma reste complet.
- Evals (phase 8) : les questions sur le chiffre d'affaires excluent les commandes annulées et remboursées. À vérifier manuellement en fin de phase avec 5 questions.

---

## Phase 5 : mémoire de session

Objectif : permettre "Quel est le CA de 2024 ?" puis "Et pour 2025 ?" puis "Détaille par catégorie".

### `agent/memory.py`
- Modèle `Turn(question, sql, columns, row_count, created_at)`. On ne stocke jamais les lignes de résultat.
- Protocole `SessionStore` : `get(session_id) -> list[Turn]`, `append(session_id, turn)`, `clear(session_id)`.
- Implémentation `InMemorySessionStore` : dictionnaire protégé par un `threading.Lock`, TTL d'inactivité (défaut 30 min), N derniers tours conservés (défaut 5), nombre maximal de sessions (éviction LRU).
- Le protocole permet de brancher Redis ou une table plus tard sans toucher à l'agent.

### Intégration dans le prompt
- `generate.md` reçoit un `MessagesPlaceholder("history")` : pour chaque tour, un `HumanMessage(question)` et un `AIMessage(sql)`.
- Le SQL précédent est la partie la plus utile : il permet au modèle de modifier la requête existante au lieu de repartir de zéro.
- Ajouter dans le prompt une consigne : une question qui fait référence à "ça", "et pour", "détaille" s'interprète par rapport au dernier tour.
- Seuls les tours réussis entrent en mémoire.
- Sans `session_id`, l'agent fonctionne sans mémoire. Avec un `session_id` inconnu, une session est créée.

### Limite connue à documenter dans le README
`InMemorySessionStore` ne fonctionne qu'avec une seule réplique. Sur Azure Container Apps, fixer `maxReplicas: 1` ou passer à un store partagé.

### Critères d'acceptation
- Tests unitaires du store : TTL, éviction, limite de tours, concurrence basique (plusieurs threads).
- Test agent avec `FakeListChatModel` : au deuxième appel de la même session, le prompt envoyé contient la question et le SQL du premier tour.
- Test marqué `llm` : la séquence des trois questions ci-dessus produit au troisième tour une requête qui contient `GROUP BY` et filtre sur 2025.

---

## Phase 6 : API FastAPI

### Endpoints
- `POST /v1/query` : corps `{question: str (1..500 car.), session_id: str | None}`. Réponse `{session_id, sql, columns, rows, row_count, truncated, attempts, latency_ms}` ou `{session_id, unanswerable: true, reason}`.
- `DELETE /v1/sessions/{session_id}` : 204.
- `GET /health` : liveness, ne touche ni base ni LLM.
- `GET /ready` : exécute `SELECT 1` et vérifie que la config LLM est présente (pas d'appel LLM).

### Implémentation
- `lifespan` : settings, engine, schéma, valeurs distinctes, skills, client LLM, store de sessions, agent. Fermeture propre de l'engine.
- `api/errors.py` : handlers pour la hiérarchie `AgentError`, réponse `{error: code, message}` en français. Jamais de traceback dans la réponse.
- Middleware `request_id` : lit `X-Request-ID` ou en génère un, le renvoie dans la réponse et l'ajoute aux logs.
- L'agent est synchrone : appeler `agent.ask` via `run_in_threadpool` dans une route `async`, ou déclarer la route en `def`.
- OpenAPI propre : modèles de réponse et exemples.

### Critères d'acceptation
- Tests d'intégration avec `TestClient` et LLM mocké : succès, question vide (422), SQL rejeté (422), LLM indisponible (503), suite de deux questions avec `session_id`.

---

## Phase 7 : observabilité

- `observability/logging.py` : formatter JSON stdlib (pas de nouvelle dépendance), champs `timestamp, level, logger, message, request_id, session_id` plus champs spécifiques.
- Un événement par tentative : `agent.attempt` avec `attempt, sql_hash, valid, error_type, duration_ms, prompt_tokens, completion_tokens`.
- Un événement par requête : `agent.completed` avec `attempts, total_duration_ms, row_count, outcome`.
- Le SQL complet est loggué au niveau DEBUG uniquement. Les lignes de résultat jamais.
- `LOG_FORMAT=human` pour le développement local.

---

## Phase 8 : évaluations

- `evals/questions.yaml` : `id`, `question`, `reference_sql`, `difficulty` (easy, medium, hard), `tags`, et pour les follow-ups un champ `session` qui groupe les questions à rejouer dans l'ordre.
- `evals/run_evals.py` : exécute le SQL de référence et le SQL de l'agent, compare les résultats en multiset de lignes (ordre ignoré sauf si la référence contient `ORDER BY`), arrondi des flottants à 2 décimales.
- Sortie : précision globale et par difficulté, latence p50/p95, tokens moyens, liste des échecs avec les deux SQL. Écrit un JSON horodaté dans `evals/results/`.
- Les questions `UNANSWERABLE` attendues comptent comme réussies si l'agent refuse.

---

## Phase 9 : UI Streamlit

- `ui/app.py` appelle uniquement l'API via httpx (`API_URL`). Aucun import de `sql_ai_agent`.
- Historique de conversation dans `st.session_state`, `session_id` conservé pour la session navigateur, bouton "Nouvelle conversation" qui appelle `DELETE /v1/sessions/{id}`.
- Affiche le SQL (repliable), le tableau, et un graphique simple quand le résultat a une colonne temporelle ou catégorielle et une colonne numérique.

---

## Phase 10 : préparation Azure

- Ajouter `pyodbc` (extra `mssql`) et le driver ODBC 18 de Microsoft dans une variante de l'image.
- `DATABASE_URL` Azure SQL au format `mssql+pyodbc://...`, utilisateur `db_datareader`. Le validateur prend le dialecte depuis l'engine (`tsql`).
- Le timeout passe par l'option de requête du driver au lieu du progress handler SQLite : isoler cette différence dans `db/executor.py`.
- Secrets dans Azure Key Vault ou secrets Container Apps, injectés en variables d'environnement.
- Workflow GitHub Actions : lint, typage, tests, build et push de l'image.