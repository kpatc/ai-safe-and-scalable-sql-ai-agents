# Règles métier — boutique en ligne

## Chiffre d'affaires
- CA d'une ligne = `quantite * prix_unitaire_paye * (1 - remise_pct / 100.0)`
- Ne jamais utiliser `produits.prix_unitaire` pour le CA (c'est le prix catalogue actuel, pas le prix payé).
- Le CA et les ventes ne comptent que les commandes au statut `livree` ou `expediee`.
- Les statuts `annulee` et `remboursee` sont exclus sauf si la question les vise explicitement.
- Les frais de livraison ne font pas partie du CA sauf demande explicite.

## Marge
- Marge d'une ligne = CA de la ligne − `quantite * cout_achat`

## Clients
- Un « client actif » sur une période a au moins une commande non annulée sur cette période.
- 63 clients n'ont aucune commande. Pour « nombre de clients par X », partir de `clients` avec une jointure externe si la question porte sur tous les clients.

## Dates
- Les dates sont du texte ISO 8601. Utiliser `strftime('%Y', col)` pour l'année, `strftime('%Y-%m', col)` pour le mois.
- Comparer avec `date_commande >= '2024-01-01'` (pas de fonctions de conversion).

## Produits
- Les produits avec `actif = 0` ont pu être vendus avant leur retrait : ne pas les exclure des analyses historiques.

## Saisonnalité
- Novembre et décembre concentrent environ deux fois plus de commandes que les autres mois : comportement attendu, pas une anomalie.
