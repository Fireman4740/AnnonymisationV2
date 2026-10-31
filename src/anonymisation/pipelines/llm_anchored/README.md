# Qwen fenêtré avec critique aveugle ancrée (`llm-anchored-v1`)

Hypothèse expérimentale : garder les décisions de `llm-windowed-v1`, puis
ajouter seulement les indices résiduels qu'un critique local repère dans le
texte déjà anonymisé et qui se projettent sans ambiguïté sur le texte original.
**Aucune amélioration n'est mesurée avant la campagne.**

1. La baseline Qwen fenêtrée produit ses détections, actions et offsets.
2. Le critique voit uniquement le texte anonymisé, fenêtre par fenêtre. Il
   renvoie des citations exactes, leur catégorie et des contextes d'ancrage.
3. Le code accepte une proposition seulement si sa localisation est unique,
   sur une portion non transformée, et si sa projection sur l'original est
   exacte. Les propositions ambiguës ou qui touchent une substitution sont
   écartées avec avertissement. Les décisions initiales sont conservées.
4. Les seules additions sont des suppressions contrôlées par catégorie. Les
   collisions entre additions sont fusionnées ; une erreur de modèle est une
   erreur explicite du document. Les réponses structurées sont validées avant
   leur mise en cache. Aucun gold ou label aval n'entre dans le pipeline.

Ce dessin s'inspire du compromis entre relations utiles et indices privés de
[PromptGraph](https://www.alphaxiv.org/pdf/2607.10709) et du rôle de l'intention
sur l'utilité étudié par [Veilmind](https://www.alphaxiv.org/pdf/2609.10992).
Il ne reproduit pas leur algorithme de graphe ou leur entraînement. L'évaluation
par inférence indépendante reste nécessaire, comme le souligne
[SPIA](https://www.alphaxiv.org/pdf/2604.21211).

Le backend est limité à une API locale ou au stub de tests ; Qwen est le seul
modèle utilisé dans la configuration du banc. Paramètre `critique=false` :
contrôle sans critique. Le système ne garantit pas l'anonymat, ne produit pas
de probabilité de risque et peut manquer des fuites ou refuser des corrections
ambiguës. La suppression ajoutée peut réduire la lisibilité. L'utilité et la
confidentialité doivent donc être évaluées séparément, y compris sur un jeu
indépendant de la cohorte de développement utilisée pour concevoir la variante.

Exemple après reprise explicite de l'expérience :

```sh
anonv2 predict --dataset quasifr --split anonymization --system llm-anchored \
  --profile llm_anchored --param backend=qwen_local_box --out runs/anchored-quasifr
anonv2 score --run runs/anchored-quasifr --protocol quasifr-v1
```
