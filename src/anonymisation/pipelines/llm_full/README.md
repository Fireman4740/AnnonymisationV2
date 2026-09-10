# Pipeline `llm_full` — anonymisation intégrale par LLM

| | |
|---|---|
| **Clé** | `llm-full-v1` (alias `llm-full`, `llm`) |
| **Capacités** | `spans`, `decisions` |
| **Politique** | non — le modèle décide lui-même de l'action |
| **Profil** | `profile.yaml` de ce dossier (`--profile llm_full`) |
| **Hors ligne** | **non** — appelle un backend LLM |

Un **seul appel LLM par document** fait la détection, le choix de l'action
(SUPPRESS / PSEUDONYMIZE / GENERALIZE) et le texte de remplacement. Le prompt
et son parseur sont locaux à ce pipeline (`prompts.py`) ; le client, le cache
et les backends sont l'infrastructure partagée `anonymisation.llm`.

## Ce que le code garde pour lui

Jamais confié au modèle, par conception :

- **la localisation des offsets** — le span renvoyé est recherché tel quel dans
  le texte original ; une entité introuvable est écartée, jamais approximée ;
- **la légalité de l'action** — validée contre `ALLOWED_ACTIONS` (SPEC-01 §8),
  repli explicite sur `SUPPRESS` et journalisation ;
- **l'application au texte** — `apply_decisions`, droite→gauche, comme les
  pipelines déterministes.

Une réponse vide, tronquée ou non-JSON est une **erreur nommée**, jamais
« aucune entité trouvée » (contrainte C3 de SPEC-10).

## Limites connues (v1)

- `expression_mode` toujours `EXPLICIT` : seules les entités ancrées
  littéralement dans le texte sont détectables ;
- `granularity` `EXACT` et `stability` `VOLATILE` par défaut : le modèle n'est
  pas interrogé sur ces axes ;
- **documents longs** : l'appel unique produit un JSON tronqué au-delà de
  ~10 000 caractères (1 document sur 15 en erreur sur TAB). Une architecture à
  fenêtre glissante est la suite naturelle — dans **son propre dossier**.

## Backends

Déclarés dans `configs/llm/backends.yaml`. `qwen_local` (défaut) est un serveur
vLLM local ; `stub` renvoie une réponse canned sans réseau et sert au contrat
de test.

```bash
anonv2 predict --dataset <ds> --split <s> --system llm-full   --profile llm_full --param backend=qwen_local
```

Évaluation : `documentation/rapport/05-evaluation-llm-full-v1.md`.
