# data/ — non versionné

Aucune donnée n'est versionnée dans ce dépôt (règle L1 de SPEC-09). La
traçabilité passe par les manifestes `configs/datasets/*.yaml` et les checksums
des `.manifest.lock.json`.

| Répertoire | Contenu | Produit par |
|------------|---------|-------------|
| `raw/` | Sources telles que téléchargées | `anonv2 datasets download` |
| `interim/` | Artefacts intermédiaires (populations résolues) | moteur de risque |
| `processed/` | Format pivot SPEC-02 (`*.jsonl`) | `anonv2 datasets ingest` |
| `external/` | Corpus sous licence restrictive (MIMIC-III…) | acquisition manuelle |

**Interdictions absolues** : commiter un fichier de `data/`, y placer des
données réelles non couvertes par une base légale documentée, ou y écrire une
sortie d'attaquant portant sur des personnes réelles (SPEC-08 E3).
