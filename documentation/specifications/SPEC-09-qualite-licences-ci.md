# SPEC-09 — Qualité des données, licences et intégration continue

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date** | 2026-08-30 |
| **Dépend de** | toutes |

---

## 1. Objet

Les contrôles automatiques qui empêchent trois catégories d'accidents :

1. publier un résultat faux (qualité) ;
2. diffuser une donnée qu'on n'a pas le droit de diffuser (licence, RGPD) ;
3. casser silencieusement une brique existante (CI).

## 2. Conformité des licences

### 2.1 Règles dures

| # | Règle |
|---|-------|
| **L1** | Aucune donnée de dataset NE DOIT être versionnée dans Git. La traçabilité passe par manifestes et checksums. |
| **L2** | Tout dataset DOIT déclarer `license.spdx`. La valeur `UNKNOWN` interdit le statut `OFFICIAL`. |
| **L3** | Un dataset `license.restricted: true` (MIMIC-III, JobStack) NE DOIT être requis par aucun test de la CI. |
| **L4** | Aucune sortie d'attaquant portant sur des personnes réelles NE DOIT être journalisée ni versionnée (SPEC-08 E3/E4). |
| **L5** | Un corpus interne dérivé de données personnelles réelles NE DOIT PAS être ingéré avant que sa fiche ne documente base légale, finalité, minimisation, durée de conservation et DPIA. |

### 2.2 Contrôles automatiques

| Contrôle | Mise en œuvre |
|----------|---------------|
| Pas de données versionnées | Hook pre-commit : refus de tout fichier sous `data/` hors `.gitkeep`/`README.md` ; refus de tout `.jsonl` > 1 Mo |
| Motifs interdits | Refus des chemins contenant `mimic`, `meddocan`, `.dcm` |
| Licence déclarée | `anonv2 datasets audit-licenses` — échoue si un manifeste est incomplet |
| Secrets | Scan de `.env`, clés API, tokens |

### 2.3 Tableau de conformité

Généré par `anonv2 datasets audit-licenses`, publié dans
[`documentation/datasets/README.md §4`](../datasets/README.md) et vérifié en CI :

```
DATASET       LICENCE            REDISTRIB  RESTREINT  OFFICIAL-ELIGIBLE
openpii       <spdx>             oui        non        oui
synthpai      <spdx>             oui        non        oui
tab           <spdx>             oui        non        oui
ratbench      UNKNOWN            ?          non        NON  ← bloquant
ipi           PhysioNet-CHD      non        OUI        non
jobstack      on-request         non        OUI        non
meddocan      CC-BY-4.0          oui        non        oui
multiconer2   <spdx>             oui        non        oui
hr_qi         projet             à décider  non        oui
```

## 3. Qualité des données

### 3.1 Contrôles par dataset

Rappel des invariants bloquants (SPEC-04 §5) : offsets valides (`E-VAL-101`),
mapping total (`E-MAP-001`), absence de fuite de split (`E-VAL-108`),
volumétrie conforme (`E-VAL-109`), cohérence risque/$k$ (`E-VAL-106`).

### 3.2 Contrôles transverses

| Contrôle | Seuil |
|----------|-------|
| Taux d'`OTHER_QI` | < 1 % par dataset — au-delà, la taxonomie est incomplète |
| Taux de `value_normalized` manquant | < 5 % sur les attributs participant à $k$ |
| Couverture des catégories SPEC-01 | Chaque code DEVRAIT apparaître dans ≥ 1 dataset ; un code jamais instancié est suspect |
| Doublons de texte | < 1 % de documents strictement identiques |
| Déséquilibre de langue | Signalé, non bloquant, mais interdit toute moyenne toutes langues confondues |

### 3.3 Contrôle de non-régression du corpus

Une réingestion complète DOIT produire des fichiers **identiques bit à bit**
(SPEC-04 §11). Le test compare les sha256 des tables produites à ceux du
`.manifest.lock.json`.

C'est le test qui attrape les non-déterminismes cachés : ordre de dictionnaire,
parcours de répertoire, seed non fixée, tri instable.

## 4. Intégration continue

### 4.1 Étages

| Étage | Déclencheur | Contenu | Durée cible |
|-------|-------------|---------|------------:|
| **CI-1 — statique** | chaque commit | `ruff`, `mypy --strict`, hook licences/secrets | < 1 min |
| **CI-2 — unitaire** | chaque commit | tests sans données réelles (fixtures synthétiques) | < 3 min |
| **CI-3 — intégration** | PR + nocturne | `datasets ingest --all --skip-missing` + `validate` sur les datasets disponibles | < 30 min |
| **CI-4 — évaluation** | hebdomadaire / manuel | benchmark complet, attaquants A et B | heures |

CI-1 et CI-2 **ne DOIVENT jamais** dépendre de données téléchargées. Un
développeur doit pouvoir cloner et lancer les tests immédiatement.

### 4.2 Marqueurs pytest

```python
@pytest.mark.requires_data       # nécessite un dataset téléchargé
@pytest.mark.restricted_license  # nécessite MIMIC-III / JobStack — skip par défaut
@pytest.mark.slow                # LLM, attaquant
```

```bash
pytest                                  # CI-1/CI-2 : rapide, aucune donnée
pytest -m "requires_data"               # CI-3
pytest -m "slow"                        # CI-4
```

### 4.3 Fixtures synthétiques

`tests/fixtures/` contient un **micro-dataset complet** (5 documents,
12 annotations, 3 profils, 4 combinaisons, 1 population de 100 individus)
conforme à SPEC-02.

Il permet de tester sans aucun téléchargement : validation, calcul de $k$,
métriques, politique, et même un attaquant simulé. C'est l'investissement le
plus rentable de la suite de tests — il transforme la majorité des tests
d'intégration en tests unitaires rapides.

## 5. Reproductibilité des expériences

| Élément | Où il est figé |
|---------|----------------|
| Version des données | `.manifest.lock.json` (sha256, révision source) |
| Version de la taxonomie | `taxonomy_version` dans le lock |
| Version du code | commit Git dans le rapport de run |
| Modèles et quantisations | rapport de run |
| Seeds | rapport de run |
| Prompts d'attaque | `configs/attack/prompts/`, versionnés |
| Politique | `configs/policy/<id>.yaml` |

Un rapport de run sans ces sept éléments N'EST PAS publiable.

## 6. Revue avant publication

Liste de contrôle à passer avant toute soumission :

- [ ] Toutes les références `[à revérifier]` de
      [`references.bib`](../rapport/references.bib) ont été reconfirmées à la
      source.
- [ ] Les licences de tous les datasets utilisés sont déclarées et compatibles
      avec la publication des résultats.
- [ ] Aucun exemple qualitatif ne porte sur une personne réelle.
- [ ] Les métriques `DIAGNOSTIC` et `PROXY` ne sont pas présentées comme
      comparables à la littérature.
- [ ] Les résultats sur corpus stratifié sont publiés bruts **et** repondérés
      (SPEC-05 §4).
- [ ] Le protocole d'attaque est décrit assez précisément pour être reproduit.
- [ ] Les limites du §10 de [SPEC-06](SPEC-06-population-et-risque.md)
      (stylométrie, graphe social, connaissance externe) sont déclarées.
- [ ] La contribution est formulée selon
      [03-lacunes §3.2](../rapport/03-lacunes-et-contribution.md), et **pas**
      comme « premier système à… ».

Le dernier point mérite d'être vérifié explicitement : c'est l'erreur de
positionnement la plus facile à commettre et la plus coûteuse en review, depuis
la publication de RAT-Bench.

## 7. Journal des modifications

| Version | Date | Changement |
|---------|------|-----------|
| 1.0 | 2026-08-30 | Création. Règles L1–L5, contrôles qualité, 4 étages de CI, liste de revue avant publication. |
