# 02 — État de l'art : datasets et métriques pour la détection de QI indirects et l'anonymisation adaptative

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date de clôture de la revue** | 2026-08-30 |
| **Périmètre** | Datasets, métriques, systèmes d'anonymisation guidée par le risque |

> **Note de traçabilité.** Les volumétries, identifiants arXiv et chiffres cités
> proviennent de la revue de littérature close le 30 août 2026 et sont
> référencés dans [`references.bib`](references.bib). Les entrées marquées
> `[à revérifier]` n'ont pas été reconfirmées à la source depuis cette date et
> doivent l'être avant toute publication.

---

## 1. Le point de bascule : RAT-Bench

La conclusion la plus importante de cette revue est un **changement de situation
scientifique**.

Le document de cadrage initial du projet affirmait qu'« aucune méthode ne fait le
pont texte libre → score combinatoire ». Cette affirmation était raisonnable au
moment du premier cadrage ; elle est **désormais trop forte**.

**RAT-Bench** [@krco2026ratbench] fournit une démonstration publique qu'on peut
partir du texte, inférer des QI, puis estimer directement un risque populationnel
de ré-identification. Le pont commence à exister.

Conséquence directe sur le positionnement : la contribution du projet ne peut
plus être « premier système qui calcule le risque de ré-identification depuis du
texte ». Elle doit être reformulée — voir
[03-lacunes-et-contribution](03-lacunes-et-contribution.md).

---

## 2. Principe directeur : une batterie, pas un dataset

Il ne faut **pas** chercher un jeu de données unique. Le benchmark doit être une
**batterie de benchmarks complémentaires**, chacun répondant à une des quatre
questions du cadrage. Aucun corpus existant ne couvre à la fois : QI indirects,
combinaisons, domaines RH/support/forums, multilinguisme FR, et population de
référence européenne.

Hiérarchie retenue :

| Niveau | Rôle | Datasets |
|--------|------|----------|
| A | Risque et ré-identification end-to-end | RAT-Bench |
| B | Annotation QI et métriques privacy-oriented | TAB, IPI |
| C | Inférence d'attributs, domaine forums | SynthPAI |
| D | PII explicite multilingue | OpenPII 500k, JobStack |
| E | Robustesse et généralisation | MultiCoNER II, MEDDOCAN |
| F | Domaine métier réel | Corpus RH / support / forums **à construire** |

---

## 3. Niveau A — RAT-Bench : benchmark principal de ré-identification

### 3.1 Pourquoi il est central

RAT-Bench [@krco2026ratbench] est le dataset public le plus proche de l'objectif
« texte libre → QI → risque de ré-identification ».

Il génère des textes à partir de **statistiques démographiques réelles**,
introduit des identifiants **directs et indirects**, contrôle plusieurs niveaux
de difficulté, puis évalue la capacité d'un **attaquant LLM** à récupérer les
attributs et à ré-identifier la personne. Le risque est ensuite calculé sur une
**population de référence**.

Le benchmark distingue explicitement :

- identifiant direct / identifiant indirect ;
- formulation explicite standard / formulation non standard ;
- information implicite ;
- difficulté variable ;
- plusieurs langues ;
- plusieurs scénarios.

Le point décisif est qu'il **ne s'arrête pas au F1 du détecteur** : il applique un
attaquant, puis estime le risque de ré-identification dans la population.

### 3.2 Résultats saillants

Le papier rapporte une augmentation du risque lorsque les identifiants deviennent
non standards, passant d'environ **44 % à 69 %** selon les régimes de difficulté,
et souligne que les informations exprimées **implicitement** restent très
difficiles à anonymiser.

Ce second point est le cœur du problème visé par ce projet.

### 3.3 Couverture

| Besoin | RAT-Bench |
|--------|----------:|
| Identifiants directs | Oui |
| Identifiants indirects | **Oui** |
| Combinaisons de QI | **Oui** |
| Génération contrôlée | Oui |
| Plusieurs langues | Oui |
| Difficulté contrôlée | **Oui** |
| Attaquant | **Oui** |
| Risque de ré-identification | **Oui** |
| Population de référence | **Oui, US** |
| RH | Partiellement transférable |
| Support / helpdesk | Partiellement transférable |
| France / Europe | Pas idéal |
| Texte réel | Non, synthétique |

### 3.4 Verdict

**Dataset public n°1 à intégrer.** Mais **pas** le dataset final : il est
synthétique, centré sur des statistiques américaines, et ne modélise pas finement
les distributions RH ou support européennes. Le papier appelle lui-même à
l'extension à d'autres géographies.

Fiche détaillée : [`../datasets/rat-bench.md`](../datasets/rat-bench.md).

---

## 4. Niveau B — TAB : référence pour l'annotation des QI

**TAB** (Text Anonymization Benchmark) [@pilan2022tab] contient **1 268 affaires
de la Cour européenne des droits de l'homme**, avec annotations riches des
informations personnelles, des types d'identifiants, des attributs confidentiels
et des **coréférences**.

La différence essentielle : TAB a été conçu comme un problème
d'**anonymisation**, et non comme du NER. Il pose implicitement la question

> quelles informations doivent être masquées pour empêcher la divulgation de
> l'identité ?

et non

> quels tokens sont des noms ?

### 4.1 Métriques proposées par TAB

- **entity-level recall** pour les identifiants directs ;
- **entity-level recall** pour les quasi-identifiants ;
- **weighted token-level precision** sur l'ensemble ;
- une mesure d'utilité tenant compte de l'information portée par le token masqué.

Ces quatre métriques sont reprises telles quelles dans
[SPEC-07 §1](../specifications/SPEC-07-metriques.md).

### 4.2 Verdict

**Dataset n°2, indispensable** pour la couche d'annotation et pour les métriques
de *privacy-oriented NER*. Son domaine légal ne doit cependant pas devenir le
benchmark principal du projet.

Fiche : [`../datasets/tab.md`](../datasets/tab.md).

---

## 5. Niveau B — IPI / MIMIC-III : source de la taxonomie

Le travail de Baroud et al. [@baroud2025ipi] est particulièrement intéressant
parce qu'il ne se limite pas aux PII classiques. Les auteurs proposent un schéma
de **neuf catégories d'identifiants indirects**, construit en tenant compte de
plusieurs adversaires possibles, et annotent **100 discharge summaries MIMIC-III**
avec **6 199 annotations**. Les guidelines et les spans sont associés aux
documents MIMIC-III correspondants.

### 5.1 Usage retenu

Construire la taxonomie QI du projet à partir de **TAB + IPI + attributs propres
au domaine**, plutôt que d'inventer un schéma *ex nihilo*.

### 5.2 Extension au domaine RH

QI candidats : tranche d'âge · ancienneté · diplôme · fonction · niveau
hiérarchique · département · localisation · historique professionnel · type de
contrat · combinaison employeur × rôle × localisation · événements
professionnels rares.

### 5.3 Extension au domaine support

QI candidats : produit · version · OS · type de terminal · localisation · fuseau
horaire · horaire d'incident · rôle utilisateur · environnement technique ·
combinaison produit × version × organisation × heure.

C'est précisément ce type de combinaison que le détecteur doit apprendre à
traiter comme un **objet de risque unique**, et non comme trois entités
indépendantes.

Fiche : [`../datasets/ipi-mimic.md`](../datasets/ipi-mimic.md).
Taxonomie dérivée : [SPEC-01](../specifications/SPEC-01-taxonomie-qi.md).

---

## 6. Niveau C — SynthPAI : le benchmark forums

**SynthPAI** [@yukhymenko2024synthpai] contient **7 823 commentaires**, issus de
**103 threads** et **300 profils synthétiques**, avec des attributs personnels :
âge, sexe, revenu, localisation, lieu de naissance, éducation, profession, statut
relationnel.

Le dataset a été conçu pour étudier l'**inférence d'attributs personnels à partir
de texte en ligne**. C'est donc une excellente base pour tester les deux étapes :

$$
\text{texte} \rightarrow \text{attributs personnels}
\qquad\text{puis}\qquad
\text{attributs} \rightarrow \text{risque}
$$

**Limite** : les personnes sont synthétiques. Excellent pour des expériences
contrôlées, moins crédible comme mesure finale de robustesse en production.

Atout structurel majeur pour ce projet : SynthPAI possède déjà la structure
`profil latent → plusieurs messages`, qui est exactement celle du corpus RH /
support à construire (voir [SPEC-05](../specifications/SPEC-05-generation-corpus-synthetiques.md)).

Fiche : [`../datasets/synthpai.md`](../datasets/synthpai.md).

---

## 7. Niveau D — OpenPII / AI4Privacy : couche PII multilingue

`ai4privacy/open-pii-masking-500k` [@ai4privacy2024openpii] fournit des centaines
de milliers d'exemples annotés, **20 classes PII** et **8 langues**, dont le
français — la carte du dataset indique plus de **112 000 exemples en français**
dans cette version.

Utile pour : noms, emails, téléphones, adresses, identifiants, autres catégories
PII, et entraînement multilingue.

### 7.1 Avertissement

> **OpenPII ≠ benchmark de QI indirects.**

Un modèle peut obtenir un excellent F1 sur OpenPII et échouer complètement sur
« je suis le seul doctorant de mon équipe à travailler sur ce sujet ». C'est un
problème récurrent des benchmarks récents : les performances élevées sur PII
synthétiques ne garantissent pas une protection contre la ré-identification par
combinaison d'attributs. RAT-Bench [@krco2026ratbench] confirme explicitement ce
décalage.

Fiche : [`../datasets/openpii-500k.md`](../datasets/openpii-500k.md).

---

## 8. Niveau D — JobStack : RH, mais insuffisant

**JobStack** [@jensen2021jobstack] est un corpus consacré à la désidentification
dans les **offres d'emploi**, traitant notamment la détection d'informations
privées telles que noms et coordonnées.

Utile comme benchmark de **PII explicite dans le domaine RH**. En revanche, ce
n'est pas un benchmark de

$$
\text{emploi} + \text{ancienneté} + \text{localisation} + \text{trajectoire} \rightarrow k
$$

Donc : utile pour la première passe, pas pour la métrique finale.

Fiche : [`../datasets/jobstack.md`](../datasets/jobstack.md).

---

## 9. Niveau E — MultiCoNER II : stress-test linguistique

**MultiCoNER II** [@fetahu2023multiconer] n'est pas un dataset de
confidentialité, mais il couvre le français, l'anglais, l'allemand, l'espagnol,
l'italien, le portugais, le suédois, l'ukrainien, le chinois, etc., et comprend un
**sous-ensemble bruité**.

Utile pour mesurer la robustesse du détecteur lorsqu'une information apparaît
dans une formulation inhabituelle, dans un texte bruité, ou dans une autre langue.
Classé **secondaire** pour le benchmark de privacy.

Fiche : [`../datasets/multiconer2.md`](../datasets/multiconer2.md).

---

## 10. Niveau E — MEDDOCAN : généralisation cross-domaine

**MEDDOCAN** [@marimon2019meddocan] est un corpus espagnol de désidentification
clinique avec annotations gold-standard. Hors domaine, mais utile pour vérifier
que le pipeline : ne dépend pas du domaine RH, détecte des formes linguistiques
différentes, reste stable en espagnol, et fonctionne sur du texte sensible à
forte densité d'informations.

À n'utiliser que dans un test de **généralisation cross-domaine**.

Fiche : [`../datasets/meddocan.md`](../datasets/meddocan.md).

---

## 11. Niveau F — Le dataset manquant

C'est l'une des conclusions scientifiques les plus importantes de cette revue :
**le benchmark principal du projet ne peut pas être constitué uniquement de
datasets publics existants.**

Il faut construire un **Indirect-QI Re-identification Benchmark** couvrant trois
domaines :

- **RH** — profils, candidatures, tickets RH simulés ou dé-identifiés
  (« 28 ans, doctorant, six ans d'expérience, PME de 400 employés, Paris,
  spécialiste X… ») ;
- **Forums** — messages utilisateur, avec historique de plusieurs messages ;
- **Support** — tickets avec timestamps, produit, configuration, organisation,
  localisation.

**Exigence structurante** : chaque individu doit avoir un **profil latent**.

```text
PERSON_ID     = P01742
age           = 28
education     = PhD
occupation    = researcher
location      = Lille
employer_size = 300-500
product       = X
support_role  = administrator
```

puis plusieurs observations textuelles de cette même personne. Le benchmark
contient alors la chaîne complète :

```text
profile
  ↓
documents / posts / tickets
  ↓
QI expressed
  ↓
QI implicit
  ↓
QI combination
  ↓
ground-truth population
```

C'est ce qui permet de mesurer le **k combinatoire réel**.

Spécification : [SPEC-05](../specifications/SPEC-05-generation-corpus-synthetiques.md).
Fiches : [`hr-qi-bench`](../datasets/hr-qi-bench.md),
[`support-qi-bench`](../datasets/support-qi-bench.md),
[`forum-qi-bench`](../datasets/forum-qi-bench.md).

---

## 12. Métriques : architecture à 5 niveaux

L'erreur principale à éviter :

> F1 de détection = anonymisation réussie.

C'est faux. L'architecture métrique retenue comporte cinq niveaux. Formules
complètes et seuils : [SPEC-07](../specifications/SPEC-07-metriques.md).

### Niveau 1 — Détection des spans

$P = \frac{TP}{TP+FP}$, $R = \frac{TP}{TP+FN}$, $F1 = \frac{2PR}{P+R}$.

Priorité : **QI Recall > QI Precision**, un faux négatif de confidentialité étant
plus grave qu'un faux positif — cohérent avec la logique privacy-first de TAB
[@pilan2022tab].

À publier, par ordre d'importance : macro-F1 par catégorie QI, F1 par langue, F1
par domaine, F1 par difficulté (**très élevée**) ; span recall, span F1,
type-aware F1 (**élevée**) ; span precision (moyenne).

### Niveau 2 — Détection combinatoire

C'est ici que le travail devient original. Le système ne doit pas seulement
produire `âge → QI`, `doctorant → QI`, `arrêt maladie → QI` ; il doit savoir que
`âge + doctorant + contexte RH` constitue une **combinaison de risque**.

**QI Combination Recall (QICR)** :

$$
QICR = \frac{\#\text{combinaisons de QI à risque correctement détectées}}
             {\#\text{combinaisons de QI réellement à risque}}
$$

Exemple. Vérité terrain `{age<30, PhD, location=Lille, department=Physics}` ;
système `{age<30, PhD, location=Lille}`. Les éléments individuels sont détectés,
la combinaison complète est manquée. Le F1 classique ne mesure pas cette erreur.

**Risky Combination Recall @ k** :

$$
RCR@k = P(\hat{k} \geq k \mid k_{true} \geq k)
$$

Autrement dit : le système reconnaît-il correctement les situations où il existe
assez de personnes pour que le risque soit acceptable ?

### Niveau 3 — Qualité du score de risque

Un score `risk = 0.73` ne suffit pas ; il doit être **calibré**.

- Erreur sur k : $MAE_k = \frac1N\sum_i |\hat{k_i} - k_i|$, ou plus robuste
  $MALE_k = \frac1N\sum_i |\log(\hat{k_i}+1) - \log(k_i+1)|$ ;
- Erreur de risque : $MAE_R = \frac1N\sum_i |\hat{R_i} - R_i|$ ;
- **AUROC** (risque élevé vs acceptable) ;
- **AUPRC**, à privilégier quand les cas fortement risqués sont rares ;
- **Brier score** ;
- **ECE** (Expected Calibration Error).

La calibration est une exigence fonctionnelle, pas un raffinement : la politique
configurable

```text
risk < 0.05    → garder
0.05 – 0.10    → généraliser
0.10 – 0.20    → anonymiser
> 0.20         → supprimer
```

n'a de sens que si le score est calibré, et pas seulement discriminant.

### Niveau 4 — Résistance à la ré-identification (métrique principale)

$$
R_{succ} = \frac{\#\text{documents ré-identifiés}}{\#\text{documents}}
\qquad \text{(plus bas = meilleur)}
$$

C'est la logique de RAT-Bench [@krco2026ratbench] : un attaquant tente d'inférer
les identifiants, puis le benchmark estime le risque dans la population.

**C'est la métrique principale du projet.**

Compléments : top-1 identity accuracy ; top-5 identity accuracy ;

$$
DILR = \frac{\#\text{docs contenant un identifiant direct récupérable}}{\#\text{docs}}
\qquad
IRR = \frac{\#\text{docs ré-identifiés par QI}}{\#\text{docs}}
$$

La distinction **direct privacy leakage** vs **combinatorial indirect leakage**
sera un résultat important à publier séparément.

### Niveau 5 — Utilité

Il faut éviter de conclure qu'« anonymisation maximale = système optimal ». TAB
insiste sur ce point et propose des métriques tenant compte de la quantité
d'information supprimée [@pilan2022tab].

**A. Utilité textuelle (secondaire)** : BERTScore, BLEU, ROUGE, similarité
d'embeddings — utilisées par des cadres récents comme Tau-Eval
[@loiseau2025taueval]. Ne doivent **pas** être la métrique d'utilité principale.

**B. Utilité métier (principale)** :

- RH : classification métier, extraction de compétences, classification de poste,
  matching compétence/emploi ;
- Support : classification de ticket, routage, détection de priorité, prédiction
  d'intention, suggestion de résolution ;
- Forums : classification de thème, sentiment, modération, détection de sujet,
  clustering.

$$
UtilityRetention = \frac{Performance(\text{anonymized})}{Performance(\text{original})}
$$

Exemple : routage de tickets, F1 original 0.91 → F1 anonymisé 0.88 → rétention
96.7 %. Beaucoup plus parlant industriellement. Tau-Eval pousse exactement vers
cette évaluation *task-aware* plutôt que vers une simple similarité textuelle
[@loiseau2025taueval].

### Le compromis privacy–utility

Le système doit être évalué comme un compromis
$\text{Privacy} \leftrightarrow \text{Utility}$, et non comme
$\text{F1} \rightarrow \text{score final}$. Il faut tracer la frontière à
plusieurs intensités d'anonymisation — orientation prise par Tau-Eval
[@loiseau2025taueval] et les travaux d'anonymisation adaptative.

---

## 13. Systèmes existants

### 13.1 PETRE — anonymisation guidée par le risque

**PETRE** [@manzanares2025petre] est la référence conceptuelle la plus proche de
la logique « score de risque → action d'anonymisation ». Il améliore une
anonymisation existante en contrôlant explicitement la réduction du **risque
empirique de ré-identification**, s'appuie sur une forme de **k-anonymité
probabiliste**, et permet de spécifier un risque maximal acceptable.

C'est très proche de la politique visée :

```text
risk < seuil     → aucune action
risk moyen       → généralisation
risk élevé       → masquage / réécriture
risk critique    → suppression
```

**Différence du projet** : rendre le moteur de risque beaucoup plus explicite sur
les **QI combinatoires** et sur les domaines RH / support / forums.

### 13.2 ARX — la logique de politique

**ARX** [@prasser2020arx] traite des données structurées, mais reste
conceptuellement très utile : il sait raisonner avec k-anonymity, k-map, average
risk, population-based risk, et **plusieurs modèles d'attaquants**.

ARX montre surtout qu'il faut distinguer : risque **maximal**, risque **moyen**,
**fraction de population ré-identifiable**, et **combinaison de QI**. C'est
exactement ce qu'il faut reproduire dans un moteur travaillant sur du texte.

### 13.3 Rocher et al. — populations incomplètes

L'approximation $R = 1/k$ est insuffisante quand la population de référence est
incomplète. Le modèle par **copule** de Rocher et al. [@rocher2019estimating]
permet d'estimer la probabilité de ré-identification même dans des jeux de
données incomplets. C'est la base retenue pour
[SPEC-06](../specifications/SPEC-06-population-et-risque.md).

### 13.4 SEAL — anonymiseur local à petit modèle

**SEAL** [@kim2025seal] est particulièrement pertinent pour la contrainte
« local < 30 B » : il montre qu'un modèle **8 B spécialisé**, obtenu par
distillation adversariale, peut atteindre un compromis privacy-utility proche
d'un anonymiseur GPT-4, et améliorer encore ses performances par
**self-refinement**.

### 13.5 AURA et InferLink — l'attaquant agentique

**AURA** [@li2026aura] montre que l'agent doté de recherche web **modifie le
modèle de menace** : des indices faibles peuvent être reliés à des sources
publiques et conduire à une ré-identification.

**InferLink** [@ko2026inferlink] va plus loin en séparant le **type de cue**,
l'**intention**, et la **connaissance préalable de l'attaquant** ; ses métriques
automatiques incluent le succès de linkage et la réalisation correcte de la tâche.

Ces deux travaux justifient le niveau d'attaquant C de
[SPEC-08](../specifications/SPEC-08-attaquants.md).

### 13.6 Tau-Eval — évaluation task-aware

**Tau-Eval** [@loiseau2025taueval] est un cadre unifié d'évaluation de
l'anonymisation « utile et privée », qui structure l'évaluation autour des tâches
en aval plutôt que de la seule similarité textuelle. Sert de référence pour le
niveau 5 des métriques.

---

## 14. Modèles à évaluer

Sous contrainte < 30 B, ne pas faire un benchmark de dix LLM. Comparer **trois
familles** :

| Baseline | Contenu | Objectif |
|----------|---------|----------|
| **B1 — règles** | Presidio | Très rapide, indispensable comme plancher |
| **B2 — encodeur léger** | XLM-R, GLiNER | Mesurer le rapport coût / rappel |
| **B3 — petit LLM** | Qwen 7B, Llama 8B, Mistral 7B | Capacité d'inférence implicite |

La question posée au benchmark ne doit pas être « lequel donne le meilleur F1 ? »
mais « lequel produit le meilleur triplet **risk reduction / utility /
latency** ? ». Les travaux récents montrent que les LLM améliorent nettement la
frontière privacy-utility, au prix d'une charge computationnelle supérieure
[@krco2026ratbench] ; SEAL [@kim2025seal] indique qu'un 8 B spécialisé peut
suffire.

---

## 15. Conclusion de l'état de l'art

Diagnostic :

- **Le domaine des PII est mûr.**
- **Le domaine des quasi-identifiants textuels est encore jeune.**
- **Le risque combinatoire à partir du texte devient un axe actif.**
- **Le domaine RH / support multilingue reste nettement sous-benchmarké.**

Le point le plus important reste que RAT-Bench a changé la situation : partir du
texte, inférer des QI, puis estimer un risque populationnel est désormais
publiquement démontré. L'angle de recherche le plus solide n'est donc plus
« inventer le pont », mais **l'adapter et le généraliser aux environnements RH,
forums et support, en multilingue, avec un score de risque calibré, une taxonomie
explicite des combinaisons de QI et une politique d'anonymisation automatique
configurable par seuil**.

Suite : [03-lacunes-et-contribution](03-lacunes-et-contribution.md).
