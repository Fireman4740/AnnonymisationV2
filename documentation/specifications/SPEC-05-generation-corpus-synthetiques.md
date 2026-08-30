# SPEC-05 — Génération des corpus internes à profil latent

| | |
|---|---|
| **Statut** | Brouillon |
| **Version** | 0.9 |
| **Date** | 2026-08-30 |
| **Dépend de** | SPEC-01, SPEC-02, SPEC-06 |
| **Concerne** | `hr_qi`, `support_qi`, `forum_qi` |

---

## 1. Objet

Définir le protocole de construction des trois corpus internes, qui portent la
contribution du projet. Ils sont **générés**, pas ingérés : leur adaptateur est
un générateur.

Principe fondateur, hérité de RAT-Bench [@krco2026ratbench] et SynthPAI
[@yukhymenko2024synthpai] :

> **L'annotation n'est pas produite après le texte. Le texte est produit à
> partir d'un plan d'annotation.**

C'est ce qui rend la vérité terrain exacte, gratuite et exempte d'erreur
d'annotateur — le seul avantage décisif du synthétique.

## 2. Chaîne de génération

```
[1] population de référence          configs/populations/<pid>.yaml
        │  échantillonnage
        ▼
[2] profils latents                  profiles.jsonl / organizations.jsonl
        │  calcul exact
        ▼
[3] combinaisons + k_true            combinations.jsonl
        │  planification
        ▼
[4] plans de document                (interne) : quels QI, à quel mode d'expression
        │  génération LLM local
        ▼
[5] textes                           documents.jsonl
        │  dérivation + vérification
        ▼
[6] annotations                      annotations.jsonl
        │
        ▼
[7] étiquettes d'utilité             tasks.jsonl
        │
        ▼
[8] contrôle qualité (5 % humain)    rapport
```

L'étape 3 précède l'étape 5 : **on connaît $k$ avant d'écrire le texte**. C'est
l'inversion qui permet de contrôler la distribution des risques dans le corpus.

## 3. Étape 1 — Population de référence

Voir [SPEC-06 §4](SPEC-06-population-et-risque.md). Résumé des sources :

| Corpus | Population | Sources |
|--------|-----------|---------|
| `hr_qi` | `fr-hr-2026` | INSEE (emploi × CSP × département, diplôme × âge × région), DARES |
| `forum_qi` | `fr-general-2026` | INSEE (population générale, âge × sexe × région × diplôme × CSP) |
| `support_qi` | `support-parc-2026` | Parc synthétique : organisations × produits × versions × configurations, avec **queue longue explicite** |

## 4. Étape 2 — Échantillonnage des profils

| Corpus | Profils | Organisations |
|--------|--------:|--------------:|
| `hr_qi` | 600 | — |
| `support_qi` | 600 | ~200 |
| `forum_qi` | 500 | — |

### Contrainte de couverture du risque

Un échantillonnage purement proportionnel produirait un corpus où presque tous
les profils ont un $k$ élevé — donc un benchmark facile et peu informatif.

**Exigence** : la distribution des $k$ dans le corpus DOIT être stratifiée.

| Strate | Part cible du corpus |
|--------|---------------------:|
| $k = 1$ (unique) | 10 % |
| $k \in [2, 4]$ | 20 % |
| $k \in [5, 9]$ | 20 % |
| $k \in [10, 19]$ | 20 % |
| $k \geq 20$ | 30 % |

Cette stratification est **déclarée**, donc corrigeable : toute métrique agrégée
sur le corpus doit être repondérée si l'on veut estimer un risque en population
réelle. Le fichier `.manifest.lock.json` conserve les poids d'échantillonnage.

> C'est un point à ne pas rater dans une publication : un $R_{succ}$ mesuré sur
> un corpus sur-représentant les $k$ faibles n'est **pas** le risque en
> production. Publier les deux : brut (sur le corpus) et repondéré (estimé en
> population).

## 5. Étape 3 — Combinaisons et $k$ exact

Pour chaque profil, énumérer les sous-ensembles de QI de taille 1 à $m_{max}$
(défaut 5) et calculer $k$ exactement sur la population de référence.

Coût combinatoire : $\sum_{i=1}^{5}\binom{|Q|}{i}$ avec $|Q| \approx 10$ →
~ 638 combinaisons par profil, soit ~380 000 pour 600 profils. Acceptable si le
calcul de $k$ est vectorisé sur la table de population.

Sont conservées dans `combinations.jsonl` :

- toutes les combinaisons **à risque** ($k \leq 10$) ;
- un échantillon des combinaisons non à risque (pour équilibrer le dénominateur
  de QICR et éviter un classifieur qui prédirait toujours « à risque »).

## 6. Étape 4 — Plans de document

Un **plan** est la spécification d'un document avant sa rédaction :

```json
{
  "plan_id": "hr_qi:plan_04412",
  "person_id": "hr_qi:P01742",
  "doc_type": "hr_ticket",
  "language": "fr",
  "target_combination": "hr_qi:comb_00981",
  "qi_plan": [
    { "qi_category": "GEN_AGE",            "value": "moins de 30 ans", "mode": "EXPLICIT" },
    { "qi_category": "GEN_EDUCATION",      "value": "doctorant",       "mode": "EXPLICIT" },
    { "qi_category": "HR_ADMIN_PROCEDURE", "value": "arrêt maladie",   "mode": "EXPLICIT" },
    { "qi_category": "GEN_GEO",            "value": "Lille",           "mode": "IMPLICIT" }
  ],
  "forbidden_qi": ["DIR_NAME", "DIR_EMAIL", "HR_SALARY_BAND"],
  "utility_labels": { "hr_request_type": "sick_leave" },
  "style": { "register": "informel", "length": "court" }
}
```

| Champ | Rôle |
|-------|------|
| `qi_plan` | Ce que le texte DOIT contenir, et **sous quel mode d'expression** |
| `forbidden_qi` | Ce que le texte NE DOIT PAS contenir — vérifié après génération |
| `utility_labels` | Les étiquettes de tâche, connues *avant* le texte |
| `style` | Variation de registre, pour éviter l'uniformité stylistique |

### Répartition des modes d'expression

| Corpus | `EXPLICIT` | `NON_STANDARD` | `IMPLICIT` |
|--------|-----------:|---------------:|-----------:|
| `hr_qi` | 40 % | 30 % | 30 % |
| `support_qi` | 45 % | 30 % | 25 % |
| `forum_qi` | 20 % | 30 % | **50 %** |

Le forum est délibérément le plus implicite : c'est le régime où la littérature
est la plus faible et où le projet a le plus à démontrer.

## 7. Étape 5 — Génération du texte

| Aspect | Règle |
|--------|-------|
| Modèle | LLM local, < 30 B |
| **Séparation générateur / évalué** | Le modèle générateur NE DOIT PAS être un des modèles évalués comme détecteur. Sinon le détecteur reconnaît son propre style. |
| Diversité | ≥ 3 modèles générateurs différents, ≥ 5 gabarits de prompt par `doc_type` |
| Température | Élevée (0.8–1.0) pour la variété lexicale |
| Traçabilité | `Document.meta.generator = {model, prompt_id, temperature, seed}` |

La séparation générateur/évalué est une exigence méthodologique dure. Si elle ne
peut pas être tenue (par exemple parce que le meilleur générateur local est
aussi le meilleur détecteur), il faut le déclarer et publier une analyse de
sensibilité, pas l'ignorer.

## 8. Étape 6 — Dérivation et vérification des annotations

L'annotation vient du plan. Mais le générateur ne suit pas parfaitement le plan :
c'est le risque principal de toute la démarche.

### Trois contrôles obligatoires

| Contrôle | Question | Action si échec |
|----------|----------|-----------------|
| **C1 — Complétude** | Chaque QI du `qi_plan` est-il effectivement présent dans le texte ? | Document rejeté et régénéré |
| **C2 — Localisation** | Pour les modes `EXPLICIT` et `NON_STANDARD`, peut-on localiser un span ? | Sinon → mode reclassé en `IMPLICIT`, ou rejet |
| **C3 — Non-contamination** | Le texte contient-il un QI **non planifié** ? | Soit il est annoté (et la combinaison recalculée, donc $k$ recalculé), soit le document est rejeté |

C3 est le plus important et le plus coûteux. Un LLM à qui l'on demande d'écrire
un ticket RH ajoutera spontanément une ville, un prénom, un nom d'entreprise
« pour faire réaliste ». Si ces QI ne sont pas annotés, la vérité terrain est
fausse **et $k_{true}$ est surestimé** — ce qui fausserait toute la calibration.

Mise en œuvre de C3 : passe de détection large (union de plusieurs détecteurs,
seuil bas, orienté rappel) + vérification humaine sur échantillon. Un détecteur
qui trouve un QI non planifié déclenche l'arbitrage.

> **Circularité à éviter** : utiliser le système évalué pour détecter les QI non
> planifiés introduirait un biais favorable (il ne verrait pas ce qu'il ne sait
> pas voir). Le détecteur de contrôle DOIT être différent, et complété par le
> contrôle humain.

## 9. Étape 7 — Étiquettes d'utilité

Elles proviennent du plan (`utility_labels`), donc elles sont exactes par
construction — deuxième avantage majeur du synthétique.

**Contrôle de validité** : un classifieur entraîné sur le texte **original**
doit atteindre un F1 non trivial (seuils dans les fiches : ≥ 0.85 pour le
routage support). Sinon la tâche est trop bruitée pour mesurer une rétention
d'utilité, et le générateur ou l'étiquetage sont à revoir.

## 10. Étape 8 — Contrôle qualité humain

Échantillon de **5 %**, revu selon quatre critères :

| Critère | Question |
|---------|----------|
| Plausibilité | Un humain aurait-il pu écrire ce texte dans ce contexte ? |
| Fidélité au plan | Les QI planifiés sont-ils présents, au bon mode ? |
| Absence de contamination | Aucun QI non annoté ? |
| Cohérence conversationnelle | (forums, support) Le fil se tient-il ? |

Un taux de rejet > 10 % sur l'échantillon invalide le lot : il faut corriger les
prompts et régénérer.

## 11. Risques de la démarche

| Risque | Gravité | Mitigation |
|--------|:-------:|-----------|
| Contamination par QI non planifiés | **Élevée** | C3 + contrôle humain |
| Le détecteur apprend le style du générateur | **Élevée** | Multi-modèles, multi-prompts, évaluation croisée sur TAB (réel) |
| Population de référence imparfaite → $k$ faux | Moyenne | Publier $k$ avec intervalle (SPEC-06 §6), pas comme valeur ponctuelle |
| Stratification confondue avec la réalité | Moyenne | Publier les résultats bruts **et** repondérés |
| Corpus trop propre (peu de bruit, de fautes) | Moyenne | Injecter du bruit réaliste (fautes, abréviations, casse) dans une fraction déclarée |
| Uniformité culturelle / linguistique | Faible | Varier registres, régions, niveaux de langue |

Les deux premiers sont existentiels pour la validité du benchmark : ils doivent
être mesurés et publiés, pas seulement mitigés.

## 12. Reproductibilité

Le générateur DOIT produire un corpus **bit à bit identique** à partir de :
population + seed + version des prompts + version des modèles.

Comme les LLM ne sont pas parfaitement déterministes, la reproductibilité passe
par la **conservation des sorties** : les textes générés sont figés et
versionnés par checksum dans le lock. Le corpus est une donnée, pas une
fonction à réexécuter.

## 13. Critères de sortie

- [ ] Les trois corpus sont générés, validés (SPEC-04 §5), et figés.
- [ ] La distribution des $k$ respecte la stratification du §4 (±3 points).
- [ ] Les taux de modes d'expression respectent le §6 (±5 points).
- [ ] Taux de rejet du contrôle humain < 10 %.
- [ ] Taux de contamination détectée < 2 % après correction.
- [ ] Les classifieurs d'utilité atteignent leurs F1 de référence.
- [ ] Les poids d'échantillonnage sont conservés dans le lock.

## 14. Questions ouvertes

- Quels modèles générateurs exactement, et comment garantir la séparation avec
  les modèles évalués sur toute la durée du projet ?
- Faut-il publier les corpus ? (recommandation : oui — c'est la contribution la
  plus réutilisable, et la publication force la rigueur)
- Faut-il une campagne d'annotation humaine complète sur un sous-ensemble, pour
  disposer d'un point de comparaison « annotation humaine vs annotation dérivée
  du plan » ? (coût élevé, valeur scientifique élevée)

## 15. Journal des modifications

| Version | Date | Changement |
|---------|------|-----------|
| 0.9 | 2026-08-30 | Création. Chaîne en 8 étapes, stratification des $k$, contrôles C1/C2/C3. Statut brouillon : dépend de SPEC-06 pour les populations. |
