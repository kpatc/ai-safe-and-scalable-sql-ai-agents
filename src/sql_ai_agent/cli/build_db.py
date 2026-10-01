from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
from pathlib import Path

DDL_STATEMENTS = [
    """CREATE TABLE categories (
  categorie_id INTEGER PRIMARY KEY,
  nom TEXT NOT NULL
)""",
    """CREATE TABLE produits (
  produit_id INTEGER PRIMARY KEY,
  nom TEXT NOT NULL,
  categorie_id INTEGER NOT NULL REFERENCES categories(categorie_id),
  prix_unitaire REAL NOT NULL,
  cout_achat REAL NOT NULL,
  stock INTEGER NOT NULL,
  actif INTEGER NOT NULL,
  date_ajout TEXT NOT NULL
)""",
    """CREATE TABLE clients (
  client_id INTEGER PRIMARY KEY,
  prenom TEXT,
  nom TEXT,
  email TEXT,
  ville TEXT,
  region TEXT,
  date_naissance TEXT,
  date_inscription TEXT NOT NULL,
  canal_acquisition TEXT
)""",
    """CREATE TABLE commandes (
  commande_id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(client_id),
  date_commande TEXT NOT NULL,
  statut TEXT NOT NULL,
  mode_paiement TEXT,
  remise_pct INTEGER NOT NULL,
  frais_livraison REAL NOT NULL
)""",
    """CREATE TABLE lignes_commande (
  ligne_id INTEGER PRIMARY KEY,
  commande_id INTEGER NOT NULL REFERENCES commandes(commande_id),
  produit_id INTEGER NOT NULL REFERENCES produits(produit_id),
  quantite INTEGER NOT NULL,
  prix_unitaire_paye REAL NOT NULL
)""",
    """CREATE TABLE avis (
  avis_id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(client_id),
  produit_id INTEGER NOT NULL REFERENCES produits(produit_id),
  note INTEGER NOT NULL CHECK (note BETWEEN 1 AND 5),
  date_avis TEXT NOT NULL
)""",
]

INDEX_STATEMENTS = [
    "CREATE INDEX idx_produits_categorie ON produits (categorie_id)",
    "CREATE INDEX idx_commandes_client ON commandes (client_id)",
    "CREATE INDEX idx_commandes_date ON commandes (date_commande)",
    "CREATE INDEX idx_lignes_commande_id ON lignes_commande (commande_id)",
    "CREATE INDEX idx_lignes_produit ON lignes_commande (produit_id)",
    "CREATE INDEX idx_avis_client ON avis (client_id)",
    "CREATE INDEX idx_avis_produit ON avis (produit_id)",
]

# Explicit column definitions — never derive from CSV headers
TABLE_COLUMNS: dict[str, list[str]] = {
    "categories": ["categorie_id", "nom"],
    "produits": [
        "produit_id",
        "nom",
        "categorie_id",
        "prix_unitaire",
        "cout_achat",
        "stock",
        "actif",
        "date_ajout",
    ],
    "clients": [
        "client_id",
        "prenom",
        "nom",
        "email",
        "ville",
        "region",
        "date_naissance",
        "date_inscription",
        "canal_acquisition",
    ],
    "commandes": [
        "commande_id",
        "client_id",
        "date_commande",
        "statut",
        "mode_paiement",
        "remise_pct",
        "frais_livraison",
    ],
    "lignes_commande": [
        "ligne_id",
        "commande_id",
        "produit_id",
        "quantite",
        "prix_unitaire_paye",
    ],
    "avis": ["avis_id", "client_id", "produit_id", "note", "date_avis"],
}

LOAD_ORDER = [
    "categories",
    "produits",
    "clients",
    "commandes",
    "lignes_commande",
    "avis",
]


def _coerce(value: str) -> str | int | float | None:
    """Empty string → NULL; otherwise try int, float, then string."""
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def build_database(csv_dir: Path, output: Path) -> None:
    tmp_path = Path(str(output) + ".tmp")
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    if tmp_path.exists():
        tmp_path.unlink()

    conn = sqlite3.connect(tmp_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = DELETE")

        for ddl in DDL_STATEMENTS:
            conn.execute(ddl)
        conn.commit()

        for table_name in LOAD_ORDER:
            columns = TABLE_COLUMNS[table_name]
            csv_path = csv_dir / f"{table_name}.csv"

            with csv_path.open(encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                rows = [
                    tuple(_coerce(row.get(col, "")) for col in columns)
                    for row in reader
                ]

            if rows:
                col_list = ", ".join(f'"{c}"' for c in columns)
                placeholders = ", ".join("?" * len(columns))
                stmt = (
                    f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})'
                )
                conn.executemany(stmt, rows)
                conn.commit()

            print(f"{table_name}: {len(rows)} rows")

        for idx_stmt in INDEX_STATEMENTS:
            conn.execute(idx_stmt)
        conn.commit()

    except Exception:
        conn.close()
        tmp_path.unlink(missing_ok=True)
        raise
    else:
        conn.close()
        os.replace(tmp_path, output)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the boutique SQLite database from CSV files"
    )
    parser.add_argument(
        "--csv-dir", type=Path, required=True, help="Directory containing CSV files"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Output SQLite database path"
    )
    args = parser.parse_args()
    try:
        build_database(args.csv_dir, args.output)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
