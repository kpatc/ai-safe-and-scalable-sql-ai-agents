from __future__ import annotations

from sqlalchemy import Engine, text

from sql_ai_agent.db.schema import DatabaseSchema

_LOW_CARDINALITY_COLS = frozenset(
    {"statut", "mode_paiement", "canal_acquisition", "region", "ville", "nom"}
)

_TOKENS_PER_CHAR = 4


def _schema_compact(schema: DatabaseSchema) -> str:
    lines: list[str] = []
    for tbl in schema.tables:
        col_parts = []
        for col in tbl.columns:
            flags = []
            if col.primary_key:
                flags.append("PK")
            if col.nullable:
                flags.append("NULL")
            suffix = " " + " ".join(flags) if flags else ""
            col_parts.append(f"{col.name} {col.type}{suffix}")
        lines.append(f"{tbl.name}({', '.join(col_parts)})")
    return "\n".join(lines)


def _fk_relations(schema: DatabaseSchema) -> str:
    lines: list[str] = []
    for tbl in schema.tables:
        for fk in tbl.foreign_keys:
            lines.append(f"{tbl.name}.{fk.column} -> {fk.ref_table}.{fk.ref_column}")
    return "\n".join(lines)


def _load_distinct_values(
    engine: Engine,
    schema: DatabaseSchema,
    max_values: int,
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for tbl in schema.tables:
        for col in tbl.columns:
            if col.name not in _LOW_CARDINALITY_COLS:
                continue
            # Use parameterized query with introspection-sourced identifiers
            # (table and column names come from inspector, never from user input)
            quoted_tbl = f'"{tbl.name}"'
            quoted_col = f'"{col.name}"'
            stmt = text(
                f"SELECT DISTINCT {quoted_col} FROM {quoted_tbl} "
                f"WHERE {quoted_col} IS NOT NULL LIMIT :lim"
            )
            with engine.connect() as conn:
                rows = conn.execute(stmt, {"lim": max_values}).fetchall()
            key = f"{tbl.name}.{col.name}"
            result[key] = [str(r[0]) for r in rows]
    return result


def _distinct_values_block(distinct: dict[str, list[str]]) -> str:
    if not distinct:
        return ""
    lines = [f"{k}: {', '.join(v)}" for k, v in distinct.items() if v]
    return "Valeurs distinctes :\n" + "\n".join(lines)


def _dialect_hints(dialect: str) -> str:
    if dialect == "sqlite":
        return (
            "Conventions SQLite : dates stockées en TEXT ISO 8601. "
            "Utiliser strftime('%Y', col) pour l'année, "
            "strftime('%Y-%m', col) pour le mois. "
            "Comparer avec date_col >= '2024-01-01'."
        )
    return ""


def build_context(
    schema: DatabaseSchema,
    engine: Engine,
    skills: str,
    max_values: int = 25,
    max_tokens: int = 4000,
) -> str:
    schema_block = _schema_compact(schema)
    relations_block = _fk_relations(schema)
    hints_block = _dialect_hints(schema.dialect)

    distinct = _load_distinct_values(engine, schema, max_values)
    distinct_block = _distinct_values_block(distinct)

    # Budget enforcement: trim distinct values then skills, never schema/relations
    mandatory = "\n\n".join(
        p for p in [schema_block, relations_block, hints_block] if p
    )
    mandatory_tokens = len(mandatory) // _TOKENS_PER_CHAR

    budget_left = max_tokens - mandatory_tokens
    distinct_tokens = len(distinct_block) // _TOKENS_PER_CHAR
    skills_tokens = len(skills) // _TOKENS_PER_CHAR

    if distinct_tokens + skills_tokens <= budget_left:
        optional = "\n\n".join(p for p in [distinct_block, skills] if p)
    elif skills_tokens <= budget_left:
        # Drop distinct values, keep skills
        optional = skills
    else:
        # Truncate skills to fit
        char_budget = budget_left * _TOKENS_PER_CHAR
        optional = skills[:char_budget]

    return "\n\n".join(p for p in [mandatory, optional] if p)
