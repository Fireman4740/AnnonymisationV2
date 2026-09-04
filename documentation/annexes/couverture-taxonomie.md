# Couverture empirique de la taxonomie

| | |
|---|---|
| **Statut** | F-3 — mesure issue du pipeline officiel |
| **Date de mesure** | 2026-09-04 |
| **Entrée** | `data/processed/<dataset>/.validation.json` |
| **Règle** | E-VAL-110 : `OTHER_QI` > 1 % des annotations ⇒ couverture taxonomique incomplète |

## 1. Méthode et périmètre

Les trois corpus ont été ingérés avec `anonv2 datasets ingest <clé> --all`,
avec `ANONV2_V1_DATASETS` pointant vers la copie locale V1. Aucun fichier brut
n'est versionné dans V2. Les taux ci-dessous utilisent le dénominateur de la
validation (`annotations.jsonl`) et les catégories effectivement émises par
l'adaptateur, après l'agrégation propre au protocole :

- **QUASIFR** : toutes les annotations source, offsets uniques ré-ancrés ;
  `COREF` et les types techniques restent `IGNORED` ;
- **TAB** : union déterministe des mentions `DIRECT` et `QUASI` de tous les
  annotateurs ; `NO_MASK` est hors cible mais son volume est compté dans la
  métadonnée du document ;
- **PersonalReddit** : une annotation implicite par réponse, sur l'attribut
  `feature` ciblé ; les neuf attributs du profil sont conservés dans le profil.

## 2. Résultat E-VAL-110

| Corpus | Documents | Annotations pivot | `OTHER_QI` | Taux | Verdict |
|--------|----------:|------------------:|-----------:|-----:|---------|
| QUASIFR | 72 | 427 | 71 | **16,63 %** | **Taxonomie incomplète** — principalement `QUASI_ID` sans justification exploitable |
| TAB officiel | 1 268 | 74 225 | 5 901 | **7,95 %** | **Taxonomie incomplète** — `MISC` et `QUANTITY` sont hétérogènes |
| PersonalReddit synthetic | 525 | 525 | 0 | **0,00 %** | Couverture des catégories de profil satisfaisante pour ce corpus |

Les rapports de validation ne contiennent aucune erreur (`errors: []`). Les
statuts sont `WARN` pour QUASIFR et TAB, `PASS` pour PersonalReddit. Un taux
nul ne prouve pas la complétude générale : PersonalReddit ne contient que huit
attributs ciblés parmi neuf attributs de profil et aucune annotation de span.

### 2.1 Catégories observées par corpus

**QUASIFR après classification des notes :**

| Catégorie | Nombre |
|-----------|-------:|
| `DIR_NAME` | 43 |
| `GEN_GEO` | 75 |
| `GEN_DATE_EVENT` | 38 |
| `GEN_AFFILIATION` | 34 |
| `GEN_OCCUPATION` | 23 |
| `DIR_DEVICE_ID` | 29 |
| `GEN_SOCIOECON` | 17 |
| `DIR_EMAIL` | 20 |
| `GEN_HEALTH_STATE` | 4 |
| `GEN_LIFESTYLE` | 2 |
| `DIR_CASE_REF` | 9 |
| `DIR_PHONE` | 10 |
| `DIR_ID_NUMBER` | 3 |
| `DIR_ACCOUNT` | 2 |
| `DIR_ADDRESS` | 1 |
| `GEN_EDUCATION` | 1 |
| `GEN_GENDER` | 1 |
| `HR_EMPLOYER_SIZE` | 1 |
| `SUP_ENVIRONMENT` | 8 |
| `OTHER_QI` | **71** |
| `IGNORED` | 29 |

Les catégories sont multi-étiquettes pour certaines notes : la somme des
lignes peut donc dépasser le nombre d'annotations.

**TAB officiel :** le reliquat `OTHER_QI` est constitué de 3 297 mentions
`MISC` et 2 604 mentions `QUANTITY` après union des annotateurs. Dans la source
brute, ces types sont beaucoup plus hétérogènes que leurs noms ne le laissent
penser : médicaments, substances, statuts, faits juridiques, produits,
quantités de personnes, sommes d'argent et formulations contextuelles. Une
conversion globale en `GEN_SOCIOECON`, `GEN_HEALTH_STATE` ou autre code serait
une approximation silencieuse.

## 3. Classification manuelle des 33 `risk_note` QUASIFR non vides

La release contient 100 annotations `QUASI_ID`, 34 valeurs distinctes de
`risk_note` (dont la valeur vide), donc **33 notes non vides**. Chaque note est
ci-dessous soit mappée vers des codes existants, soit explicitement maintenue
`OTHER_QI`. Les 65 notes vides ne fournissent aucune information permettant une
classification : elles restent `OTHER_QI`.

| `risk_note` | n | Décision taxonomique |
|-------------|--:|----------------------|
| `Âge` | 2 | `GEN_AGE` |
| `Âge précis` | 2 | `GEN_AGE` |
| `Tranche d'âge` | 1 | `GEN_AGE` |
| `Âge avancé combiné à pathologie` | 1 | `GEN_AGE` + `GEN_HEALTH_STATE` |
| `Maladie rare (faible k-anonymat)` | 1 | `GEN_HEALTH_STATE` |
| `Événement marquant récent` | 1 | `GEN_DATE_EVENT` |
| `Blessure précise` | 1 | `GEN_HEALTH_STATE` |
| `Statut lié à un fait divers` | 1 | `GEN_DATE_EVENT` |
| `Activité physique` | 1 | `GEN_LIFESTYLE` |
| `Véhicule rare` | 1 | `GEN_SOCIOECON` (patrimoine) |
| `Dispositif médical rare` | 1 | `GEN_HEALTH_STATE` |
| `Attribut unique dans le département (k=1)` | 1 | `GEN_GENDER` + `GEN_OCCUPATION` |
| `Condition de travail spécifique` | 1 | `GEN_OCCUPATION` |
| `Métier local` | 1 | `GEN_OCCUPATION` + `GEN_GEO` |
| `Fonction publique locale unique` | 1 | `GEN_OCCUPATION` + `GEN_GEO` |
| `Description de poste unique via un produit spécifique` | 1 | `GEN_OCCUPATION` + `GEN_AFFILIATION` |
| `Métier actuel très spécifique` | 1 | `GEN_OCCUPATION` |
| `Identification par possession unique dans une petite zone géographique` | 1 | `GEN_SOCIOECON` + `GEN_GEO` |
| `Expertise sur un module interne obscur` | 1 | `GEN_OCCUPATION` |
| `Poste très spécifique dans une petite équipe` | 1 | `GEN_OCCUPATION` + `GEN_AFFILIATION` |
| `Poste médical unique dans une petite ville` | 1 | `GEN_OCCUPATION` + `GEN_GEO` |
| `Possession unique d'un véhicule de collection dans une petite île` | 1 | `GEN_SOCIOECON` + `GEN_GEO` |
| `Combinaison métier/activité unique localement` | 1 | `GEN_OCCUPATION` + `GEN_LIFESTYLE` + `GEN_GEO` |
| `Domaine académique très spécifique` | 1 | `GEN_EDUCATION` |
| `Taille d'équipe très réduite` | 1 | `HR_EMPLOYER_SIZE` |
| `Cumul de rôle local visible` | 1 | `GEN_OCCUPATION` + `GEN_GEO` |
| `Nom commercial local` | 1 | `GEN_AFFILIATION` + `GEN_GEO` |
| `Grant élevé, sensitif` | 1 | `GEN_SOCIOECON` |
| `Hostname avec loc implicite` | 1 | `SUP_ENVIRONMENT` + `GEN_GEO` |
| `Nom d'hôte interne` | 1 | `SUP_ENVIRONMENT` |
| `Lien indirect par déduction (rôle + loc + produit)` | 1 | `OTHER_QI` — la note décrit le mécanisme, pas l'attribut source |
| `Lien indirect par combinaison rare` | 1 | `OTHER_QI` — combinaison non décomposable à partir de la note |
| `Rareté explicite, risque de déduction` | 1 | `OTHER_QI` — justification de risque, pas catégorie |
| `Lien par déduction contextuelle` | 1 | `OTHER_QI` — justification de risque, pas catégorie |
| `Lien indirect par déduction métier (publications + grant)` | 1 | `OTHER_QI` — plusieurs attributs possibles, non déterminables |
| `Descripción única` | 1 | `OTHER_QI` — note insuffisante et langue différente |

Les labels `MONTANT`/`AMOUNT` (14 annotations) sont désormais mappés vers
`GEN_SOCIOECON`, qui couvre revenu, patrimoine et transaction. `HOST` (8) est
mappé vers `SUP_ENVIRONMENT`, et un motif de détection `hostname` a été ajouté
à `configs/detection/patterns.yaml`. Ces deux corrections utilisent des codes
existants et ne créent pas de nouvelle catégorie.

## 4. Décision d'évolution selon SPEC-01 §10

### 4.1 Pourquoi aucun nouveau code n'est ajouté

Les deux dépassements E-VAL-110 ne fournissent pas les prérequis de §10.3 :

1. `QUASI_ID` vide et notes de déduction : la source justifie un risque mais
   ne donne pas un attribut stable à séparer. Ajouter un code « déduction »
   confondrait le mécanisme d'inférence avec l'attribut et ne définirait pas
   une fréquence populationnelle.
2. TAB `MISC` : classe résiduelle qui mélange substances, produits, statuts,
   événements et faits juridiques. Aucun code unique ne la représente sans
   erreur de sens.
3. TAB `QUANTITY` : quantités de personnes, audiences, montants, pourcentages
   et durées. Une classe `GEN_QUANTITY` serait trop large ; aucune source de
   population française/européenne permettant d'estimer sa fréquence n'est
   déclarée.

Créer `GEN_MONEY`, `GEN_QUANTITY` ou `GEN_DEDUCTION` maintenant violerait la
barrière de SPEC-01 §10.3 (« fournir la source de population permettant de
calculer k »). Le statut `Gelé` de SPEC-01 v1.1 est donc conservé ; les labels
non résolus restent explicitement `OTHER_QI`, avec leur label source et leur
justification dans `Annotation.meta`.

### 4.2 Motifs et manifeste

- `MONTANT`/`AMOUNT` → `GEN_SOCIOECON` dans le manifeste QUASIFR ;
- `HOST` et les hostnames détectés → `SUP_ENVIRONMENT` ;
- `OTHER_QI` est maintenu comme code de service : son taux déclenche
  E-VAL-110, aucune alerte n'est supprimée ;
- `configs/detection/patterns.yaml` ajoute uniquement le motif déclaratif
  `hostname -> SUP_ENVIRONMENT` ; il n'ajoute pas de code taxonomique.

Cette décision satisfait la procédure §10 sans contourner sa condition de
population. Une réouverture de SPEC-01 nécessitera une population de référence
et deux exemples normalisés pour chaque éventuel nouveau code.

## 5. Limites de la mesure

- Les taux sont propres aux schémas de chaque protocole : l'union TAB réduit
  les doublons multi-annotateurs ; le taux n'est pas comparable à un comptage
  brut de mentions annotateur par annotateur.
- `OTHER_QI` est une alerte de couverture, pas une preuve que chaque mention
  est réellement ré-identifiante ; la taxonomie ne doit toutefois pas la
  masquer.
- PersonalReddit mesure des attributs implicites au niveau document et ne teste
  pas la détection de spans ; son taux nul ne généralise pas aux autres
  domaines.
