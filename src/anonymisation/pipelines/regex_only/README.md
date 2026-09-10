# Pipeline `regex_only` — baseline PII par motifs

| | |
|---|---|
| **Clé** | `regex-only-v1` (alias `regex-only`, `regex`) |
| **Capacités** | `spans`, `decisions` |
| **Politique** | non — décisions `SUPPRESS` directes |
| **Profil** | aucun (n'en lit pas) |
| **Hors ligne** | oui |

Détection par motifs déclaratifs seuls (`configs/detection/patterns.yaml`, via
`PatternDetector`) : **aucun lexique contextuel, aucune règle QI**. Chaque
candidat devient une décision `SUPPRESS`.

C'est la **baseline PII classique** du projet : elle montre ce que rate un
détecteur d'identifiants explicites face aux quasi-identifiants combinatoires
(ER_qi mesuré à 0,000 sur les trois corpus de la campagne — voir
`documentation/rapport/05-evaluation-llm-full-v1.md`).

```bash
anonv2 predict --dataset <ds> --split <s> --system regex-only --profile deterministic
```
