from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import Engine, MetaData, Table, func, inspect, select


class ColumnInfo(BaseModel):
    name: str
    type: str
    nullable: bool
    primary_key: bool


class ForeignKey(BaseModel):
    column: str
    ref_table: str
    ref_column: str


class TableInfo(BaseModel):
    name: str
    columns: list[ColumnInfo]
    foreign_keys: list[ForeignKey]
    row_count: int


class DatabaseSchema(BaseModel):
    tables: list[TableInfo]
    dialect: str

    @property
    def allowed_tables(self) -> set[str]:
        return {t.name.lower() for t in self.tables}

    def get_table(self, name: str) -> TableInfo | None:
        name_lower = name.lower()
        return next((t for t in self.tables if t.name.lower() == name_lower), None)


def _row_count(engine: Engine, table_name: str) -> int:
    meta = MetaData()
    tbl = Table(table_name, meta, autoload_with=engine)
    with engine.connect() as conn:
        result = conn.execute(select(func.count()).select_from(tbl))
        row = result.fetchone()
        return int(row[0]) if row else 0


def load_schema(engine: Engine, include: list[str] | None = None) -> DatabaseSchema:
    inspector = inspect(engine)
    dialect = engine.dialect.name

    if include is not None:
        table_names = include
    else:
        table_names = [
            n for n in inspector.get_table_names() if not n.startswith("sqlite_")
        ]

    tables: list[TableInfo] = []
    for table_name in table_names:
        raw_cols = inspector.get_columns(table_name)
        pk_set: set[str] = set(
            inspector.get_pk_constraint(table_name).get("constrained_columns", [])
        )

        columns = [
            ColumnInfo(
                name=str(col["name"]),
                type=str(col["type"]),
                nullable=bool(col.get("nullable", True)),
                primary_key=str(col["name"]) in pk_set,
            )
            for col in raw_cols
        ]

        raw_fks = inspector.get_foreign_keys(table_name)
        foreign_keys = [
            ForeignKey(
                column=fk["constrained_columns"][0],
                ref_table=fk["referred_table"],
                ref_column=fk["referred_columns"][0],
            )
            for fk in raw_fks
            if fk.get("constrained_columns") and fk.get("referred_columns")
        ]

        count = _row_count(engine, table_name)

        tables.append(
            TableInfo(
                name=table_name,
                columns=columns,
                foreign_keys=foreign_keys,
                row_count=count,
            )
        )

    return DatabaseSchema(tables=tables, dialect=dialect)
