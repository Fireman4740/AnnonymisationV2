# Pipeline `passthrough` — ancre S1

| | |
|---|---|
| **Clé** | `passthrough-v1` (alias `passthrough`, `noop`) |
| **Capacités** | *(aucune)* — boîte noire |
| **Politique** | non |
| **Profil** | aucun (n'en lit pas) |

Ne modifie rien. **Borne basse de la protection, borne haute de l'utilité.**

Ce n'est pas un gadget : sans elle, aucun chiffre de protection n'a d'échelle
— on ne sait pas si un CPR de 0,61 est bon. Toute campagne devrait l'inclure.

```bash
anonv2 predict --dataset <ds> --split <s> --system passthrough --profile deterministic
```
