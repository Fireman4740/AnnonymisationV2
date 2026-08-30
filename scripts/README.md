# scripts/

Scripts d'acquisition et de maintenance. La logique métier vit dans
`src/anonymisation/` ; ces scripts ne sont que des points d'entrée.

| Script | Rôle | Lot |
|--------|------|-----|
| `download_openpii.py` | Acquisition OpenPII depuis Hugging Face | L2 |
| `download_synthpai.py` | Acquisition SynthPAI | L2 |
| `download_tab.py` | Acquisition TAB | L2 |
| `download_ratbench.py` | Acquisition RAT-Bench (dépôt à identifier) | L2 |
| `download_multiconer.py` | Acquisition MultiCoNER II | L2 |
| `download_meddocan.py` | Acquisition MEDDOCAN (Zenodo) | L2 |
| `build_population_fr.py` | Construction de `fr-hr-2026` / `fr-general-2026` | L3 |
| `build_population_parc.py` | Parc synthétique support, avec queue longue | L3 |
| `generate_corpus.py` | Génération HR / support / forums (SPEC-05) | L4 |

Préférer `anonv2 datasets download <key>` quand l'adaptateur existe : les
scripts sont réservés aux acquisitions qui ne rentrent pas dans le contrat
d'adaptateur.
