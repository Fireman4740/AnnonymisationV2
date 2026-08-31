# 04 — Datasets d'évaluation et métriques : révision d'avril 2026

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date** | 2026-08-30 |
| **Remplace** | complète et corrige [`02-etat-de-l-art.md`](02-etat-de-l-art.md) §12 |
| **Impact normatif** | [SPEC-07](../specifications/SPEC-07-metriques.md) v2.0 |

---

## 1. Le résultat qui justifie toute l'architecture d'évaluation

Sur le benchmark **SPIA** [@oh2026spia], un système de masquage NER
(Longformer) atteint :

$$
ER_{di} = 0{,}997 \qquad \text{mais} \qquad CPR = 0{,}330
$$

Autrement dit : **99,7 % des identifiants directs sont masqués, et pourtant
deux tiers des informations personnelles restent inférables par un LLM
adversaire.**

Ce n'est pas une hypothèse, c'est une mesure. C'est la démonstration empirique
directe que :

1. la **détection** et le **risque résiduel** doivent être évalués séparément,
   avec des datasets et des métriques différents ;
2. un F1 de détection, même excellent, **ne prédit pas** la protection réelle ;
3. la problématique du projet — le risque combinatoire par inférence — est
   réelle et non couverte par les pipelines de masquage existants.

C'est le chiffre à mettre en tête de toute publication issue du projet.

## 2. Les quatre axes d'évaluation

Confondre ces axes est l'erreur la plus fréquente de la littérature.

| Axe | Ce qu'il mesure | Erreur si confondu |
|-----|-----------------|--------------------|
| **A — Détection** | Le modèle trouve-t-il les bons spans de QI ? | Un F1 de 0,99 ne dit rien sur le risque résiduel |
| **B — Risque de ré-identification** | Quelle probabilité qu'un adversaire retrouve la personne ? | C'est la métrique métier réelle, indépendante du rappel de spans |
| **C — Utilité** | Le texte reste-t-il exploitable ? | Sans elle, on optimise vers la suppression totale : `k` infini, texte inutile |
| **D — Robustesse adversariale** | Le système résiste-t-il à un attaquant qui **infère** au lieu de lire ? | C'est l'axe qui capture l'exemple canonique du projet (doctorant / arrêt maladie) |

Correspondance avec les cinq niveaux de [SPEC-07](../specifications/SPEC-07-metriques.md) :

| Axe | Niveaux SPEC-07 |
|-----|-----------------|
| A | 1 (spans) et 2 (combinaisons) |
| B | 3 (qualité du score de risque) |
| C | 5 (utilité) |
| D | 4 (résistance à la ré-identification) |

L'architecture en 5 niveaux est donc conservée ; ce document en **précise les
métriques concrètes**.

---

## 3. Datasets — inventaire révisé

### 3.1 Nouveaux datasets à intégrer

| Dataset | Taille | Langue | Apport | Licence |
|---------|-------:|--------|--------|---------|
| **SPIA** [@oh2026spia] | 675 documents (144 TAB + 531 PANORAMA), **1 712 sujets**, 7 040 PII, 15 catégories | EN | **Premier dataset multi-sujets avec métriques d'inférence par sujet** | MIT + CC BY 4.0 |
| **PANORAMA** [@selvam2025panorama] | 384 789 documents | EN | Grande échelle, **cohérence d'attributs forcée** (âges familiaux, éducation-emploi) | CC BY 4.0 |

Ces deux corpus sont **ouverts et redistribuables**, contrairement à
PersonalReddit et MIMIC-III. Ils entrent au niveau de priorité P0 pour l'axe D.

### 3.2 Corrections sur les datasets déjà fichés

| Dataset | Correction |
|---------|-----------|
| **PersonalReddit** | 520 profils **réels**, non redistribué pour raisons de vie privée. ⚠️ Contredit ce que le README du cache local laissait entendre — voir §6. |
| **SynthPAI** | Proxy **libre** de PersonalReddit, écart < 12,5 % vs données réelles. C'est ce chiffre qui légitime son usage en remplacement. |
| **IPI** | Confirmation : guidelines et identifiants publiés, **pas les documents**. Cohérent avec l'abandon de PhysioNet. |
| **TAB** | 1 268 arrêts, dont **144 repris dans SPIA** — permet une comparaison directe avec la littérature multi-sujets. |
| **ai4privacy OpenPII** | Jusqu'à 1 M d'exemples, **30 langues** dont le français. Axe A uniquement. |

### 3.3 La lacune RH / support / forums FR — confirmée

Après recherche complémentaire, **aucun dataset académique annoté en QI/PII
n'existe pour les domaines RH et support client**.

| Domaine | Ce qui existe | Ce qui manque |
|---------|---------------|---------------|
| **RH** | Job postings [@jensen2021jobstack] ; *Degendering Resumes* (arXiv 2112.08910) qui démontre la fuite de QI via proxies même sans nom ; prototype CV Europass | Aucune annotation QI combinatoire, aucun score de risque |
| **Support** | Sources industrielles non peer-reviewées (Lorikeet, OpenRedaction, Supportbench) ; dataset Endava/Microsoft (~50k tickets) **déjà anonymisé et non ré-annoté** | Tout |
| **Forums FR** | — | Aucun équivalent de SynthPAI/PersonalReddit en français |

> **Conséquence directe** : construire un mini-corpus annoté est un
> **prérequis, pas une option**. Il n'existe aucun raccourci dans la
> littérature publique. Cela confirme
> [SPEC-05](../specifications/SPEC-05-generation-corpus-synthetiques.md).

---

## 4. Métriques — définitions normatives

### 4.1 Axe A — détection

**Correspondance de spans : adopter le *partial match*.**

Deux conventions coexistent : *exact match* (bornes identiques) et
*partial/relaxed match* (SemEval-2013 task 9.1, implémenté par le paquet
`nervaluate`). L'argument des auteurs d'IPI est décisif :

> la difficulté principale est de **trouver** l'information et de la retirer ;
> masquer un span un peu trop long ne nuit pas à la personne.

**Recommandation retenue** : partial-match F1 par catégorie comme métrique de
développement rapide du détecteur.

**ER_di et ER_qi — recall au niveau entité, pas mention.** Si un nom apparaît
4 fois et que 3 occurrences sont masquées, l'entité **n'est pas protégée** : la
4ᵉ mention suffit à divulguer l'identité.

- `ER_di` : proportion d'identifiants **directs** entièrement masqués.
- `ER_qi` : idem pour les quasi-identifiants.

Précision et rappel se calculent en **micro-moyenne sur plusieurs annotateurs**,
car un document admet plusieurs anonymisations valides — il n'y a pas de gold
standard unique. Cela valide la règle d'agrégation paramétrable retenue pour
l'adaptateur TAB.

**Limites documentées du F1** — trois pièges à ne pas reproduire :

| Piège | Preuve chiffrée |
|-------|-----------------|
| Déséquilibre sur les catégories rares | IPI : macro-F1 **0,55** vs micro-F1 **0,85** ; les catégories critiques sont les moins bien détectées (`CIRCUMSTANCES` F1 = 0,20, `DETAILS` F1 = 0,21) |
| Optimisme sur données synthétiques | PIIBench multi-source et SPY : **< 0,14–0,47** sur corpus réels vs **~0,96** sur ai4privacy synthétique |
| Le F1 ne prédit pas le risque | SPIA : ER_di 0,997 / CPR 0,330 |

> Le F1 de détection n'est fiable que **relativement à son corpus de test**,
> jamais en absolu.

### 4.2 Axe B — risque de ré-identification

**TRIA / TRIR** [@manzanares2024tria] — la métrique la plus proche du besoin.

- **TRIA** (*Text Re-Identification Attack*) : un modèle d'apprentissage
  entraîné à ré-identifier un document anonymisé parmi un ensemble candidat,
  jouant le rôle d'adversaire empirique.
- **TRIR** (*Text Re-Identification Risk*) : métrique de risque dérivée de
  **l'accuracy de ré-identification de TRIA**.

⚠️ **Distinction à ne pas manquer** : TRIA/TRIR (DMKD 2024) et PETRE (KBS 2025)
sont deux travaux **distincts** de la même équipe. **TRIR est la métrique de
risque ; PETRE est la méthode d'anonymisation pilotée par ce risque.** Les deux
sont complémentaires et directement réutilisables.

**k-anonymat probabiliste** [@manzanares2025petre] — relâche la contrainte
stricte du k-anonymat en n'exigeant que l'**équivalence de probabilité de
ré-identification** avec un groupe de taille `k`. Cela le rend calculable sur du
texte libre, sans regrouper explicitement les documents en classes
d'équivalence. C'est exactement le mécanisme « score → seuil configurable »
visé par le projet. Code : `CRISES-research-group/PETRE`.

**Estimateur d'unicité** [@rocher2019estimating] — modèle par copule estimant,
**même sur données incomplètes**, la probabilité qu'un individu soit unique.
AUC entre **0,84 et 0,97 sur 210 populations testées**. C'est la référence pour
calculer un `k` combinatoire quand on ne dispose que d'un échantillon partiel de
la population de référence.

### 4.3 Axe D — robustesse adversariale

**AAC — Adversarial Accuracy** [@staab2024beyond] : un LLM adversaire tente
d'inférer un attribut cible. Notation **1,0 = exact · 0,5 = partiel** (deviner
« Californie » pour « Los Angeles ») **· 0,0 = faux**. Rapporté en top-1
(jusqu'à **85 %**) et top-3 (jusqu'à **95,8 %**) sur PersonalReddit.

> **Limite explicite** : l'AAC ne mesure que la protection du **sujet cible**,
> pas des autres personnes mentionnées. Rédhibitoire pour les tickets support,
> qui citent presque toujours plusieurs personnes.

**CPR / IPR** [@oh2026spia] — généralisation multi-sujets. Soit $N$ sujets,
$O_i$ le nombre de PII vérité-terrain du sujet $i$, $A_i$ le nombre de PII
encore inférables après anonymisation :

$$
CPR = 1 - \frac{\sum_i A_i}{\sum_i O_i}
\qquad\qquad
IPR = \frac{1}{N}\sum_i \left(1 - \frac{A_i}{O_i}\right)
$$

CPR pondère par la **quantité de PII par sujet** ; IPR pondère **chaque sujet
également**. Les publier ensemble : leur écart révèle si la protection est
inégale entre sujets.

**Deux résultats empiriques décisifs pour le projet :**

| Résultat | Conséquence |
|----------|-------------|
| La protection ciblée sur un seul sujet laisse les autres **significativement moins protégés** — jusqu'à **11 points d'écart** entre 1-AAC et CPR sur TAB | Directement transposable à un ticket support mentionnant un collègue, un manager ou un tiers |
| Corrélation de Spearman **ρ > 0,98** entre CPR/IPR calculés avec différents LLM adversaires (GPT-4.1, Claude-Haiku-4.5) | **Un LLM local < 30 B suffit comme adversaire d'évaluation** sans perdre en validité de comparaison — déblocage majeur pour la contrainte du projet |

### 4.4 Axe C — utilité

**Mean Utility** (méthodologie Staab / SPIA) : moyenne de **Readability** et
**Meaning** jugés par un LLM juge, combinés à **ROUGE-L**. Le LLM juge utilisé
doit être documenté.

Attention : BLEU/ROUGE **pénalisent les reformulations légitimes** — généraliser
« 28 ans » en « fin de vingtaine » est une bonne anonymisation qu'une métrique
de surface sanctionne. D'où la nécessité de la **performance downstream**
[@larbi2022which] comme métrique de référence : un ticket anonymisé
reste-t-il correctement routable ?

Compromis observé sur SPIA (Table 4) : DP-Prompt (paraphrase à haute
température) protège mal (CPR ≈ 0,30) ; Adversarial Anonymization protège le
mieux (**CPR/IPR 0,870 / 0,897**) au prix d'une utilité modérément dégradée.

---

## 5. Le vide que ce projet peut combler

Les auteurs de SPIA formulent eux-mêmes la limite de leurs métriques :

> CPR et IPR traitent **toutes les catégories de PII avec un poids égal**, alors
> que le risque réel diffère fortement entre un identifiant direct (SSN) et un
> quasi-identifiant (âge, genre). Travail futur : pondérer par type de PII, ou
> **modéliser le risque combinatoire depuis une perspective k-anonymat**.

**C'est précisément l'espace de contribution du projet.** La formulation retenue
en [03-lacunes §3.2](03-lacunes-et-contribution.md) s'en trouve renforcée et
précisée :

> Combiner **CPR/IPR** (protection multi-sujets, mesurée empiriquement) avec
> **TRIR / k-anonymat probabiliste** (risque combinatoire pondéré par type de
> QI), plutôt que de choisir l'un ou l'autre — et le faire sur les domaines RH,
> forums et support, en multilingue.

## 6. Réserves et points à vérifier

| Réserve | Portée |
|---------|--------|
| **Aucun benchmark de risque (axes B/D) n'existe en français.** PETRE, TRIR, AAC, CPR/IPR, SynthPAI, SPIA sont tous validés en anglais. | La transposition au français est une **hypothèse de travail**, pas un résultat établi. À déclarer dans toute publication. |
| **Aucun dataset RH ou support n'a jamais servi à calculer CPR/IPR, TRIR ou AAC.** Ces métriques sont validées sur juridique (TAB) et forums. | Leur transférabilité à des tickets courts ou des CV **reste à démontrer empiriquement**. C'est un résultat à produire, pas à supposer. |
| **PersonalReddit : 520 profils réels, non redistribués.** | ⚠️ **Contredit** le README du cache local (`Reddit_synthetic/`), qui le présente comme synthétique. À trancher avant toute mesure — voir ticket [F-6](../tickets/EPIC-F-dettes.md). La prudence impose de le traiter comme réel. |
| PIIBench multi-source et SPY : chiffres non revérifiés en profondeur. | À vérifier avant citation formelle. |
| IDs arXiv 2604.21211 (SPIA), 2604.15776 (PIIBench), 2505.12238 (PANORAMA), 2502.18545 (PII-Bench) | Dates 2025–2026 : **à revérifier avant citation définitive**. |

## 7. Synthèse opérationnelle

| Besoin | Datasets | Métriques |
|--------|----------|-----------|
| Développer et valider le détecteur (**axe A**) | SynthPAI · IPI (schéma) · corpus maison RH/support | Partial-match F1 par catégorie (`nervaluate`) **+ ER_di / ER_qi** |
| Calibrer le score de risque combinatoire (**axe B**) | Aucun existant → corpus maison, cadre théorique PETRE/TRIA | **k-anonymat probabiliste + TRIR** |
| Mesurer l'utilité résiduelle (**axe C**) | Documents anonymisés du projet | **Mean Utility** + performance downstream (routage) |
| Robustesse adversariale (**axe D**) | **SPIA** comme gabarit méthodologique | **CPR / IPR avec LLM local < 30 B** en continu ; attaquant agentique web ponctuellement |
| Valider le multilingue FR | ai4privacy OpenPII | F1 partial-match par langue — **axe A seulement** |
