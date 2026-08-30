# Notations mathématiques

Notations utilisées dans le rapport et les spécifications. Toute spec qui
introduit une notation nouvelle DOIT l'ajouter ici.

---

## Ensembles et individus

| Notation | Signification |
|----------|---------------|
| $P$ | Population de référence |
| $S$ | Échantillon / jeu de données évalué, $S \subseteq P$ |
| $p, i$ | Un individu de la population |
| $d$ | Un document |
| $D$ | L'ensemble des documents évalués |

## Quasi-identifiants

| Notation | Signification |
|----------|---------------|
| $c_j$ | Un code de catégorie QI (SPEC-01 §4) |
| $v_j$ | Une valeur normalisée |
| $Q(d) = \{(c_j, v_j)\}$ | L'ensemble des QI observés dans $d$ |
| $\hat{Q}$ | Les QI **inférés** par le système ou par l'attaquant |
| $m = \|Q\|$ | Taille de la combinaison |
| $p[c] \models v$ | L'individu $p$ satisfait la contrainte $v$ sur l'attribut $c$ |

Le symbole $\models$ remplace l'égalité : les valeurs peuvent être des
intervalles (`[18,29]`) ou des niveaux hiérarchiques (`FR-59`).

## Risque

| Notation | Définition |
|----------|-----------|
| $\mathrm{EC}_P(Q)$ | $\{p \in P : \forall j,\ p[c_j] \models v_j\}$ |
| $k(Q)$ | $\|\mathrm{EC}_P(Q)\|$ |
| $\hat{k}$ | $k$ estimé par le moteur |
| $[\hat{k}_{low}, \hat{k}_{high}]$ | Intervalle d'incertitude sur $\hat{k}$ |
| $R_{pros}(Q)$ | $1/k(Q)$ — modèle prosecutor |
| $R_{jour}(Q)$ | $1/k_P(Q)$ — modèle journalist (k-map) |
| $R_{mark}$ | $\frac{1}{\|S\|}\sum_i 1/k(Q_i)$ — modèle marketer |
| $R_{cop}(Q)$ | $P(\text{unicité} \mid Q, P)$ — modèle par copule |
| $k_{seuil}$ | Seuil de « combinaison à risque », défaut 10 |

## Portées

$$
Q_{doc} \subseteq Q_{thread} \subseteq Q_{author}
\quad\Longrightarrow\quad
k_{author} \leq k_{thread} \leq k_{document}
$$

## Détection

| Notation | Définition |
|----------|-----------|
| $TP, FP, FN$ | Vrais positifs, faux positifs, faux négatifs |
| $P$ (contexte détection) | $TP/(TP+FP)$ — précision |
| $R$ | $TP/(TP+FN)$ — rappel |
| $F1$ | $2PR/(P+R)$ |
| $F_\beta$ | $\frac{(1+\beta^2)PR}{\beta^2 P + R}$, $\beta = 2$ en privacy-first |

> ⚠️ Collision de notation : $P$ désigne la **population** dans les sections de
> risque et la **précision** dans les sections de détection. Le contexte lève
> l'ambiguïté ; en cas de doute, écrire $P_{pop}$ et $P_{prec}$.

## Combinatoire

$$
QICR = \frac{\#\text{combinaisons à risque correctement détectées}}
             {\#\text{combinaisons réellement à risque}}
$$

$$
QICR@j = QICR \text{ restreint aux combinaisons de taille } j
$$

$$
RCR@k = P\big(\hat{k} \geq k \mid k_{true} \geq k\big)
$$

## Calibration

$$
MAE_k = \frac1N\sum_i |\hat{k_i} - k_i|
\qquad
MALE_k = \frac1N\sum_i \big|\log(\hat{k_i}+1) - \log(k_i+1)\big|
$$

$$
MAE_R = \frac1N\sum_i |\hat{R_i} - R_i|
\qquad
\text{Brier} = \frac1N\sum_i (\hat{R_i} - y_i)^2
$$

$$
ECE = \sum_{b=1}^{B} \frac{|B_b|}{N}\,\big|\,\overline{y}(B_b) - \overline{\hat{R}}(B_b)\,\big|
$$

$B$ = nombre de bacs d'équi-effectif, défaut 10.

## Ré-identification

$$
R_{succ} = \frac{\#\text{documents ré-identifiés}}{\#\text{documents}}
$$

$$
DILR = \frac{\#\text{docs avec identifiant direct récupérable}}{\#\text{docs}}
\qquad
IRR = \frac{\#\text{docs ré-identifiés par QI}}{\#\text{docs}}
$$

## Utilité

$$
UtilityRetention = \frac{Performance(\text{anonymized})}{Performance(\text{original})}
$$

## Conventions typographiques

- Les **codes de catégorie** sont en capitales avec préfixe de bloc :
  `GEN_AGE`, `HR_SENIORITY`, `SUP_VERSION`.
- Les **statuts et énumérations** sont en capitales : `QUASI`, `IMPLICIT`,
  `OFFICIAL`.
- Les **clés de dataset** sont en minuscules avec underscore : `hr_qi`,
  `support_qi`, `multiconer2`.
- Les **noms de métriques** sont en anglais dans le code, en français ou anglais
  dans le texte selon l'usage établi ($R_{succ}$, QICR, Utility Retention).
