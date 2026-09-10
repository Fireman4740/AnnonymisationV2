# Pipeline `redact_all` — ancre S2

| | |
|---|---|
| **Clé** | `redact-all-v1` (alias `redact-all`, `suppress-all`) |
| **Capacités** | *(aucune)* — boîte noire |
| **Politique** | non |
| **Paramètre requis** | `replacement` (sans défaut, délibérément) |

Supprime tout le texte. **Borne haute de la protection, utilité effondrée.**

Sert aussi de **contrôle de la métrique elle-même** : si un système bat
`redact-all` sur la protection, c'est la métrique qui est fausse, pas le
système qui est excellent.

`replacement` n'a pas de défaut : une chaîne vide et un placeholder ne donnent
pas la même utilité mesurée, et choisir en silence reviendrait à fixer un point
de la courbe privacy-utility à la place de l'expérimentateur.

```bash
anonv2 predict --dataset <ds> --split <s> --system redact-all   --param replacement="[SUPPRIME]" --profile deterministic
```
