# scripts/

Scripts d'acquisition et de maintenance. La logique métier vit dans
`src/anonymisation/` ; ces scripts ne sont que des points d'entrée.

| Script | Rôle |
|--------|------|
| `check_no_data_committed.py` | Contrôle d'intégrité CI interdisant la version de données brutes ou de secrets |

Pour l'acquisition et l'ingestion des jeux de données, utiliser directement la CLI :
`anonv2 datasets ingest <key>` ou `anonv2 datasets download <key>`.
