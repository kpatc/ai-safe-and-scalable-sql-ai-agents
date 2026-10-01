# Dataset : boutique en ligne (synthétique)

Données générées par `gen.py` (graine fixe 42), période 2023-01-01 à 2025-12-31. Les CSV sont dans `data/raw/`, encodés en UTF-8, séparateur virgule, chaîne vide = NULL.

## Tables

| Table | Lignes | Clé primaire |
|---|---|---|
| categories | 6 | categorie_id |
| produits | 44 | produit_id |
| clients | 800 | client_id |
| commandes | 2 889 | commande_id |
| lignes_commande | 4 974 | ligne_id |
| avis | 915 | avis_id |

## DDL de référence

```sql
CREATE TABLE categories (
  categorie_id INTEGER PRIMARY KEY,
  nom TEXT NOT NULL
);
CREATE TABLE produits (
  produit_id INTEGER PRIMARY KEY,
  nom TEXT NOT NULL,
  categorie_id INTEGER NOT NULL REFERENCES categories(categorie_id),
  prix_unitaire REAL NOT NULL,        -- prix catalogue TTC en euros
  cout_achat REAL NOT NULL,
  stock INTEGER NOT NULL,
  actif INTEGER NOT NULL,             -- 1 = en vente, 0 = retiré du catalogue
  date_ajout TEXT NOT NULL            -- ISO 8601 (YYYY-MM-DD)
);
CREATE TABLE clients (
  client_id INTEGER PRIMARY KEY,
  prenom TEXT, nom TEXT,
  email TEXT,                         -- NULL pour 31 clients
  ville TEXT, region TEXT,
  date_naissance TEXT,                -- NULL pour 96 clients
  date_inscription TEXT NOT NULL,
  canal_acquisition TEXT              -- recherche, reseaux_sociaux, parrainage, publicite, direct
);
CREATE TABLE commandes (
  commande_id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(client_id),
  date_commande TEXT NOT NULL,
  statut TEXT NOT NULL,               -- livree, expediee, annulee, remboursee
  mode_paiement TEXT,                 -- carte, paypal, virement
  remise_pct INTEGER NOT NULL,        -- 0, 5, 10, 15 ou 20 ; s'applique à toute la commande
  frais_livraison REAL NOT NULL       -- 0.0 ou 4.99
);
CREATE TABLE lignes_commande (
  ligne_id INTEGER PRIMARY KEY,
  commande_id INTEGER NOT NULL REFERENCES commandes(commande_id),
  produit_id INTEGER NOT NULL REFERENCES produits(produit_id),
  quantite INTEGER NOT NULL,
  prix_unitaire_paye REAL NOT NULL    -- peut être inférieur au prix catalogue (promo)
);
CREATE TABLE avis (
  avis_id INTEGER PRIMARY KEY,
  client_id INTEGER NOT NULL REFERENCES clients(client_id),
  produit_id INTEGER NOT NULL REFERENCES produits(produit_id),
  note INTEGER NOT NULL CHECK (note BETWEEN 1 AND 5),
  date_avis TEXT NOT NULL
);
```

## Règles métier

Ces règles sont la source de `skills/boutique.md`.

- Chiffre d'affaires d'une ligne : `quantite * prix_unitaire_paye * (1 - remise_pct / 100.0)`. Ne pas utiliser `produits.prix_unitaire`, qui est le prix catalogue actuel.
- Le chiffre d'affaires, les ventes et le panier moyen ne comptent que les commandes au statut `livree` ou `expediee`. Les statuts `annulee` et `remboursee` sont exclus sauf si la question les vise explicitement.
- Les frais de livraison ne font pas partie du chiffre d'affaires sauf demande explicite.
- Marge d'une ligne : chiffre d'affaires de la ligne moins `quantite * cout_achat`.
- Un "client actif" sur une période a au moins une commande non annulée sur cette période.
- 63 clients n'ont aucune commande. Pour "nombre de clients par X", partir de `clients` avec une jointure externe si la question porte sur tous les clients.
- Les dates sont du texte ISO : année avec `strftime('%Y', date_commande)`, mois avec `strftime('%Y-%m', date_commande)`. Comparer des dates avec `date_commande >= '2024-01-01'`.
- Les produits avec `actif = 0` ont pu être vendus avant leur retrait : ne pas les exclure des analyses historiques.
- Novembre et décembre concentrent environ deux fois plus de commandes que les autres mois : comportement attendu, pas une anomalie.

## Requête de référence

```sql
-- Chiffre d'affaires par année
SELECT strftime('%Y', c.date_commande) AS annee,
       ROUND(SUM(l.quantite * l.prix_unitaire_paye * (1 - c.remise_pct / 100.0)), 2) AS chiffre_affaires
FROM commandes c
JOIN lignes_commande l ON l.commande_id = c.commande_id
WHERE c.statut IN ('livree', 'expediee')
GROUP BY annee
ORDER BY annee;
```