# SPEC-06 — Populations de référence et moteur de risque

| | |
|---|---|
| **Statut** | Brouillon |
| **Version** | 0.9 |
| **Date** | 2026-08-30 |
| **Dépend de** | SPEC-01, SPEC-02 |
| **Utilisée par** | SPEC-05, SPEC-07 |

---

## 1. Objet

Définir comment on passe d'un ensemble de quasi-identifiants observés dans un
texte à une **probabilité de ré-identification calibrée**.

C'est le cœur scientifique du projet et sa principale difficulté.

## 2. Formalisation

Population de référence $P$, individu $i$, document $d$. Le système extrait :

$$
Q(d) = \{(c_1, v_1), \dots, (c_m, v_m)\}
$$

où $c_j$ est un code de catégorie SPEC-01 et $v_j$ une **valeur normalisée**
(SPEC-01 §6.2).

Classe d'équivalence :

$$
\mathrm{EC}_P(Q) = \{p \in P : \forall j,\ p[c_j] \models v_j\}
$$

Le symbole $\models$ (« satisfait ») remplace l'égalité, car les valeurs peuvent
être des intervalles ou des niveaux hiérarchiques : `GEN_AGE = [18,29]` est
satisfait par un individu de 24 ans ; `GEN_GEO = FR-59` est satisfait par un
habitant de `FR-59350`.

$$
k(Q) = |\mathrm{EC}_P(Q)|
$$

## 3. Les quatre modèles de risque

Repris de la logique d'ARX [@prasser2020arx], qui montre qu'il faut les
distinguer.

### 3.1 Prosecutor

L'attaquant **sait** que la cible est dans le jeu de données.

$$
R_{pros}(Q) = \frac{1}{k(Q)}
$$

C'est le modèle le plus conservateur, et le défaut du projet.

### 3.2 Journalist

L'attaquant ne sait pas si la cible est dans le jeu de données ; il dispose de
la population $P$ mais l'échantillon $S$ est un sous-ensemble.

$$
R_{jour}(Q) = \frac{1}{k_P(Q)}
\qquad \text{avec } k_P \geq k_S
$$

C'est le modèle **k-map**. Il donne un risque plus faible et plus réaliste
quand la population de référence est large.

### 3.3 Marketer

Risque **moyen** sur l'ensemble des enregistrements — pertinent pour une
divulgation de masse, pas pour la protection d'un individu.

$$
R_{mark} = \frac{1}{|S|}\sum_{i \in S} \frac{1}{k(Q_i)}
$$

### 3.4 Copula — populations incomplètes

Quand $P$ n'est connue que par ses **marginales** (cas réel de l'INSEE : on a
âge × région, diplôme × âge, profession × région, mais pas la jointe complète),
les trois modèles précédents ne sont pas calculables exactement.

Le modèle de [@rocher2019estimating] estime la probabilité qu'un individu
correspondant à $Q$ soit **unique** dans la population, à partir d'un modèle
génératif par copule ajusté sur les marginales.

$$
R_{cop}(Q) = P\big(\text{unicité} \mid Q, P\big)
$$

> **C'est le modèle qui doit devenir le défaut du projet pour les corpus FR.**
> L'approximation $R = 1/k$ n'est valide que si $P$ est complète, ce qui n'est
> jamais le cas avec des données publiques agrégées.

### 3.5 Choix par contexte

| Contexte | Modèle par défaut |
|----------|-------------------|
| Corpus généré avec population synthétique complète | `prosecutor` (le $k$ est exact) |
| Corpus FR avec population INSEE agrégée | `copula` |
| Comparaison avec RAT-Bench | Celui du papier, à documenter |
| Publication d'un risque « pire cas » | `prosecutor` |

Le modèle utilisé DOIT figurer dans `Combination.risk_model` (SPEC-02 §8) et
dans tout rapport de métrique. Comparer deux risques calculés avec deux modèles
différents n'a aucun sens.

## 4. Populations de référence

### 4.1 Format

`configs/populations/<population_id>.yaml`

```yaml
population_id: fr-hr-2026
name: "Population active française — cadrage RH"
size: 29_500_000
geography: FR
year: 2026
kind: marginals            # exhaustive | sample | marginals | synthetic

attributes:
  GEN_AGE:
    normalization: range_years
    source: "INSEE — population par âge, 2023"
    file: "tables/fr/age.csv"
  GEN_GEO:
    normalization: geo_hierarchy      # FR > FR-59 > FR-59350
    source: "INSEE — COG 2026"
    file: "tables/fr/geo.csv"
  GEN_OCCUPATION:
    normalization: pcs_ese
    source: "INSEE — PCS-ESE 2020, emploi par CSP et département"
    file: "tables/fr/pcs_by_dept.csv"
  GEN_EDUCATION:
    normalization: isced
    source: "INSEE — diplôme par âge et région"
    file: "tables/fr/education.csv"

joints:                     # marginales croisées disponibles
  - [GEN_AGE, GEN_GEO]
  - [GEN_EDUCATION, GEN_AGE]
  - [GEN_OCCUPATION, GEN_GEO]

model:
  kind: copula
  fitted: "artifacts/populations/fr-hr-2026.copula.pkl"
  validation: "artifacts/populations/fr-hr-2026.validation.json"
```

### 4.2 Les trois populations du projet

| `population_id` | Nature | Corpus servis |
|-----------------|--------|---------------|
| `fr-hr-2026` | Marginales INSEE, population active | `hr_qi` |
| `fr-general-2026` | Marginales INSEE, population générale | `forum_qi` |
| `support-parc-2026` | **Synthétique exhaustive** (parc d'organisations) | `support_qi` |
| `ratbench-us` | Fournie par RAT-Bench | `ratbench` |

`support-parc-2026` est le cas confortable : le parc étant synthétique, il est
énuméré exhaustivement, donc $k$ est **exact** et sert de vérité terrain pour
calibrer les estimateurs utilisés sur les populations incomplètes.

> C'est une opportunité expérimentale à exploiter : mesurer l'erreur du modèle
> copule **contre un $k$ exact connu**, sur le corpus support, puis transférer
> la confiance ainsi établie aux corpus FR où le $k$ exact est inconnaissable.

### 4.3 Le cas du support : population = parc, pas humains

Pour `support_qi`, $P$ n'est pas une population humaine mais un **parc
installé** : l'ensemble des couples (organisation, configuration). Le
formalisme est inchangé — seule la nature de $P$ diffère.

La distribution des configurations DOIT suivre une **loi à queue longue** (loi
de puissance), faute de quoi le corpus ne contiendrait pas de cas $k = 1$, qui
sont précisément les cas intéressants.

## 5. Normalisation des valeurs

Sans normalisation, pas de comparaison, donc pas de $k$. Tables dans
`configs/populations/tables/`.

| Catégorie | Normalisation | Hiérarchie de généralisation |
|-----------|---------------|------------------------------|
| `GEN_AGE` | intervalle d'années | 1 an → 5 ans → 10 ans → tranche large |
| `GEN_GEO` | code hiérarchique | commune → département → région → pays |
| `GEN_OCCUPATION` | PCS-ESE (FR) / ESCO (EU) | niveau 4 → 3 → 2 → 1 |
| `GEN_EDUCATION` | CITE/ISCED + discipline | discipline fine → domaine → niveau seul |
| `HR_EMPLOYER_SIZE` | tranche d'effectifs | tranche fine → tranche large |
| `SUP_VERSION` | semver | patch → mineure → majeure |
| `SUP_INCIDENT_TIME` | plage + fuseau | heure → demi-journée → jour |

**La hiérarchie de généralisation est ce qui rend l'action `GENERALIZE`
opérationnelle** (SPEC-01 §8) : généraliser, c'est remonter d'un niveau, et
l'effet sur $k$ est calculable avant d'agir. C'est ce qui permet au moteur de
politique de choisir l'action **minimale** atteignant le seuil de risque — donc
de préserver l'utilité.

## 6. Incertitude

Un $k$ estimé sur des marginales est une **estimation**, pas une mesure. Le
moteur DOIT produire un intervalle :

$$
\hat{k}(Q) \in [\hat{k}_{low}, \hat{k}_{high}]
$$

et le risque publié DOIT être le **pire cas crédible** (borne haute du risque,
donc borne basse de $k$), pas l'estimation ponctuelle. Une anonymisation qui se
fonde sur l'espérance de $k$ échoue une fois sur deux, par construction.

Sortie du moteur :

```json
{
  "k_hat": 7,
  "k_interval": [3, 14],
  "risk": 0.33,
  "risk_point": 0.14,
  "risk_model": "copula",
  "population_id": "fr-hr-2026",
  "contributing_qi": ["GEN_AGE", "GEN_EDUCATION", "HR_ADMIN_PROCEDURE"],
  "explanation": "..."
}
```

Le champ `contributing_qi` est nécessaire à l'explicabilité et à l'action : la
politique doit savoir **quel** QI généraliser pour faire baisser le risque, ce
qui est la logique de PETRE [@manzanares2025petre].

## 7. Portée : document, thread, auteur

Le risque n'est pas une propriété du document mais du **sujet**, dans une
portée donnée.

| Portée | $Q$ considéré |
|--------|---------------|
| `document` | QI observables dans ce document seul |
| `thread` | Union des QI du fil |
| `author` | Union des QI de tout l'historique connu du sujet |

$$
Q_{doc} \subseteq Q_{thread} \subseteq Q_{author}
\quad\Longrightarrow\quad
k_{author} \leq k_{thread} \leq k_{document}
$$

**Conséquence architecturale** : le moteur de risque DOIT accepter un état
d'historique (`author_history`), et la politique d'anonymisation DOIT pouvoir
être appliquée au niveau auteur avec un état persistant. Un système qui traite
chaque document indépendamment sous-estime systématiquement le risque sur les
forums et les fils de support.

C'est une exigence issue de [`forum-qi-bench §4`](../datasets/forum-qi-bench.md).

## 8. Calibration

Un score discriminant ne suffit pas ; il doit être **calibré** pour que la
politique par seuils ait un sens (SPEC-07 §3).

| Étape | Méthode |
|-------|---------|
| Calibration | Régression isotonique ou Platt scaling sur un split de calibration dédié |
| Split | **Distinct** du test — un split `calib` est réservé dans chaque corpus |
| Mesure | ECE, Brier, courbe de fiabilité |
| Re-calibration | Par domaine et par langue (un score calibré sur le RH FR ne l'est pas sur le support EN) |

La recalibration par domaine est une exigence, pas un raffinement : les
distributions de $k$ diffèrent trop entre les trois domaines.

## 9. Seuils et politique

Seuils initiaux, **expérimentaux et non juridiques** :

| $k$ estimé | Risque approx. | Niveau | Action par défaut |
|-----------:|---------------:|--------|-------------------|
| ≥ 20 | ≤ 5 % | faible | `KEEP` |
| 10–19 | 5–10 % | modéré | `GENERALIZE` |
| 5–9 | 10–20 % | élevé | `GENERALIZE` puis `SUPPRESS` si insuffisant |
| 3–4 | 25–33 % | très élevé | `SUPPRESS` |
| 2 | 50 % | critique | `SUPPRESS` |
| 1 | 100 % | critique | `SUPPRESS` |

Correspondance avec les paramètres classiques de k-anonymité : $k$ = 2, 3, 5, 10
→ risques prosecutor de 50 %, 33 %, 20 %, 10 % [@prasser2020arx].

Ces seuils vivent dans `configs/policy/*.yaml` et définissent les points de
fonctionnement P0…P4 de [SPEC-07 §6](SPEC-07-metriques.md). Ils ne sont **pas**
codés en dur.

### Algorithme de la politique

```
tant que risk(Q) > seuil et actions_possibles non vide :
    choisir l'action qui maximise  Δrisk / Δutilité_perdue
    appliquer, recalculer Q et risk
si risk(Q) > seuil :
    SUPPRESS les QI restants du contributing_qi
```

Le critère $\Delta risk / \Delta utilit\acute{e}$ est ce qui distingue une
anonymisation pilotée par le risque d'un masquage aveugle : il cherche le
**minimum de dégâts** pour atteindre le seuil. C'est aussi ce qui produit une
frontière privacy-utility intéressante plutôt qu'un point.

## 10. Ce que le moteur ne fait pas (v1)

Limites assumées, à déclarer dans toute publication :

| Hors périmètre | Raison |
|----------------|--------|
| QI stylométriques | Chantier à part entière ; le style est identifiant mais non modélisable dans ce formalisme |
| QI relationnels (graphe social) | Nécessiterait un modèle de risque sur graphe |
| Connaissance externe de l'attaquant | Traité empiriquement par l'attaquant C (SPEC-08), pas par le moteur |
| Corrélations temporelles longues | Un $k$ est calculé à un instant donné |

## 11. Critères de sortie

- [ ] Les quatre modèles de risque sont implémentés et testés.
- [ ] Les trois populations sont construites et documentées.
- [ ] Le modèle copule est validé contre le $k$ exact du parc support (erreur
      mesurée et publiée).
- [ ] Le moteur produit un intervalle, pas un point.
- [ ] La calibration atteint un ECE < 0.05 par domaine sur le split de
      calibration.
- [ ] L'invariant $k_{author} \leq k_{thread} \leq k_{document}$ est vérifié par
      test sur les trois corpus.
- [ ] `contributing_qi` permet effectivement de réduire le risque en généralisant
      (test : généraliser un QI listé fait baisser le risque ; généraliser un QI
      non listé ne le fait pas).

## 12. Journal des modifications

| Version | Date | Changement |
|---------|------|-----------|
| 0.9 | 2026-08-30 | Création. Quatre modèles de risque, format de population, hiérarchies de généralisation, portées, calibration. Brouillon : le modèle copule reste à spécifier en détail. |
