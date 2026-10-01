from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from sql_ai_agent.db.schema import DatabaseSchema
from sql_ai_agent.domain.errors import ValidationRejected

_WRITE_NODE_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Pragma,
    exp.Attach,
    exp.Detach,
    exp.Command,
)

_FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}
)

_SYSTEM_TABLES: frozenset[str] = frozenset({"sqlite_master", "sqlite_schema"})


@dataclass(frozen=True)
class ValidatedQuery:
    sql: str
    tables: frozenset[str]
    limit_applied: bool


def _is_read_root(node: exp.Expr) -> bool:
    if isinstance(node, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        return True
    if isinstance(node, exp.With):
        return isinstance(
            node.expression, (exp.Select, exp.Union, exp.Intersect, exp.Except)
        )
    return False


def _apply_limit(tree: exp.Expr, max_rows: int) -> tuple[exp.Expr, bool]:
    limit_node = tree.find(exp.Limit)

    if limit_node is None:
        if isinstance(tree, exp.Select):
            return tree.limit(max_rows), True
        if isinstance(tree, exp.With) and isinstance(tree.expression, exp.Select):
            new_sel = tree.expression.limit(max_rows)
            tree.set("expression", new_sel)
            return tree, True
        # UNION / INTERSECT / EXCEPT — serialize and re-parse with LIMIT appended
        raw = tree.sql(dialect="sqlite")
        with_limit = f"SELECT * FROM ({raw}) AS __outer LIMIT {max_rows}"
        reparsed = sqlglot.parse_one(with_limit, read="sqlite")
        return reparsed, True

    # Cap existing LIMIT
    try:
        current: int = int(limit_node.expression.this)
    except (AttributeError, TypeError, ValueError):
        current = max_rows + 1

    if current > max_rows:
        limit_node.set("expression", exp.Literal.number(max_rows))
        return tree, True

    return tree, False


def validate(
    sql: str,
    schema: DatabaseSchema,
    max_rows: int,
    dialect: str = "sqlite",
) -> ValidatedQuery:
    # Rule 1 — parse
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except sqlglot.errors.ParseError as exc:
        raise ValidationRejected(f"SQL invalide : {exc}") from exc

    # Rule 2 — exactly one non-empty statement (lone ';' is tolerated)
    non_empty: list[exp.Expr] = [s for s in statements if s is not None]
    if len(non_empty) == 0:
        raise ValidationRejected("La requête est vide.")
    if len(non_empty) > 1:
        raise ValidationRejected("Une seule instruction est autorisée.")

    tree: exp.Expr = non_empty[0]

    # Rule 3 — root must be a read operation
    if not _is_read_root(tree):
        raise ValidationRejected("Seules les requêtes SELECT sont autorisées.")

    # Rule 4 — no write/DDL nodes anywhere in the tree (including CTEs)
    for write_type in _WRITE_NODE_TYPES:
        node = tree.find(write_type)
        if node is not None:
            raise ValidationRejected(
                f"Instruction interdite dans la requête : {write_type.__name__}"
            )

    # Rule 5 — all referenced tables must be in schema.allowed_tables
    cte_names: set[str] = {
        cte.alias.lower() for cte in tree.find_all(exp.CTE) if cte.alias
    }

    allowed = schema.allowed_tables
    referenced: set[str] = set()

    for tbl in tree.find_all(exp.Table):
        name = tbl.name.lower() if tbl.name else ""
        if not name or name in cte_names:
            continue
        if name in _SYSTEM_TABLES:
            raise ValidationRejected(
                f"Accès interdit à la table système : {tbl.name!r}"
            )
        if name not in allowed:
            raise ValidationRejected(f"Table inconnue ou non autorisée : {tbl.name!r}")
        referenced.add(name)

    # Rule 6 — forbidden functions
    for func_node in tree.find_all(exp.Anonymous):
        fname = func_node.name.lower() if func_node.name else ""
        if fname in _FORBIDDEN_FUNCTIONS:
            raise ValidationRejected(f"Fonction interdite : {func_node.name!r}")

    # Rule 7 — limit enforcement
    tree, limit_applied = _apply_limit(tree, max_rows)

    final_sql = tree.sql(dialect=dialect)
    return ValidatedQuery(
        sql=final_sql, tables=frozenset(referenced), limit_applied=limit_applied
    )
