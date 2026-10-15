# Évaluations conditionnelles — scorecards 3.1

À la demande de l'utilisateur, trois axes sont réintroduits avec des protocoles
explicites : utilité sur une tâche, détection des combinaisons de QI, exactitude
et qualité probabiliste du risque. Ils restent **diagnostiques** : utiliser un
calcul officiel ne valide pas automatiquement le corpus, l'évaluateur ou le
modèle de menace. Les anciens scores ne sont pas réactivés.

## Provenance des implémentations

| Calcul | Code utilisé | Adaptation du banc |
|---|---|---|
| Macro-F1, accuracy | [`sklearn.metrics`, version 1.8.0](https://github.com/scikit-learn/scikit-learn/blob/1.8.0/sklearn/metrics/_classification.py), paquet appelé directement et épinglé dans `uv.lock` | Vocabulaire de classes fixé au train ; même évaluateur pour original/anonymisé ; delta, ratio et bootstrap apparié |
| Évaluateur aval de référence | `sklearn.feature_extraction.text.TfidfVectorizer`, `sklearn.linear_model.LogisticRegression`, `sklearn.dummy.DummyClassifier`, version 1.8.0 | Paramètres fixes ; pas d'ajustement sur le test ; ce modèle linéaire doit encore être validé pour l'usage métier |
| Brier binaire | [`sklearn.metrics.brier_score_loss`](https://scikit-learn.org/1.8/modules/generated/sklearn.metrics.brier_score_loss.html), appelé directement | Cible binaire observée, `pos_label=1`, `scale_by_half=True` : intervalle [0,1] |
| Courbe de fiabilité | [`sklearn.calibration.calibration_curve`](https://github.com/scikit-learn/scikit-learn/blob/1.8.0/sklearn/calibration.py), appelée directement | ECE calculée comme moyenne pondérée des écarts absolus des bacs non vides ; 10 bacs uniformes, sensibilité 5/10/15/20 |
| QICR et MALE-k | Définitions **propres au projet**, versionnées | Aucune implémentation officielle externe de QICR n'a été identifiée ; ne pas les présenter comme des métriques officielles de Tau-Eval ou de RAT-Bench |

Le protocole original/anonymisé à évaluateur figé est cohérent avec
[Tau-Eval, `utils.py`, commit 63aca8f8ba24db5b1c06c140d11ea695f47ff98b](https://github.com/gabrielloiseau/tau-eval/blob/63aca8f8ba24db5b1c06c140d11ea695f47ff98b/tau_eval/utils.py).
Le banc ne copie pas son code et ne reproduit pas ses modèles tasknet : le
backend linéaire est une adaptation déclarée, pas une reproduction de ses résultats.

## Utilité sur une tâche

```bash
uv run --locked --extra metrics anonv2 evaluate --run runs/mon_run --task ticket_routing
uv run --locked --extra metrics anonv2 score --run runs/mon_run --protocol supporttickets-v1
```

Le pivot doit contenir les documents et labels `tasks.jsonl` du train original
et du test, déjà verrouillés par l'ingestion et le run. `--train-split` permet
de choisir un autre split d'entraînement. Le split évalué doit être `test` ou
`eval`. Une étape n'évalue qu'une tâche ; aucune moyenne entre tâches différentes.

`evaluate` entraîne localement un pipeline TF-IDF unigrammes/bigrammes et
régression logistique (C=1, lbfgs, poids équilibrés, 1000 itérations, graine 42),
puis fige pour chaque document son label gold et les prédictions sur les deux
textes. Les paramètres, l'empreinte du modèle et les versions sont conservés.

Contrôles : documents et textes disjoints entre train et test ; auteurs, sujets
et fils disjoints quand ces identifiants sont disponibles ; deux classes au
minimum ; labels uniques et présents ; classes du test connues du train ;
convergence obligatoire. L'absence d'identifiants de groupe ne prouve pas
l'indépendance des personnes : cette limite reste attachée au protocole.

Deux clés sont publiées :

- `utility_retention` = macro-F1 anonymisé / macro-F1 original ;
- `task_f1_delta` = macro-F1 anonymisé − macro-F1 original.

Les F1 absolus, accuracies et référence majoritaire restent dans les détails.
Si l'évaluateur ne dépasse pas la classe majoritaire sur l'original, les deux
clés deviennent indisponibles. Le ratio n'est pas borné à 1 : une amélioration
est possible. Un texte vide peut conserver une performance de classe majoritaire ;
on ne lui impose pas artificiellement F1=0.

## Combinaisons et population indépendante

```bash
uv run --locked --extra metrics anonv2 evaluate --run runs/mon_run --population population.json --k-threshold 10
uv run --locked --extra metrics anonv2 score --run runs/mon_run --protocol mon-protocole
```

Les deux options `--task` et `--population` peuvent être utilisées ensemble.
Le pivot `combinations.jsonl` doit être verrouillé et relier chaque combinaison
à ses documents, annotations précises, cible, attributs normalisés et population.
La population est un fichier fourni indépendamment du système évalué :

```json
{
  "schema_version": "1",
  "population_id": "population-controlee",
  "kind": "synthetic_controlled",
  "records": [
    {"subject_id": "p1", "attributes": {"GEN_AGE": {"exact": 30}}},
    {"subject_id": "p2", "attributes": {"GEN_AGE": {"exact": 30}}}
  ]
}
```

`kind` accepte `synthetic_controlled` ou `reference_census`. Le protocole v1
compte exactement les égalités d'attributs normalisés ; il ne déduit pas de
relations hiérarchiques et n'extrapole pas une population depuis un échantillon.
Les identifiants sont uniques, tous les attributs interrogés sont renseignés,
et la personne cible doit appartenir à sa classe. Un `k_true` déclaré dans le
pivot doit coïncider avec ce comptage, sinon l'évaluation échoue.

`qicr` est la proportion des combinaisons à k ≤ seuil dont **toutes les mentions
liées sont intégralement détectées**, avec catégorie compatible. Un simple
chevauchement ne suffit pas. La ventilation `qicr_at_j` utilise le nombre
d'attributs, pas le nombre de répétitions d'une mention. Les combinaisons sans
lien, sans offsets ou avec un document en erreur sont exclues et comptées.
Le bootstrap regroupe toutes les combinaisons d'une même cible.

C'est un diagnostic de détection, sans garantie de confidentialité : il ne
mesure pas la suppression effective, le sur-masquage ou l'inférence contextuelle.
Il doit être lu avec les mesures de transformation et d'attaque.

`male_k` = moyenne |ln(1+k_hat) − ln(1+k_true)|. Le risque prédit doit nommer
explicitement la même `combination_id` et la même `population_id` ; un risque
documentaire n'est pas associé arbitrairement à chacune de ses combinaisons.
Cette mesure n'est disponible que sur `test`/`eval`. C'est une erreur
d'estimation de k, pas une calibration de probabilités de ré-identification.
Les producteurs historiques qui n'émettent pas cette liaison restent non évaluables.

## Brier et ECE sur un événement observé

Ces clés sont calculées automatiquement par `score` seulement si une attaque
RAT-Bench figée et vérifiée est présente et si les **prédictions d'origine**
contiennent une prévision d'événement pour chaque document attaqué sans erreur :

```json
{
  "risk": {
    "event_forecast": {
      "probability": 0.2,
      "contract": {
        "protocol": "ratbench-staab-correctmatch",
        "protocol_version": "2",
        "event": "ratbench_reidentified",
        "text_stage": "anonymized",
        "attacker": {"configuration_complete": "identique au bloc attacker de attack.lock.json"}
      }
    }
  }
}
```

Le bloc `attacker` ci-dessus est schématique : il faut recopier **toute la
configuration réelle** prévue pour l'attaque. Le contrat doit être identique.
L'empreinte des prédictions présente dans le lock d'attaque garantit qu'une
prévision ne peut pas être ajoutée après l'attaque. Les producteurs actuels ne
fournissent pas automatiquement une telle probabilité : `risk=1/k` de l'original
n'est pas une prévision validée de l'attaque après anonymisation.

La cible est `reidentified`, booléen observé de RAT-Bench. CorrectMatch, le
risque 1/k gold continu et les certitudes ordinales de SPIA ne sont pas utilisés
comme cibles de substitution. Couverture incomplète, attaque non exploitable,
split d'ajustement ou absence de prévisions : métriques indisponibles. Un contrat
divergent ou une probabilité invalide fait échouer le score.

Les probabilités égales restent dans le même bac ; les observations gold ne
servent pas à départager leurs positions. Brier mesure la qualité probabiliste
globale et ne suffit pas seul à prouver une bonne calibration. La courbe et les
effectifs de ses bacs sont conservés ; les petits échantillons restent diagnostiques.

## Intégrité et campagne

`evaluate` produit `evaluation.json` et `evaluation.lock.json`. `score` vérifie
les empreintes des prédictions, des documents, des annotations, des labels train/test,
des combinaisons et de la population utilisée. Il ne fait aucun entraînement ni
appel modèle. Les comparaisons refusent des tâches, évaluateurs, populations,
seuils ou ensembles de documents différents. Les intervalles à 95 % utilisent
1000 réplicats déterministes ; les unités et réplicats indéfinis sont conservés.

La campagne accepte une configuration explicite, par exemple :

```json
{
  "datasets": {"supporttickets": ["test"]},
  "conditional_evaluations": {
    "supporttickets": {
      "task": "ticket_routing",
      "train_split": "train",
      "training_documents": 2000
    }
  }
}
```

Cet extrait complète les autres paramètres de campagne. Le train auxiliaire
est ingéré et verrouillé, sans prédiction d'anonymisation ; il ne consomme pas
le budget des documents évalués. Une référence populationnelle peut être
déclarée avec `population` et `k_threshold`. La campagne de dix documents
active `ticket_routing` sur SupportTickets et `intent` sur BitextSupport, avec
2000 documents de train chacun. Le train est échantillonné après exclusion des
textes, personnes et fils présents dans le test ; les exclusions sont comptées.
Les populations indépendantes et prévisions d'événement manquantes ne sont pas fabriquées.

RCR, le juge global d'utilité, ROUGE comme mesure du sens et TRIR lexical
restent hors du banc actif. Les anciennes scorecards ne sont pas modifiées.
