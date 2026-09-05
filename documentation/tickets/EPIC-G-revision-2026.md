# ÉPIC G — Révision d'avril 2026 : multi-sujets et métriques de protection

**Origine** : [`04-datasets-et-metriques-2026.md`](../rapport/04-datasets-et-metriques-2026.md)
et [SPEC-07 v2.0](../specifications/SPEC-07-metriques.md).

**Objectif** : intégrer les métriques qui mesurent réellement la protection —
CPR/IPR et TRIR — et les corpus qui permettent de les valider.

**Effort** : ~4 jours.

---

## Pourquoi cet épic existe

Sur SPIA, un masqueur NER atteint **ER_di = 0,997** et un **CPR de 0,330** :
99,7 % des identifiants directs masqués, et deux tiers des informations
personnelles toujours inférables.

C'est la preuve empirique que le backlog initial, centré sur la détection et le
déterminisme, est **nécessaire mais pas suffisant** : il produirait un pipeline
fiable qui mesure la mauvaise chose. Cet épic ajoute la mesure de ce qui compte.

---

## G-1 — Adaptateurs `spia` et `panorama`

| | |
|---|---|
| **Priorité** | **P0 pour l'axe D** |
| **Dépend de** | B-3 (TAB, dont SPIA reprend 144 documents) |
| **Difficulté nouvelle** | **Annotation multi-sujets** |
| **Effort** | 1 j |

### Ce que ces corpus apportent

**SPIA** — 675 documents (144 TAB + 531 PANORAMA), **1 712 sujets**, 7 040 PII,
15 catégories. Premier dataset multi-sujets avec métriques d'inférence par
sujet. Sans lui, CPR et IPR ne sont validables sur aucune référence externe et
le projet ne peut pas se situer par rapport à la littérature.

**PANORAMA** — 384 789 documents synthétiques avec **cohérence d'attributs
forcée** (âges familiaux cohérents, correspondance éducation-emploi). Cette
cohérence produit des combinaisons de QI **plausibles**, là où un générateur
naïf produit des profils incohérents dont le `k` n'a aucun sens. C'est un modèle
méthodologique direct pour [SPEC-05](../specifications/SPEC-05-generation-corpus-synthetiques.md).

Les deux sont **ouverts et redistribuables** (MIT + CC BY 4.0). Le cache
PersonalReddit local est distinct : il contient les exemples synthétiques ETH SRI
sous CC BY-NC-SA 4.0 ; le PersonalReddit réel de l'article ICLR n'est pas
distribué.

### Périmètre

- `src/anonymisation/datasets/spia.py`, `panorama.py`
- `configs/datasets/{spia,panorama}.yaml`
- `tests/integration/test_spia.py`
- **modification de SPEC-02** (voir ci-dessous)

### Difficulté principale : le schéma doit devenir multi-sujets

SPEC-02 associe aujourd'hui un `Document` à **un** `author_id`. SPIA associe à
chaque document **plusieurs sujets**, chacun avec ses propres PII.

Deux options :

| Option | Description | Verdict |
|--------|-------------|---------|
| 1 | `Document.subject_ids: tuple[str, ...]` + `Annotation.subject_id` | **Recommandée** — explicite, et nécessaire au calcul de $N$ dans IPR |
| 2 | `Annotation.subject_id` seul, `author_id` restant le sujet principal | Rend le comptage des sujets implicite et fragile |

L'option 1 impose une **nouvelle version de SPEC-02** et une mise à jour de
`schema/validation.py` (un `subject_id` orphelin devient un cas `E-VAL-104`).

### Critères d'acceptation

- [ ] 675 documents SPIA chargés, **1 712 sujets** distincts recensés.
- [ ] Chaque annotation est rattachée à un sujet identifié.
- [ ] `text[start:end] == span_text` sur 100 % des annotations.
- [ ] Les 15 catégories sont mappées vers SPEC-01, aucune orpheline.
- [ ] Un document multi-sujets figure dans les fixtures de test.
- [ ] Le recouvrement SPIA ∩ TAB est identifié et exposé.

### Piège connu

**144 documents de SPIA viennent de TAB.** Évaluer sur « TAB + SPIA » sans
déduplication gonflerait la taille apparente de l'échantillon et introduirait
une corrélation entre deux corpus présentés comme indépendants.

---

## G-2 — CPR et IPR (protection multi-sujets)

| | |
|---|---|
| **Priorité** | **P0 — ce sont désormais les métriques principales** |
| **Dépend de** | G-1, D-2 |
| **Spécs** | SPEC-07 v2.0 §5 |
| **Effort** | 1 j |

### Contexte

SPEC-07 v2.0 place **CPR et IPR devant $R_{succ}$**. Raison : l'AAC et
$R_{succ}$ ne mesurent que le **sujet cible**, or SPIA documente jusqu'à
**11 points d'écart** entre 1−AAC et CPR — protéger un sujet peut laisser les
autres nettement moins protégés.

Décisif ici : un ticket support mentionne presque toujours un client, un agent
et souvent un tiers ; un document RH mentionne un candidat et un référent.

### Périmètre

- `src/anonymisation/metrics/protection.py`
- `tests/unit/test_protection.py`

### Travail

$$
CPR = 1 - \frac{\sum_i A_i}{\sum_i O_i}
\qquad\qquad
IPR = \frac{1}{N}\sum_i \left(1 - \frac{A_i}{O_i}\right)
$$

```python
@dataclass(frozen=True)
class SubjectOutcome:
    subject_id: str
    pii_total: int          # O_i
    pii_still_inferable: int  # A_i

def collective_protection_rate(subjects) -> float
def individual_protection_rate(subjects) -> float
def adversarial_accuracy(guesses, truth) -> float   # 1.0 exact / 0.5 partiel / 0.0 faux
```

L'AAC est conservée comme **diagnostic mono-sujet**, jamais comme métrique
principale.

### Critères d'acceptation

- [ ] Sur un cas où un sujet porte 10 PII et un autre 1 PII, **CPR et IPR
      diffèrent** — c'est toute la raison de les publier ensemble.
- [ ] $O_i = 0$ est traité explicitement : sujet exclu du calcul d'IPR, pas une
      division par zéro.
- [ ] Un test reproduit l'écart 1−AAC vs CPR sur un document multi-sujets.
- [ ] `assert_published_together` : les deux métriques sortent ensemble ou
      aucune ne sort.

### Piège connu — et opportunité de contribution

Les auteurs de SPIA notent que CPR et IPR **pondèrent toutes les catégories de
PII également**, alors que le risque diffère entre un identifiant direct et un
quasi-identifiant. Ils posent comme travail futur la pondération par type et la
modélisation k-anonymat.

**C'est l'espace de contribution du projet** ([04 §5](../rapport/04-datasets-et-metriques-2026.md)).
Prévoir dès l'implémentation un paramètre `weights: dict[str, float]` par
catégorie SPEC-01 : poids uniformes par défaut pour rester **comparable à
SPIA**, variante pondérée publiée à côté.

---

## G-3 — TRIA / TRIR (risque de ré-identification)

| | |
|---|---|
| **Priorité** | P1 |
| **Dépend de** | D-2, G-1 |
| **Spécs** | SPEC-07 v2.0 §5 |
| **Effort** | 1 j |

### Contexte

**TRIA** (*Text Re-Identification Attack*) : un modèle entraîné à ré-identifier
un document anonymisé parmi un ensemble candidat. **TRIR** : la métrique de
risque dérivée de son accuracy [@manzanares2024tria].

⚠️ **À ne pas confondre avec PETRE.** TRIA/TRIR (DMKD 2024) et PETRE (KBS 2025)
sont deux travaux distincts de la même équipe : TRIR est la **métrique**, PETRE
la **méthode d'anonymisation** pilotée par ce risque. Citer l'un pour l'autre
serait une erreur bibliographique visible en review.

### Périmètre

- `src/anonymisation/metrics/tria.py`
- `tests/unit/test_tria.py`

### Travail

1. Constituer l'ensemble candidat (documents originaux du corpus).
2. Classifieur de ré-identification document → sujet.
3. `TRIR` = accuracy de ré-identification sur les documents anonymisés.
4. **Rester hors LLM** : TF-IDF + régression logistique suffit pour une
   première version, et respecte la règle « pas de LLM avant 0 % d'erreur ».

### Critères d'acceptation

- [ ] TRIR élevé sur texte non anonymisé ; proche du hasard ($1/N$) sur texte
      entièrement supprimé.
- [ ] TRIR décroît de façon monotone de P0 à P4.
- [ ] La **taille de l'ensemble candidat** est déclarée avec le score : un TRIR
      sur 10 candidats n'est pas comparable à un TRIR sur 1 000.
- [ ] Aucun appel LLM.

---

## G-4 — Mean Utility (axe C)

| | |
|---|---|
| **Priorité** | P1 |
| **Dépend de** | D-2 |
| **Spécs** | SPEC-07 v2.0 §6.A |
| **Effort** | 0,5 j |

### Travail

$$
\text{Mean Utility} = \text{moyenne}\big(\text{Readability},\ \text{Meaning},\ \text{ROUGE-L}\big)
$$

ROUGE-L est calculable sans dépendance lourde. *Readability* et *Meaning*
requièrent un **LLM juge** : les placer derrière une interface, avec un repli
retournant `MetricStatus.UNAVAILABLE` quand aucun juge n'est configuré —
**jamais une valeur par défaut**.

### Critères d'acceptation

- [ ] ROUGE-L fonctionne sans LLM, sans dépendance hors stdlib/numpy.
- [ ] Sans juge configuré, Mean Utility retourne `UNAVAILABLE`, pas une valeur
      partielle silencieuse.
- [ ] Le LLM juge utilisé figure dans la scorecard.
- [ ] Un test documente le piège : généraliser « 28 ans » en « fin de
      vingtaine » **dégrade** ROUGE-L alors que c'est une bonne anonymisation.
      C'est ce qui justifie l'utilité métier (SPEC-07 §6.B) comme référence.

---

## G-5 — Partial match `nervaluate` et ER_di / ER_qi

| | |
|---|---|
| **Priorité** | **P0** |
| **Dépend de** | D-1 |
| **Spécs** | SPEC-07 v2.0 §2 |
| **Effort** | 0,5 j |

### Contexte

SPEC-07 v2.0 change le **mode de correspondance par défaut** : `partial`
(SemEval-2013 task 9.1) remplace `overlap`. Argument des auteurs d'IPI : la
difficulté est de *trouver* l'information ; masquer un span un peu trop long ne
nuit pas à la personne.

Et surtout : **ER_di / ER_qi**, le rappel au niveau **entité**. Si un nom
apparaît 4 fois et que 3 occurrences sont masquées, l'entité n'est **pas**
protégée.

### Périmètre

- `src/anonymisation/metrics/spans.py` (extension)
- `src/anonymisation/metrics/entities.py`
- `tests/unit/test_er_metrics.py`

### Travail

1. Implémenter le partial match SemEval-2013 (réimplémentation directe ;
   `nervaluate` n'est pas dans les dépendances autorisées et l'algorithme est
   court).
2. `ER_di` et `ER_qi` : une entité compte comme protégée **seulement si toutes
   ses mentions sont masquées**.
3. Micro-moyenne sur les annotateurs.

### Critères d'acceptation

- [ ] Sur une entité à 4 mentions dont 3 masquées, `ER` vaut **0** pour cette
      entité, alors que le rappel span-level vaut 0,75. Le test l'exige
      explicitement — c'est toute la différence.
- [ ] Les 3 modes (`exact`, `partial`, `entity`) donnent des valeurs distinctes
      sur un cas construit.
- [ ] La micro-moyenne multi-annotateurs est testée sur un document à
      2 annotateurs divergents.

---

## G-6 — Trancher le statut de PersonalReddit — **Résolu**

| | |
|---|---|
| **Priorité** | **P0 — bloquant pour toute mesure sur ce corpus** |
| **Dépend de** | — |
| **Effort** | 0,25 j |
| **Décision** | Le cache local est synthétique (`structure.synthetic: true`) |

### Contradiction résolue

| Source | Constat |
|--------|---------|
| `README.md` du cache local | Décrit des commentaires Reddit synthétiques et pointe vers `eth-sri/llmprivacy/data/synthetic`. |
| Dépôt ETH SRI | Le PersonalReddit original n'est pas publié pour des raisons de vie privée ; des exemples synthétiques sont publiés séparément. |
| Cache local | 318 lignes `train` + 207 lignes `test` = 525 exemples, 40 profils latents ; l'union correspond à `synthetic_dataset.jsonl` après retrait du champ local `label`. |
| Inspection du contenu | Profils, réponses et lieux générés ; aucun identifiant de compte ou nom d'utilisateur Reddit réel. |

Les **520 profils réels** rapportés par `staab2024beyond` ne sont donc pas dans le
cache local. La proximité numérique entre 520 profils et 525 exemples ne prouve
aucune identité de corpus.

### Conséquences appliquées

- `configs/datasets/personalreddit.yaml` déclare `structure.synthetic: true`,
  525 documents, 40 profils et la licence CC BY-NC-SA 4.0.
- `documentation/datasets/personalreddit.md` distingue explicitement la release
  synthétique du corpus réel non redistribué.
- La garde E2 n'est pas applicable au cache synthétique ; elle reste obligatoire
  pour toute source Reddit réelle.
- Les fichiers locaux `train.jsonl` et `test.jsonl` partagent les 40 profils :
  ils ne doivent pas être utilisés comme split auteur-disjoint. Toute mesure
  author-level doit reconstruire un split groupé déterministe.

### Critères d'acceptation

- [x] Le statut est établi, avec preuve de provenance, volumétrie et contenu.
- [x] Le manifeste porte `structure.synthetic: true`.
- [x] La fiche `personalreddit.md` est corrigée et la contradiction documentée.
- [x] La règle conservatrice est satisfaite par une séparation explicite entre
      cache synthétique et PersonalReddit réel non distribué ; aucune donnée
      ambiguë n'est traitée comme réelle sans preuve.
