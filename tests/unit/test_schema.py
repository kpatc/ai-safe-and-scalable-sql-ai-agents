from __future__ import annotations

from sql_ai_agent.db.schema import DatabaseSchema


def test_load_schema_returns_six_tables(schema: DatabaseSchema) -> None:
    assert len(schema.tables) == 6


def test_lignes_commande_has_two_fks(schema: DatabaseSchema) -> None:
    tbl = schema.get_table("lignes_commande")
    assert tbl is not None
    assert len(tbl.foreign_keys) == 2
    ref_tables = {fk.ref_table for fk in tbl.foreign_keys}
    assert ref_tables == {"commandes", "produits"}


def test_allowed_tables_property(schema: DatabaseSchema) -> None:
    allowed = schema.allowed_tables
    assert "produits" in allowed
    assert "clients" in allowed
    assert len(allowed) == 6


def test_row_count(schema: DatabaseSchema) -> None:
    tbl = schema.get_table("produits")
    assert tbl is not None
    assert tbl.row_count == 2
