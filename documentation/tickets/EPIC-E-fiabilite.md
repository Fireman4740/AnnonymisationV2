# ÉPIC E — Fiabilité et non-régression

**Objectif** : rendre les résultats reproductibles et empêcher les régressions
silencieuses.

**Effort** : ~2 jours · **Dépend de** : C-3, D-1.

C'est l'épic qui distingue « un pipeline qui tourne » de « un pipeline fiable ».

---

## E-1 — Non-régression déterministe de bout en bout

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | C-3 |
| **Spécs** | SPEC-04 §9, SPEC-09 §3.3 |
| **Effort** | 0,5 j |

### Contexte

Le déterminisme n'est pas une élégance : sans lui, on ne peut pas distinguer
l'effet d'un changement de code du bruit d'exécution, et aucune comparaison
entre deux politiques n'a de sens.

### Périmètre

- `tests/integration/test_determinism.py`

### Travail

Trois tests, chacun sur le micro-dataset **et** sur un corpus réel échantillonné :

1. **Ingestion** : deux `ingest` successifs → sha256 identiques sur toutes les
   tables produites.
2. **Prédiction** : deux `predict` successifs → `predictions.jsonl` identiques
   bit à bit.
3. **Scoring** : deux `score` successifs → scorecards identiques hors
   horodatage.

### Sources de non-déterminisme à débusquer

| Source | Symptôme |
|--------|----------|
| Ordre de parcours de répertoire | l'ordre des documents change entre machines |
| Itération sur un `set` | l'ordre des annotations change entre exécutions |
| `dict` non trié à la sérialisation | diff JSON non vide alors que le contenu est identique |
| Seed non fixée | échantillonnage différent |
| Horodatage dans les données | tout diffère à chaque exécution |

### Critères d'acceptation

- [ ] Les 3 tests passent.
- [ ] Un test **négatif** prouve que le contrôle fonctionne : introduire
      volontairement un `set()` non trié dans un chemin de sérialisation doit
      faire échouer le test de déterminisme.
- [ ] Les horodatages vivent dans le lock, jamais dans les enregistrements.

---

## E-2 — Tests de sanité S1 à S3

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | C-3, D-1 |
| **Spécs** | SPEC-07 §11 |
| **Effort** | 0,5 j |

### Contexte

Ces tests attrapent les erreurs d'implémentation les plus coûteuses : celles qui
produisent des chiffres plausibles mais faux. Un pipeline qui échoue S3 a un
bug, quelles que soient ses autres valeurs.

### Périmètre

- `tests/integration/test_sanity.py`

### Les trois tests

| # | Test | Attendu |
|---|------|---------|
| **S1** | Texte non anonymisé | fuite gold élevée, `UtilityRetention` = 1.0 |
| **S2** | Texte entièrement supprimé | fuite gold ≈ 0, utilité effondrée |
| **S3** | Politique plus stricte (P0 → P4) | fuite décroissante **et** utilité décroissante, de façon **monotone** |

S4 (mode `NON_STANDARD` vs `EXPLICIT`), S5 (portée auteur vs document) et S6
(entity vs span recall) arrivent avec les lots ultérieurs ; S6 est déjà
partiellement couvert par D-1.

### Critères d'acceptation

- [ ] S1, S2, S3 passent sur le micro-dataset et sur `quasifr`.
- [ ] S3 vérifie la monotonie sur les **5** politiques, pas seulement aux
      extrêmes.
- [ ] Les tests échouent avec un message qui nomme la politique fautive.

---

## E-3 — Golden test sur le micro-dataset

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | C-3 |
| **Effort** | 0,25 j |

### Contexte

Un test de référence figé, rapide, qui tourne à chaque commit et détecte tout
changement de comportement non intentionnel du pipeline complet.

### Périmètre

- `tests/fixtures/golden/predictions_micro_P2.jsonl`
- `tests/integration/test_golden.py`

### Travail

1. Exécuter le pipeline sur `tests/fixtures/micro/` en politique P2, profil
   déterministe.
2. Figer la sortie comme référence.
3. Le test rejoue et compare.
4. Fournir `--update-golden` pour régénérer **délibérément** la référence.

### Critères d'acceptation

- [ ] Le test tourne en moins de 2 secondes, sans aucune donnée externe.
- [ ] Toute modification du détecteur, de la politique ou de la transformation
      fait échouer le test avec un diff **lisible** (pas un dump de 500 lignes).
- [ ] La régénération de la référence est explicite et jamais automatique.

### Piège connu

Un golden test régénéré machinalement à chaque échec ne sert plus à rien.
La régénération doit apparaître dans le diff de commit et être justifiée.

---

## E-4 — Intégration continue à 4 étages

| | |
|---|---|
| **Priorité** | P1 |
| **Dépend de** | E-1 |
| **Spécs** | SPEC-09 §4 |
| **Effort** | 0,5 j |

### Périmètre

- `.github/workflows/ci.yml`
- `pyproject.toml` (marqueurs pytest — déjà déclarés)
- `scripts/check_no_data_committed.py`

### Les 4 étages

| Étage | Déclencheur | Contenu | Durée cible |
|-------|-------------|---------|------------:|
| CI-1 statique | chaque commit | `ruff`, `mypy --strict`, hook licences/secrets | < 1 min |
| CI-2 unitaire | chaque commit | tests sans données réelles | < 3 min |
| CI-3 intégration | PR + nocturne | `ingest --all` + `validate` sur les corpus disponibles | < 30 min |
| CI-4 évaluation | hebdomadaire | benchmark complet | heures |

**CI-1 et CI-2 ne doivent jamais dépendre de données téléchargées.** Un
développeur doit pouvoir cloner et lancer les tests immédiatement.

### Travail complémentaire — hook de conformité

`scripts/check_no_data_committed.py` refuse :
- tout fichier sous `data/` hors `.gitkeep` / `README.md` ;
- tout `.jsonl` de plus de 1 Mo ;
- tout chemin contenant `mimic`, `meddocan`, `.dcm` ;
- toute clé d'API ou fichier `.env`.

### Critères d'acceptation

- [ ] CI-1 et CI-2 passent sur un clone frais, sans `ANONV2_V1_DATASETS`.
- [ ] CI-3 saute proprement les corpus absents et les **liste** en fin de
      rapport, au lieu d'échouer.
- [ ] Le hook rejette une tentative de commit d'un fichier de `data/`
      (test dédié).
- [ ] `mypy --strict` passe sur `src/anonymisation`.

---

## E-5 — Garde « aucun accès réseau » en profil déterministe

| | |
|---|---|
| **Priorité** | P1 |
| **Dépend de** | C-3 |
| **Spécs** | SPEC-10 §10 |
| **Effort** | 0,25 j |

### Contexte

Deux risques distincts, tous deux relevés par l'audit v1 :

1. un appel réseau accidentel rend un run non reproductible ;
2. le pipeline peut **exfiltrer le texte original** vers un fournisseur externe
   — risque de confidentialité P1 de l'audit, d'autant plus grave que TAB,
   DB-bio et SupportTicketsReal contiennent des personnes réelles.

La garde répond aux deux.

### Périmètre

- `tests/integration/test_no_network.py`
- `src/anonymisation/pipeline/guards.py`

### Travail

1. Test qui neutralise `socket.socket` puis exécute `predict --profile
   deterministic` de bout en bout.
2. `guards.py` : `assert_local_only(profile, manifest)` qui lève si
   `llm.allow_remote` est vrai **et** que le manifeste porte
   `structure.synthetic: false`. C'est la garde E2 de SPEC-08, appliquée en
   code et non en documentation.

### Critères d'acceptation

- [ ] `predict --profile deterministic` réussit avec les sockets désactivés.
- [ ] `assert_local_only` lève sur TAB, DB-bio, SupportTicketsReal et CleanCoNLL
      dès que `allow_remote` est vrai.
- [ ] Elle laisse passer `personalreddit` et `ratbench` (corpus synthétiques).
- [ ] Le message d'erreur nomme le corpus et la raison.
