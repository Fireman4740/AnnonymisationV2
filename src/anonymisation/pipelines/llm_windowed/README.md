# Pipeline `llm_windowed` — anonymisation LLM par fenêtres

| | |
|---|---|
| **Clé** | `llm-windowed-v1` (alias `llm-windowed`, `llm_windowed`) |
| **Capacités** | `spans`, `decisions` |
| **Politique** | non — le modèle décide lui-même de l'action |
| **Profil** | `profile.yaml` de ce dossier (`--profile llm_windowed`) |
| **Hors ligne** | **non** — appelle un backend LLM |

Un appel LLM **par fenêtre** : le document est découpé en segments contigus
d'environ 6 000 caractères, aux frontières de paragraphe puis de phrase, avec
240 caractères de contexte à gauche. Chaque réponse est parsée avec un contrat
JSON strict, puis les spans sont localisés sur le **texte original** et
translatés par l'offset de la fenêtre.

## Pourquoi cette architecture

La campagne `llm-full-v1` a montré qu'un appel unique par document produit des
sorties tronquées sur les documents longs (1/15 sur TAB, 48 erreurs sur
RAT-Bench dans la campagne max-500). Découper borne la longueur de sortie par
appel et permet d'exploiter un budget de génération raisonnable par fenêtre.

## Ce que le code garde pour lui

- **localisation des offsets** : recherche exacte, en mots entiers, dans la
  fenêtre, puis translation vers le texte original ; une entité introuvable
  est écartée avec un avertissement ;
- **légalité de l'action** : validation contre `ALLOWED_ACTIONS` (SPEC-01 §8),
  repli explicite sur `SUPPRESS` ;
- **application au texte** : `apply_decisions`, droite→gauche, comme les
  pipelines déterministes ;
- **déduplication** : une mention vue dans le recouvrement n'est décidée
  qu'une fois par couple `(start, end, catégorie)`.

Une réponse vide, tronquée ou non-JSON est une **erreur nommée** (C3). Une
seule fenêtre en échec met le document en erreur : poursuivre laisserait une
portion du texte non anonymisée.

## Limites connues (v1)

- une entité qui chevauche une frontière n'est rattrapée que si le
  recouvrement de 240 caractères suffit à la faire apparaître entière dans la
  fenêtre suivante ;
- le modèle ne voit pas le document global : les coréférences très lointaines
  restent hors de portée ;
- `expression_mode` toujours `EXPLICIT`, `granularity` toujours `EXACT`,
  `stability` toujours `VOLATILE` ;
- `max_windows=64` : un document qui produirait davantage de fenêtres est mis
  en erreur plutôt que tronqué silencieusement.

## Backend local

`configs/llm/backends.yaml` déclare `qwen_local_box` : serveur vLLM
`qwen3.8-27b` sur `127.0.0.1:18020`, `enable_thinking=false`, clé lue depuis
`VLLM_API_KEY` ou `~/qwen38-27b-rtx3090/.env` sur la box d'évaluation. Le
modèle local respecte la contrainte « < 30 B » du projet.

```bash
anonv2 predict --dataset quasifr --split hard_quasi_id \
  --system llm-windowed --profile llm_windowed \
  --param backend=qwen_local_box --limit 15 --out runs/eval-llm-windowed-quasifr
anonv2 score --run runs/eval-llm-windowed-quasifr --protocol quasifr-v1
```
