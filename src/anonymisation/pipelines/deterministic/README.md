# Pipeline `deterministic` — le noyau de SPEC-10

| | |
|---|---|
| **Clé** | `deterministic-v1` (alias `deterministic`) |
| **Capacités** | `spans`, `decisions`, `traces`, `risk`, `policy`, `gold_aware` |
| **Politique** | **oui** — `--policy P0..P4` requis |
| **Profil** | `profile.yaml` de ce dossier (`--profile deterministic`) |
| **Hors ligne** | oui — aucun LLM, aucun GPU, aucun réseau |

Enveloppe la classe `Pipeline` (`anonymisation.pipeline.orchestrator`) et ses
8 étapes : DETECT → FUSE → ASSESS → PLAN → TRANSFORM → VALIDATE (+ AUDIT et
REWRITE, désactivées). C'est le **profil par défaut** et la contrainte C1 :
il doit traiter 100 % des documents avec 0 % d'erreur, sans modèle.

Le profil est la source de configuration des étapes ; `profile.yaml` documente
chaque choix. La garde de `profiles.py` interdit d'y activer NER, relecteur
LLM, audit, réécriture ou `allow_remote` : ce serait contredire son nom.

```bash
anonv2 predict --dataset <ds> --split <s> --system deterministic   --policy P2 --profile deterministic
```
