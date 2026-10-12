# Pipeline `oracle_mask` — ancre oracle

| | |
|---|---|
| **Clé** | `oracle-mask-v1` (alias `oracle-mask`, `oracle`) |
| **Capacités** | `spans`, `decisions`, `gold_aware` — **oracle** |
| **Politique** | non |

Supprime exactement chaque mention gold ancrée (placeholder `[CATÉGORIE]`), par
la même chaîne d'application que les autres systèmes. Ce qui reste
ré-identifiable après l'oracle mesure ce que les métriques de spans ne voient
pas (attributs inférés sans span, contexte). Lit le gold : n'est **jamais**
classé parmi les systèmes évalués.

```bash
anonv2 predict --dataset <ds> --split <s> --system oracle-mask --profile deterministic
```
