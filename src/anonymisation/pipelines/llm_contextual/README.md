# Qwen contextuel local (`llm-contextual-v1`)

Cette variante vise le compromis observé sur la baseline `llm-windowed-v1` :
les masques locaux ne suppriment pas tous les indices personnels distribués,
et masquer les concepts génériques utiles peut dégrader la tâche aval.
**Une amélioration est une hypothèse à mesurer, pas un résultat acquis.**

La chaîne utilise exclusivement l'API Qwen locale existante, sans télécharger
de modèle ni entraîner de poids :

1. Le document entier sert à reconnaître une intention générale et à relier
   des indices personnels exacts répartis entre plusieurs passages. Aucun
   label de tâche, nom de dataset, gold ou exemple du banc n'entre dans le prompt.
2. Des fenêtres de 3 000 caractères produisent des éditions ciblées. Les
   concepts publics utiles sont conservés ; les identifiants directs sont
   remplacés par des marqueurs cohérents et les indices personnels sont
   généralisés ou supprimés. Les offsets sont calculés par recherche exacte
   en mots entiers ; toutes les occurrences d'une surface proposée sont traitées.
3. Une critique reçoit **uniquement le texte anonymisé et l'intention générique**,
   sans le texte original ni les risques du plan, et propose des corrections.
   Une table de provenance projette ces corrections sur le texte original.
   Une sous-partie de remplacement ou une édition traversant plusieurs segments
   n'est jamais projetée approximativement : elle est écartée avec avertissement.

Les réponses sont soumises à des schémas JSON dans le décodeur vLLM et validées
avant mise en cache. Une fenêtre invalide ou tronquée est retentée trois fois,
puis seule cette fenêtre est redécoupée, jusqu'à 500 caractères. Un échec
persistant reste une erreur du document ; aucune sortie incomplète ne devient
une détection vide. Le critique essaie d'abord le texte entier et se redécoupe
lui aussi si nécessaire ; le plan, borné à 12 chaînes, échoue explicitement
après trois tentatives invalides. Le schéma est dans la clé du cache via `extra_body`.

La variante refuse une API publique : seuls localhost et les adresses IP
privées sont acceptés (ou le backend `stub` pour les tests). Tous les appels
de la campagne, y compris les attaques, sont configurés sur `qwen_local_box`.
La commande de run héritée exécute une sanité synthétique de ce système avant
la campagne ; elle s'arrête si le format contraint ou l'anonymisation échoue.

## Appui bibliographique et écarts

- [IntentAnony, §3](https://www.alphaxiv.org/pdf/2601.04265) motive le contexte
  global, les chaînes d'indices et la préservation de l'intention. Les auteurs
  écrivent : “Sensitive personal attributes are rarely disclosed through isolated
  identifiers.” Cette variante adapte ces idées en prompts ; elle ne reproduit
  pas leur matrice de budgets d'exposition et ne reçoit pas de tâche aval.
- [SEAL, §4](https://www.alphaxiv.org/pdf/2506.01420) motive la critique et la
  révision locales. SEAL entraîne un petit modèle par SFT/DPO ; ici les poids
  Qwen restent inchangés et une seule critique est appliquée par défaut.
- [AgentStealth, §4.1](https://www.alphaxiv.org/pdf/2506.22508) motive les
  corrections guidées par les indices d'inférence et l'attention à l'utilité.
  Les mémoires apprises, le RL et les juges d'utilité de cet article ne sont
  pas introduits dans le banc.
- [GRASP](https://www.alphaxiv.org/pdf/2608.06526), également examiné, optimise
  un anonymiseur local par GRPO. Aucun entraînement GRPO ni résultat de GRASP
  n'est revendiqué pour cette implémentation.
- [vLLM : structured outputs](https://docs.vllm.ai/en/latest/features/structured_outputs/)
  documente `structured_outputs.json`, utilisé avec thinking désactivé.

## Contrat et limites

Capacités : `spans`, `decisions`. Ni estimation de risque calibré, ni politique
à seuil, ni garantie de confidentialité différentielle. Les confidences des
annotations sont nominales, comme dans la baseline ; elles ne sont pas des
probabilités d'attaque. Les sorties du critique ne remplacent jamais les attaques
indépendantes du banc ni ses métriques d'utilité mesurées par classifieur.

Le contexte global est limité explicitement à 16 000 caractères, comme la
cohorte gelée ; un document plus long est refusé. La segmentation adaptative
conserve un contexte global résumé mais peut perdre des dépendances locales.
Les indices non verbalisés, les variantes d'un même nom, les coréférences et
la langue restent des limites du modèle. La préservation d'intention peut
laisser une information personnelle utile : protection et utilité doivent être
rapportées ensemble. Les 200 items déjà examinés constituent une cohorte de
développement ; une confirmation sur un ensemble indépendant restera nécessaire.

Exemple (via l'environnement verrouillé du projet) :

```sh
anonv2 predict --dataset quasifr --split hard_quasi_id --system llm-contextual \
  --profile llm_contextual --param backend=qwen_local_box --out runs/contextual-quasifr
anonv2 score --run runs/contextual-quasifr --protocol quasifr-v1
```

Les paramètres sont figés dans `Params` et enregistrés dans l'identité.
La campagne conserve la cohorte `banc-fiable-200-v2`, les deux contrôles
oracle-mask/regex-only, les tâches aval, les attaquants et les calculs originaux
RAT-Bench/SPIA/TAB du parent. Seul le troisième système est remplacé.
