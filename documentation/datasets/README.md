# Jeux de données — index, priorisation, couverture et licences

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date** | 2026-08-30 |

Principe directeur : **une batterie de benchmarks complémentaires, pas un
dataset unique**. Aucun corpus existant ne couvre simultanément QI indirects,
combinaisons, domaines RH/support/forums, français, et population de référence
européenne.

---

## 0. Lire d'abord : l'inventaire local

**[`inventaire-local.md`](inventaire-local.md)** — le dépôt v1 contient déjà tous
les corpus nécessaires, y compris **TAB officiel avec son script d'évaluation**
et la **population de référence PUMS (3,37 M individus)**. Aucun téléchargement
n'est requis pour démarrer, et **l'accès PhysioNet est abandonné**.

Cette page conserve les fiches détaillées ; la priorisation effective est celle
de [`inventaire-local.md §7`](inventaire-local.md).

## 1. Index des fiches

### Corpus disponibles localement (aucun téléchargement)

| Dataset | Fiche | Rôle | Priorité |
|---------|-------|------|---------:|
| TAB (officiel) | [`tab.md`](tab.md) | Annotation QI + métriques privacy-oriented | **P0** |
| RAT-Bench + PUMS | [`rat-bench.md`](rat-bench.md) | Risque + ré-identification, **seule source de `k` réel** | **P0** |
| SupportTicketsReal | [`supporttickets.md`](supporttickets.md) | Domaine support réel + tâche de routage | **P0** |
| Corpus QI français | [`quasifr.md`](quasifr.md) | **Seule source de QI annotés en français** | **P0** |
| PersonalReddit | [`personalreddit.md`](personalreddit.md) | Forums + inférence d'attributs + difficulté | **P0** |
| DB-bio | [`dbbio.md`](dbbio.md) | Utilité aval (classification d'occupation) | P1 |
| CleanCoNLL / CoNLL-2003 | [`conll2003.md`](conll2003.md) | Contrôle NER | P1 |
| BitextSupportSynthetic | [`supporttickets.md`](supporttickets.md) | Tâche d'utilité « intention » | P1 |

### Corpus à générer (la contribution du projet)

| Dataset | Fiche | Rôle | Priorité |
|---------|-------|------|---------:|
| HR-QI-Bench | [`hr-qi-bench.md`](hr-qi-bench.md) | Corpus RH à construire | **P0** |
| Support-QI-Bench | [`support-qi-bench.md`](support-qi-bench.md) | Corpus support à construire | **P0** |
| Forum-QI-Bench | [`forum-qi-bench.md`](forum-qi-bench.md) | Corpus forums FR à construire | **P0** |

### Corpus nécessitant un téléchargement

| Dataset | Fiche | Rôle | Priorité |
|---------|-------|------|---------:|
| OpenPII 500k | [`openpii-500k.md`](openpii-500k.md) | PII multilingue (dont FR), F1 par langue | **P0** |
| MultiCoNER II | [`multiconer2.md`](multiconer2.md) | Robustesse multilingue / bruit | P1 |
| MEDDOCAN | [`meddocan.md`](meddocan.md) | Stress-test cross-domaine (ES) | P2 |
| SynthPAI | [`synthpai.md`](synthpai.md) | Forums — **redondant avec PersonalReddit** à court terme | P2 |
| JobStack | [`jobstack.md`](jobstack.md) | PII explicite RH — accès sur demande | P2 |

### Non retenu

| Dataset | Fiche | Motif |
|---------|-------|-------|
| IPI / MIMIC-III | [`ipi-mimic.md`](ipi-mimic.md) | ❌ Accès PhysioNet abandonné — voir [`inventaire-local.md §4`](inventaire-local.md) |

Sens des priorités :

- **P0** — bloquant. Sans lui, une des quatre questions de recherche n'est pas
  mesurable.
- **P1** — utile, à intégrer après les P0. Diagnostic ou robustesse.
- **P2** — optionnel. Un seul usage : test de généralisation.

---

## 2. Matrice de couverture

Légende : ✅ couvert · ◐ partiel · ❌ absent.

| | RAT-Bench | TAB | IPI | SynthPAI | OpenPII | JobStack | MultiCoNER | MEDDOCAN | HR-QI | Sup-QI | Forum-QI |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Identifiants directs | ✅ | ✅ | ✅ | ◐ | ✅ | ✅ | ◐ | ✅ | ✅ | ✅ | ✅ |
| QI indirects | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ | ◐ | ✅ | ✅ | ✅ |
| QI implicites | ✅ | ◐ | ◐ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Combinaisons annotées | ✅ | ◐ | ◐ | ◐ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Profil latent par personne | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Population de référence | ✅ (US) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (FR) | ✅ | ✅ (FR) |
| Attaquant intégré | ✅ | ❌ | ❌ | ◐ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |
| Multilingue | ✅ | ❌ (EN) | ❌ (EN) | ❌ (EN) | ✅ | ❌ (EN) | ✅ | ❌ (ES) | ✅ | ✅ | ◐ |
| Français | ◐ | ❌ | ❌ | ❌ | ✅ | ❌ | ✅ | ❌ | ✅ | ✅ | ✅ |
| Domaine RH | ◐ | ❌ | ❌ | ◐ | ❌ | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Domaine support | ◐ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Domaine forums | ◐ | ❌ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Texte réel (non synthétique) | ❌ | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ◐ | ◐ | ◐ |
| Métrique d'utilité en aval | ❌ | ◐ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ |

**Lecture** : les colonnes des trois derniers corpus (à construire) sont les
seules à être vertes partout. C'est exactement la justification de
[SPEC-05](../specifications/SPEC-05-generation-corpus-synthetiques.md).

---

## 3. Affectation aux quatre benchmarks

| Benchmark | Question de recherche | Datasets |
|-----------|----------------------|----------|
| **B1 — PII Detection** | Détecte-t-on les identifiants explicites ? | OpenPII, JobStack, MultiCoNER II, (MEDDOCAN) |
| **B2 — Indirect QI Detection** | Détecte-t-on les QI et leurs combinaisons ? | TAB, IPI, SynthPAI, HR-QI, Support-QI |
| **B3 — Risk Estimation** | Le score de risque est-il exact et calibré ? | RAT-Bench, corpus population-based interne |
| **B4 — End-to-End** | Le texte résiste-t-il et reste-t-il utile ? | Toute la batterie |

---

## 4. Licences et contraintes de diffusion

⚠️ **Aucune donnée sous licence restrictive ne doit être versionnée dans ce
dépôt.** Voir [`.gitignore`](../../.gitignore) et
[SPEC-09](../specifications/SPEC-09-qualite-licences-ci.md).

| Dataset | Licence / régime d'accès | Redistribution | Contrainte opérationnelle |
|---------|--------------------------|----------------|---------------------------|
| RAT-Bench | À confirmer à l'acquisition (probable licence ouverte type MIT/CC-BY) | À confirmer | Vérifier avant tout usage publié |
| TAB | Licence ouverte recherche (corpus CEDH, jugements publics) | Autorisée sous conditions | Citer [@pilan2022tab] |
| IPI / MIMIC-III | **Restrictive** — MIMIC-III exige PhysioNet + formation CITI + DUA signé | **Interdite** | Seules les *guidelines* et le schéma sont réutilisables sans accès. Les spans nécessitent MIMIC-III. |
| SynthPAI | Licence ouverte (HF / GitHub eth-sri) | Autorisée | Données synthétiques, pas de contrainte RGPD |
| OpenPII 500k | Licence ouverte AI4Privacy (vérifier la version exacte) | Autorisée | Données synthétiques |
| JobStack | Accès sur demande auprès des auteurs | Restreinte | Prévoir un délai |
| MultiCoNER II | Licence ouverte (SemEval) | Autorisée | — |
| MEDDOCAN | Licence ouverte Zenodo (CC) | Autorisée | Corpus clinique synthétique/anonymisé, mais vérifier |
| HR/Support/Forum-QI | **Propriété du projet** | Décision à prendre (publication envisagée) | Si dérivé de données réelles : RGPD, base légale, DPIA |

**Règle de conformité n°1** : tout adaptateur doit déclarer sa licence dans son
manifeste (`configs/datasets/<nom>.yaml`, champ `license`) et le registre refuse
de charger un dataset dont la licence n'est pas déclarée. Voir
[SPEC-03 §5](../specifications/SPEC-03-registre-et-adaptateurs.md).

**Règle de conformité n°2** : si un corpus interne est dérivé de données
personnelles réelles (tickets, messages RH), il relève du RGPD. Base légale,
minimisation, durée de conservation et DPIA doivent être documentés dans la
fiche du corpus avant toute ingestion.

---

## 5. Volumétrie et coût d'ingestion (estimations)

| Dataset | Documents | Taille disque estimée | Effort d'adaptateur |
|---------|----------:|----------------------:|--------------------|
| RAT-Bench | à confirmer | à confirmer | **Élevé** (profils + population + attaquant) |
| TAB | 1 268 affaires | ~50–150 Mo | Moyen (coréférences, annotateurs multiples) |
| IPI | 100 documents / 6 199 annotations | < 10 Mo (hors MIMIC) | Moyen + blocage d'accès |
| SynthPAI | 7 823 commentaires / 300 profils | < 50 Mo | Faible |
| OpenPII 500k | ~500 000 exemples | ~1–3 Go | Faible |
| JobStack | à confirmer | à confirmer | Faible |
| MultiCoNER II | ~2 M tokens × 12 langues | ~1 Go | Faible |
| MEDDOCAN | ~1 000 cas cliniques | < 100 Mo | Faible (format BRAT) |
| HR-QI-Bench | cible 3 000 docs / 600 profils | < 100 Mo | **Élevé** (génération) |
| Support-QI-Bench | cible 3 000 tickets / 600 profils | < 100 Mo | **Élevé** |
| Forum-QI-Bench | cible 5 000 messages / 500 profils | < 100 Mo | **Élevé** |

*Les valeurs « à confirmer » doivent être renseignées lors de l'acquisition et
figées dans le manifeste (`expected_documents`, `sha256`).*

---

## 6. Ordre d'implémentation recommandé

Révisé après l'inventaire local — chaque étape introduit **une** difficulté
nouvelle, ce qui évite d'affronter simultanément le format, la taxonomie, la
coréférence et le risque :

1. **Corpus QI français** (`quasifr`) — le plus petit et le plus simple ; valide
   la chaîne d'ingestion complète, et c'est du français annoté en QI.
2. **PersonalReddit** — introduit le profil latent et l'axe de difficulté ; ses
   fichiers source train/test nécessitent une reconstruction du split par auteur.
3. **TAB officiel** — introduit la coréférence, le multi-annotateurs et les
   métriques entity-level.
4. **SupportTicketsReal** — introduit le domaine support, le multilinguisme et
   la tâche d'utilité (routage).
5. **RAT-Bench + PUMS** — introduit la population de référence et le `k` réel.
6. **DB-bio**, **CleanCoNLL**, **BitextSupportSynthetic**.
7. **HR-QI-Bench**, **Support-QI-Bench**, **Forum-QI-Bench** (génération).
8. Différés : OpenPII, MultiCoNER II, MEDDOCAN.

---

## 7. Format des fiches

Chaque fiche suit la même structure en 14 sections :

1. Identité · 2. Rôle et priorité · 3. Contenu et volumétrie ·
4. Structure brute · 5. Accès et acquisition · 6. Licence et conformité ·
7. Couverture · 8. Apport pour le projet · 9. Limites et pièges ·
10. Mapping vers le schéma interne · 11. Splits et protocole ·
12. Plan d'implémentation de l'adaptateur · 13. Critères d'acceptation ·
14. Questions ouvertes.

Toute nouvelle fiche doit respecter ce gabarit.
