# IPI — Indirect Personal Identifiers (sur MIMIC-III)

| | |
|---|---|
| **Statut de la fiche** | Archivée · v1.2 · 2026-09-04 |
| **Priorité** | **NON RETENU** (décision 2026-08-30) — partie *spécification* terminée le 2026-09-04 (ticket F-2) |
| **Benchmark** | — |

---

> ## ⚠️ Décision : ce dataset n'est pas retenu
>
> L'accès aux **données** IPI passe par MIMIC-III (PhysioNet : compte + formation
> CITI + DUA signé, plusieurs semaines de délai administratif), et sa
> redistribution est interdite — donc aucun résultat ne serait reproductible par
> un tiers.
>
> **Remplacements** (voir [`inventaire-local.md §4`](inventaire-local.md)) :
>
> | Apport d'IPI | Remplacé par |
> |---|---|
> | Taxonomie des identifiants indirects | Les **guidelines** de la publication, lisibles sans aucun accès aux données. SPEC-01 s'en inspire déjà. |
> | Annotation QI sur texte réel | **TAB officiel**, plus riche et disponible localement |
> | Stress-test clinique cross-domaine | **MEDDOCAN** (licence ouverte, sans démarche) |
> | QI indirects annotés | **Corpus QI français** (`data/hard_quasi_id_dataset.json`) |
>
> Aucune capacité du projet n'est perdue. Le reste de la fiche est conservé
> **pour la taxonomie uniquement** : la section §10 (extension aux domaines RH et
> support) reste la source du bloc `HR_*` / `SUP_*` de SPEC-01.

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom | Indirect Personal Identifiers — schéma d'annotation et corpus |
| Référence | [@baroud2025ipi] |
| Année | 2025 |
| Type | Texte réel (notes cliniques), annoté manuellement |
| Langue | Anglais |
| Domaine | Clinique — *discharge summaries* MIMIC-III |

## 2. Rôle et priorité

**C'est la source principale de la taxonomie des QI du projet.**

Le travail ne se limite pas aux PII classiques : les auteurs proposent un schéma
de **neuf catégories d'identifiants indirects**, construit **en tenant compte de
différents adversaires potentiels** (connaissances, famille, personnel médical).
Priorité double :

- **P0 pour la spécification** : ✅ fait (2026-09-04, ticket F-2) — les 9
  catégories figurent dans SPEC-01 §9 avec définitions, exemples et mapping ;
  SPEC-01 est Gelé v1.1.
- **P2 pour les données** : les spans nécessitent un accès MIMIC-III, long à
  obtenir et non redistribuable.

## 3. Contenu et volumétrie

| | |
|---|---|
| Documents annotés | **100 discharge summaries** MIMIC-III |
| Annotations | **6 199** |
| Catégories | **9 catégories d'identifiants indirects** |
| Distribution | Guidelines + spans, référencés aux documents MIMIC-III correspondants |

Les auteurs ne redistribuent pas les textes : ils publient les **guidelines** et
les **spans** (offsets), rattachables aux documents MIMIC-III que l'utilisateur
doit se procurer lui-même.

## 4. Structure brute

- **Guidelines d'annotation** : document décrivant les 9 catégories, leurs
  frontières et les cas limites. C'est la pièce la plus précieuse.
- **Fichier de spans** : `(document_id MIMIC, start, end, catégorie)` — format
  exact à confirmer.

## 5. Accès et acquisition

### Guidelines (immédiat)

| | |
|---|---|
| Source | Publication + matériel supplémentaire ACL Anthology |
| Prérequis | Aucun |
| Action | Lire, extraire les 9 catégories, les transposer dans [SPEC-01](../specifications/SPEC-01-taxonomie-qi.md) |

### Données (long)

| | |
|---|---|
| Source | PhysioNet — MIMIC-III |
| Prérequis | Compte PhysioNet **+ formation CITI « Data or Specimens Only Research » + accord d'utilisation (DUA) signé** |
| Délai typique | Plusieurs semaines |
| Cache local | `data/raw/ipi/` (spans) et `data/external/mimic3/` (textes, **jamais versionné**) |

> **Action recommandée** : lancer la demande d'accès PhysioNet **maintenant**,
> en parallèle du reste du travail, car c'est le seul élément de la batterie dont
> le délai est administratif et non technique.

## 6. Licence et conformité

| | |
|---|---|
| Guidelines | Licence de la publication (réutilisation du schéma : citer [@baroud2025ipi]) |
| Spans | Licence des auteurs, à confirmer |
| Textes MIMIC-III | **Restrictif — PhysioNet Credentialed Health Data License** |
| Redistribution des textes | **INTERDITE** |
| Versionnement dans ce dépôt | **INTERDIT** — voir `.gitignore` (`**/mimic*/`) |

**Règle dure** : aucun test du dépôt ne doit exiger MIMIC-III pour passer. Les
tests concernés portent le marqueur pytest `restricted_license` et sont skippés
par défaut. Voir [SPEC-09](../specifications/SPEC-09-qualite-licences-ci.md).

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs | ✅ |
| **QI indirects, taxonomie explicite** | ✅ **(l'apport principal)** |
| QI implicites | ◐ |
| Combinaisons annotées | ◐ |
| Modèle d'adversaire explicite | ✅ |
| Population de référence | ❌ |
| Multilingue | ❌ (anglais) |
| Domaine RH/support/forum | ❌ |
| Texte réel | ✅ |

## 8. Apport pour le projet

1. **La taxonomie.** Partir de **TAB + IPI + attributs de domaine** plutôt que
   d'inventer un schéma. C'est l'économie méthodologique la plus rentable du
   projet, et elle rend la taxonomie défendable en publication.
2. **La logique multi-adversaires** : les catégories IPI sont définies par
   rapport à ce qu'un adversaire donné peut exploiter, ce qui se transpose
   directement dans les niveaux A/B/C de SPEC-08.
3. **Un point d'ancrage clinique** pour vérifier que la taxonomie n'est pas
   sur-ajustée au domaine RH.

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| 100 documents seulement | Trop petit pour entraîner ; utile pour évaluer et calibrer la taxonomie. |
| Accès MIMIC bloquant | Prévoir un chemin de repli : la taxonomie sans les données. |
| Domaine clinique | Les 9 catégories doivent être **étendues**, pas copiées : elles ne couvrent ni le produit/version support, ni l'ancienneté/hiérarchie RH. |
| Anglais | Adaptation FR à valider. |

## 10. Extension aux domaines du projet

Les 9 catégories IPI servent de socle. Le projet ajoute deux blocs de domaine
(détail : [SPEC-01](../specifications/SPEC-01-taxonomie-qi.md)) :

### Bloc RH

tranche d'âge · ancienneté · diplôme · fonction · niveau hiérarchique ·
département · localisation · historique professionnel · type de contrat ·
combinaison employeur × rôle × localisation · événements professionnels rares.

### Bloc support

produit · version · OS · type de terminal · localisation · fuseau horaire ·
horaire d'incident · rôle utilisateur · environnement technique · combinaison
produit × version × organisation × heure.

Ces combinaisons doivent être traitées comme des **objets de risque uniques**,
et non comme des entités indépendantes — c'est la justification de la métrique
QICR.

## 11. Mapping vers le schéma interne

| Catégorie IPI | Mappage dans SPEC-01 (v1.1 §9) |
|---------------|----------------------------------|
| appearance | `GEN_PHYSICAL` |
| circumstances | **aucun code** — événement/comportement, non attribut ; seul le daté → `GEN_DATE_EVENT` (écart réel documenté) |
| sec | `GEN_OCCUPATION` + `GEN_SOCIOECON` ; antécédent judiciaire → axe `sensitivity = JUDICIAL` |
| family | `GEN_FAMILY` ; historique médical familial → `GEN_HEALTH_STATE` avec `subject = THIRD_PARTY` |
| fclt_personnel | `GEN_AFFILIATION` ; médecin externe nommé → `DIR_NAME` |
| time | `GEN_AGE` ; daté → `GEN_DATE_EVENT` ; temps clinique = limite documentée |
| lfstl | `GEN_LIFESTYLE` |
| details | **pas un code** : l'axe `expression_mode` (`IMPLICIT`/`NON_STANDARD`) appliqué au code du PII sous-jacent |
| other | `GEN_ORIGIN_BELIEF` ; orientation sexuelle → axe `sensitivity = SEXLIFE` |

## 12. Splits et protocole

- 100 documents → **aucun split d'entraînement**. Corpus d'évaluation
  exclusivement.
- Protocole : `diagnostic` par défaut ; `official` impossible tant que la
  redistribution est interdite (résultats non reproductibles par un tiers sans
  accès MIMIC).

## 13. Plan d'implémentation

| # | Étape | Dépend de MIMIC ? | Sortie |
|---|-------|:-----------------:|--------|
| 1 | Lire les guidelines, extraire les 9 catégories | Non | tableau dans SPEC-01 |
| 2 | Définir le mapping IPI → SPEC-01 | Non | `configs/datasets/ipi.yaml` |
| 3 | Lancer la demande PhysioNet + CITI | Non | accès en cours |
| 4 | Écrire l'adaptateur avec chargement du texte externe | Non (code) | `src/anonymisation/datasets/ipi.py` |
| 5 | Test unitaire sur un texte factice + spans factices | Non | test toujours vert |
| 6 | Ingestion réelle | **Oui** | `data/processed/ipi/` |

**L'étape 1 est la seule vraiment bloquante pour le reste du projet** : la
taxonomie conditionne SPEC-01, donc SPEC-02, donc tous les adaptateurs.

## 14. Critères d'acceptation

- [x] Les 9 catégories IPI figurent dans SPEC-01 avec leur définition et un
      exemple. — ✅ 2026-09-04 (ticket F-2) : SPEC-01 v1.1 §9 (définitions
      verbatim de l'appendix A + comptes de la table 1).
- [x] Le mapping IPI → SPEC-01 est total (aucune catégorie orpheline). — ✅
      2026-09-04 (ticket F-2) : 7 catégories mappées sur un code `GEN_*`
      (parfois complété par un axe), `details` absorbée par l'axe
      `expression_mode`, `circumstances` documentée comme écart réel
      (événement/comportement, sans code d'attribut) — SPEC-01 §9.
- [ ] L'adaptateur fonctionne sur un jeu factice sans MIMIC-III.
- [ ] Les tests réels portent `@pytest.mark.restricted_license` et sont skippés
      sans données.
- [ ] Aucun fichier MIMIC n'apparaît dans `git status`.

## 15. Questions ouvertes

- Les spans sont-ils publiés séparément et sous quelle licence ?
- Les 9 catégories sont-elles disjointes, ou un span peut-il en porter
  plusieurs ? — **Répondu par la publication** (2026-09-04) : un span porte
  **une** catégorie — les comptes de la table 1 (132+99+59+273+1421+4006+144+32+33)
  somment exactement aux 6 199 annotations, et l'annotation Prodigy est en
  B/I/O word-level (une étiquette par mot). L'adaptateur (lorsque l'accès
  MIMIC-III sera obtenu) émettra des listes `qi_categories` à un seul élément ;
  le modèle de données de SPEC-02 reste multi-label (généralisation stricte).
- La demande PhysioNet est-elle réellement nécessaire au projet, ou la taxonomie
  suffit-elle ? → décision à prendre en fin de lot L1.
