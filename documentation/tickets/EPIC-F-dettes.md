# ÉPIC F — Dettes à solder

**Objectif** : éliminer les incohérences connues avant de figer les
spécifications et de publier le moindre chiffre.

**Effort** : ~2 jours.

Ces tickets ne produisent pas de fonctionnalité. Ils empêchent de construire
sur du faux.

---

## F-1 — Réconcilier SPEC-10 et `configs/llm/backends.yaml`

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | — |
| **Effort** | 0,25 j |

### Contexte — dette introduite par erreur

`documentation/specifications/SPEC-10-pipeline-anonymisation.md` a été
**réécrit par-dessus une version antérieure sans que celle-ci ait été lue**.
Le contenu précédent n'est pas récupérable : fichier non suivi par git, aucune
sauvegarde.

Preuve de l'existence de la version antérieure : `configs/llm/backends.yaml`
(intact, non touché) référence « SPEC-10 §5 » pour les backends LLM et
« SPEC-10 §11 » pour les messages d'erreur actionnables et l'exécution sans
LLM. Or la version actuelle place les LLM en §6 et les critères d'acceptation
en §10. **Ces renvois sont donc cassés.**

### Périmètre

- `documentation/specifications/SPEC-10-pipeline-anonymisation.md`
- éventuellement `configs/llm/backends.yaml` (renvois uniquement)

### Travail

1. **Demander d'abord** si une copie de la version antérieure existe ailleurs.
   Si oui, fusionner plutôt que réécrire.
2. Sinon, réconcilier la numérotation dans un sens ou dans l'autre, et vérifier
   que tous les renvois de `backends.yaml` retombent juste.
3. Intégrer à SPEC-10 les éléments que `backends.yaml` documente et que la
   version actuelle ne couvre pas :
   - **backends interchangeables** avec `api_key_env` / `api_key_cmd`, la clé
     n'étant jamais écrite dans le fichier ;
   - le serveur **Qwen3.8-27B local en vLLM** (`F:\IA\Qwen3.8\qwen.ps1`, port
     18020) comme backend par défaut — cohérent avec la contrainte « modèles
     locaux < 30 B » ;
   - le **backend `null`** permettant d'exécuter le pipeline sans GPU ;
   - le **cache LLM obligatoire**, clé = `sha256(backend + model + prompt +
     params)` — sans lui, chaque réévaluation recoûte des heures de GPU et les
     comparaisons entre politiques ne sont plus isolées du bruit du modèle ;
   - l'affectation **par rôle** (détection, génération, attaquant A, attaquant
     B, paraphrase) ;
   - le rappel que le **backend utilisé doit figurer dans tout rapport** : un
     résultat obtenu avec Sonnet n'est pas comparable à un résultat Qwen.

### Critères d'acceptation

- [ ] Tous les renvois de `backends.yaml` pointent vers des sections existantes.
- [ ] Le contenu de `backends.yaml` est couvert par une section de SPEC-10.
- [ ] Le journal des modifications de SPEC-10 mentionne explicitement
      l'écrasement et sa réparation.

### Leçon de processus

Ne jamais écrire par-dessus un fichier sans l'avoir lu, y compris quand un
listage de répertoire le donne pour absent.

---

## F-2 — Table de réconciliation SPEC-01 §9

| | |
|---|---|
| **Priorité** | P1 |
| **Dépend de** | — |
| **Effort** | 0,5 j |

### Contexte

SPEC-01 §9 contient une table de réconciliation **vide** entre les 9 catégories
d'identifiants indirects d'IPI et le bloc générique de 13 codes du projet.

Tant qu'elle est vide, le bloc `GEN_*` est une proposition motivée, **pas un
alignement vérifié** — et SPEC-01 ne peut pas passer au statut `Gelé`.

Bonne nouvelle : ce ticket **ne dépend plus de PhysioNet**. Les guidelines
d'IPI se lisent dans la publication, sans aucun accès aux données.

### Périmètre

- `documentation/specifications/SPEC-01-taxonomie-qi.md` §9
- `documentation/datasets/ipi-mimic.md` (statut de la fiche)

### Critères d'acceptation

- [ ] Les 9 catégories IPI sont listées avec leur définition.
- [ ] Chacune est associée à un ou plusieurs codes `GEN_*`, ou déclarée sans
      équivalent (avec justification).
- [ ] Les écarts sont explicités : ce que le projet ajoute, ce qu'il omet.
- [ ] SPEC-01 peut passer en `Gelé` à l'issue du ticket.

---

## F-3 — Mesurer le taux d'`OTHER_QI` réel

| | |
|---|---|
| **Priorité** | P1 |
| **Dépend de** | B-3 |
| **Effort** | 0,5 j |

### Contexte

SPEC-01 §4.6 pose une règle : un taux d'`OTHER_QI` supérieur à **1 %** signale
une taxonomie incomplète, et `E-VAL-110` l'implémente déjà.

Mais tant qu'aucun corpus réel n'est ingéré, cette règle n'a jamais été
éprouvée. TAB et `quasifr` sont les premiers corpus capables de la mettre en
défaut : ils contiennent des QI juridiques et français que le bloc `GEN_*` n'a
peut-être pas prévus.

### Périmètre

- rapport d'analyse dans `documentation/annexes/couverture-taxonomie.md`
- corrections éventuelles de `configs/detection/patterns.yaml`
- corrections éventuelles de SPEC-01 §4

### Travail

1. Ingérer TAB, `quasifr` et `personalreddit`.
2. Relever `by_qi_category` dans chaque `.validation.json`.
3. Pour chaque code jamais instancié : est-il inutile, ou simplement absent de
   ces corpus ?
4. Pour chaque `OTHER_QI` : quel code manque ?

### Critères d'acceptation

- [ ] Le taux d'`OTHER_QI` est mesuré et publié par corpus.
- [ ] Si le taux dépasse 1 %, soit des codes sont ajoutés (via la procédure
      SPEC-01 §10, y compris la source de population), soit le dépassement est
      justifié par écrit.
- [ ] Les codes jamais instanciés sont listés avec un verdict.

### Piège connu

La procédure d'ajout de code de SPEC-01 §10 impose de fournir **la source de
population permettant d'estimer la fréquence de l'attribut**. C'est la barrière
qui empêche la taxonomie de gonfler indéfiniment : un QI dont on ne sait pas
estimer la fréquence est inutilisable par le moteur de risque. Ne pas la
contourner.

---

## F-4 — Solder les « à confirmer » des fiches

| | |
|---|---|
| **Priorité** | P2 |
| **Dépend de** | B-* |
| **Effort** | 0,25 j |

### Contexte

Une passe de correction des fiches a été interrompue par le plafond de session.
Les faits ci-dessous sont **déjà vérifiés sur disque** mais pas encore reportés
dans toutes les fiches.

### Faits vérifiés à reporter

| Fiche | Fait établi |
|-------|-------------|
| `personalreddit.md` | **Synthétique** (`eth-sri/llmprivacy`, via RUPTA) → `synthetic: true`, garde E2 **non applicable**. 318 train / 207 test. |
| `quasifr.md` | 40 + 31 + 1 = **72 exemples**, 427 annotations et six offsets ré-ancrés. Trop peu pour une mesure statistiquement solide. |
| `dbbio.md` | **1 938 train / 243 val / 239 test**, soit 2 420 lignes canoniques. `l1/l2/l3` = ontologie **DBpedia** (`Agent` > `Artist` > `Photographer`), pas ESCO/ISCO. `people` est une **chaîne**, pas des offsets. |

### Restent légitimement ouverts

Licence exacte de SupportTicketsReal · recouvrement des 3 fichiers `quasifr` ·
granularité du document CoNLL (phrase vs dépêche) · rôle des variantes
`train_sft.jsonl` / `train_dpo.jsonl` de DB-bio.

### Critères d'acceptation

- [x] Les faits vérifiés figurent dans les fiches, sans confusion avec les points ouverts.
- [x] Les points réellement ouverts le restent, marqués comme tels.
- [x] Les manifestes correspondants portent les bonnes volumétries dans
      `integrity.expected_documents` (`personalreddit`: 525, `quasifr`: 72,
      `dbbio`: 2 420).

---

## F-5 — Retirer `NaiveRiskEstimator` des chemins publiés

| | |
|---|---|
| **Priorité** | P1 |
| **Dépend de** | D-2 |
| **Effort** | 0,25 j |

### Contexte

`NaiveRiskEstimator` est un estimateur **provisoire et non calibré**. Sa formule
a déjà dû être corrigée une fois : elle retournait `Π(prévalences)`, si bien
qu'un attribut rare produisait un risque **faible** et que généraliser
**augmentait** le risque. Elle est désormais `k = N·Π(p)`, `R = 1/k`, avec les
deux monotonies vérifiées par test.

Il reste que :

- l'hypothèse d'indépendance des attributs est **fausse** (profession et
  diplôme, ville et région sont corrélés) et **sous-estime le risque** ;
- la taille de population `N = 10 000` est une valeur arbitraire de repli ;
- rien n'empêche aujourd'hui ses sorties d'apparaître dans un rapport.

### Périmètre

- `src/anonymisation/policy/engine.py`
- `src/anonymisation/metrics/scorecard.py`

### Travail

1. Toute sortie de `NaiveRiskEstimator` porte `MetricStatus.PROXY`, de façon
   **inamovible** (pas un paramètre surchargeable).
2. `validate_scorecard()` refuse une scorecard dont le bloc `primary` contient
   une métrique de risque `PROXY`.
3. Émettre un avertissement au chargement du profil quand
   `assess.estimator == "naive"`.

### Critères d'acceptation

- [ ] Impossible de produire une scorecard `OFFICIAL` avec l'estimateur naïf.
- [ ] Un test tente de forcer le statut à `OFFICIAL` et échoue.
- [ ] L'avertissement apparaît une fois par run, pas à chaque document.

### À retirer quand

Le ticket est clos par la livraison du moteur de risque de SPEC-06 (lot L4), qui
remplace l'estimateur par un calcul sur population réelle — PUMS étant déjà
disponible (ticket B-5).
