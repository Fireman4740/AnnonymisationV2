# SPEC-07 — Métriques

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date** | 2026-08-30 |
| **Dépend de** | SPEC-02, SPEC-06 |

---

## 1. Principe

> **Le F1 de détection n'est pas la métrique principale du projet.**

Hiérarchie normative :

| Rang | Métrique | Direction | Rôle |
|-----:|----------|:---------:|------|
| 1 | **Residual Re-Identification Risk** ($R_{succ}$) | ↓ | Métrique principale |
| 2 | **Utility Retention** | ↑ | Second axe du compromis |
| 3 | **QI Combination Recall** (QICR) | ↑ | Diagnostic central |
| 4 | Calibration (ECE, Brier, MAE-k) | ↓ | Condition de validité de la politique |
| 5 | P / R / F1 par span | — | Diagnostic bas niveau |

Aucun rapport ne DOIT présenter un F1 comme résultat principal.

---

## 2. Niveau 1 — Détection des spans

### Formules

$$
P = \frac{TP}{TP+FP}, \qquad
R = \frac{TP}{TP+FN}, \qquad
F1 = \frac{2PR}{P+R}
$$

### Priorité privacy-first

**Le rappel prime sur la précision.** Un faux négatif de confidentialité est
plus grave qu'un faux positif : le premier laisse fuiter, le second dégrade
l'utilité. Cohérent avec TAB [@pilan2022tab].

Une métrique agrégée DEVRAIT donc pondérer le rappel :

$$
F_\beta = \frac{(1+\beta^2)PR}{\beta^2 P + R}, \qquad \beta = 2
$$

### Métriques TAB reprises telles quelles

| Métrique | Définition |
|----------|-----------|
| **Entity-level recall — identifiants directs** | Une entité est rappelée si **au moins une** de ses mentions est détectée ; le rappel se calcule sur les entités, pas les spans |
| **Entity-level recall — quasi-identifiants** | Idem, restreint aux `QUASI` |
| **Weighted token-level precision** | Précision au token, pondérée par le poids informationnel du token |
| **Utilité pondérée** | Information supprimée, pondérée par le contenu informationnel |

Le rappel entity-level est celui qui compte : masquer 9 des 10 mentions d'un nom
ne protège rien. Le rappel span-level, lui, afficherait 90 %.

### Déclinaisons obligatoires

| Déclinaison | Importance |
|-------------|-----------|
| Macro-F1 **par catégorie QI** | Très élevée |
| F1 **par langue** | Très élevée |
| F1 **par domaine** | Très élevée |
| F1 **par `expression_mode`** | Très élevée |
| Type-aware F1 | Élevée |
| Span recall / F1 | Élevée |
| Span precision | Moyenne |

Les dénominateurs proviennent de `.validation.json`
([SPEC-04 §5](SPEC-04-pipeline-ingestion.md)).

### Correspondance de spans

| Mode | Règle | Usage |
|------|-------|-------|
| `exact` | Offsets identiques | Rapport strict |
| `overlap` | Intersection non vide | **Défaut** — un masquage partiellement décalé protège quand même |
| `entity` | Au moins une mention par entité | Rapport privacy |

Le mode utilisé DOIT être déclaré avec tout score.

---

## 3. Niveau 2 — Détection combinatoire

C'est le niveau où le projet apporte quelque chose de neuf.

### QI Combination Recall (QICR)

$$
QICR = \frac{\#\text{combinaisons de QI à risque correctement détectées}}
             {\#\text{combinaisons de QI réellement à risque}}
$$

Une combinaison est « à risque » si $k_{true} \leq k_{seuil}$ (défaut 10,
SPEC-01 §6.3).

**Détectée correctement** = le système a identifié **tous** les QI de la
combinaison. C'est une condition exigeante, et c'est le point.

#### Exemple

| | |
|---|---|
| Vérité terrain | `{age<30, PhD, location=Lille, department=Physics}` |
| Système | `{age<30, PhD, location=Lille}` |
| Span-level F1 | ≈ 0.86 (3 sur 4, précision parfaite) |
| **QICR** | **0** pour cette combinaison |

Le système a détecté les éléments individuels et raté la combinaison. Le F1
classique ne mesure pas cette erreur ; QICR si.

### Variantes de diagnostic

$$
QICR@j = \text{QICR restreint aux combinaisons de taille } j
$$

Permet de voir à partir de quelle taille de combinaison le système décroche.

### Risky Combination Recall @ k

$$
RCR@k = P\big(\hat{k} \geq k \mid k_{true} \geq k\big)
$$

Lecture : le système reconnaît-il correctement les situations où il existe
**suffisamment** de personnes pour que le risque soit acceptable ? C'est la
mesure du **sur-masquage** : un système qui déclarerait tout à risque aurait un
QICR parfait et un RCR@k nul.

**QICR et RCR@k DOIVENT être publiés ensemble.** Séparément, chacun est
manipulable.

---

## 4. Niveau 3 — Qualité du score de risque

### Erreur sur $k$

$$
MAE_k = \frac{1}{N}\sum_i |\hat{k_i} - k_i|
\qquad
MALE_k = \frac{1}{N}\sum_i \big|\log(\hat{k_i}+1) - \log(k_i+1)\big|
$$

$MALE_k$ est **la métrique à privilégier** : l'écart entre $k = 1$ et $k = 3$
importe infiniment plus que l'écart entre $k = 1000$ et $k = 1002$, et $MAE_k$
ne le voit pas.

### Erreur de risque

$$
MAE_R = \frac{1}{N}\sum_i |\hat{R_i} - R_i|
$$

### Discrimination

- **AUROC** — risque élevé vs acceptable.
- **AUPRC** — à privilégier, les cas fortement risqués étant rares.

### Calibration

$$
\text{Brier} = \frac{1}{N}\sum_i (\hat{R_i} - y_i)^2
$$

$$
ECE = \sum_{b=1}^{B} \frac{|B_b|}{N}\,\big|\,\overline{y}(B_b) - \overline{\hat{R}}(B_b)\,\big|
$$

avec $B$ bacs d'équi-effectif (défaut $B = 10$).

**Cible : ECE < 0.05 par domaine.** En dessous de cette qualité, la politique
par seuils

```text
risk < 0.05    → garder
0.05 – 0.10    → généraliser
0.10 – 0.20    → anonymiser
> 0.20         → supprimer
```

ne veut rien dire : les seuils ne correspondraient pas aux probabilités
annoncées.

### Garde-fou de circularité

> Les métriques de niveau 3 n'acceptent que des combinaisons dont
> `source ∈ {generated, annotated, dataset}` (SPEC-02, invariant I-CMB-3).

Évaluer le moteur de risque contre des $k$ calculés par ce même moteur
produirait une calibration parfaite et vide. Le contrôle est automatique et
bloquant.

---

## 5. Niveau 4 — Résistance à la ré-identification

### Métrique principale

$$
R_{succ} = \frac{\#\text{documents ré-identifiés}}{\#\text{documents}}
\qquad\text{(↓ meilleur)}
$$

C'est la logique de RAT-Bench [@krco2026ratbench] : un attaquant tente d'inférer
les identifiants, le benchmark estime ensuite le risque dans la population.

**Toute publication du projet DOIT présenter $R_{succ}$ en résultat principal.**

### Compléments

| Métrique | Formule / définition |
|----------|---------------------|
| Top-1 identity accuracy | L'attaquant désigne exactement la bonne personne |
| Top-5 identity accuracy | La bonne personne est dans les 5 candidats |
| **DILR** | $\dfrac{\#\text{docs contenant un identifiant direct récupérable}}{\#\text{docs}}$ |
| **IRR** | $\dfrac{\#\text{docs ré-identifiés par QI}}{\#\text{docs}}$ |
| $k$ résiduel | Distribution de $k$ après anonymisation (publier p5, médiane, p95) |
| Risque p95 / max | Le pire cas, pas la moyenne |

### La distinction à publier

> **Direct privacy leakage** (DILR) vs **combinatorial indirect leakage** (IRR).

C'est un résultat en soi : un système peut avoir un DILR nul (aucun nom ne
fuit) et un IRR élevé (les gens sont retrouvés par combinaison). Les confondre
masquerait exactement le phénomène que le projet étudie.

### Conditions de comparabilité

Un $R_{succ}$ n'est comparable qu'à un autre $R_{succ}$ obtenu avec **le même
attaquant, la même population et le même protocole**. Tout rapport DOIT
préciser : niveau d'attaquant (A/B/C), modèle, population de référence, portée
(document/thread/auteur).

---

## 6. Niveau 5 — Utilité

### A. Utilité textuelle (secondaire)

BERTScore, BLEU, ROUGE, similarité d'embeddings — utilisées par Tau-Eval
[@loiseau2025taueval]. **Ne DOIVENT PAS** être la métrique d'utilité
principale : un texte peut rester lexicalement proche et devenir inutilisable
pour la tâche.

### B. Utilité métier (principale)

$$
UtilityRetention = \frac{Performance(\text{anonymized})}{Performance(\text{original})}
$$

| Domaine | Tâches |
|---------|--------|
| RH | classification du type de demande, extraction de compétences, classification de poste, matching compétence/emploi |
| Support | classification de ticket, **routage**, priorité, intention, suggestion de résolution |
| Forums | thème, sentiment, **modération**, détection de sujet, clustering |

Exemple : routage F1 0.91 → 0.88 ⇒ rétention 96.7 %.

**Tâches de référence** : le routage (support) et la modération (forums). Ce
sont celles qui dépendent le plus des QI, donc celles qui révèlent le mieux la
tension. Une rétention élevée sur une tâche insensible aux QI ne prouve rien.

### Protocole

1. Entraîner le classifieur sur le texte **original**, mesurer $F1_{orig}$.
2. Appliquer l'anonymisation.
3. Évaluer le **même** classifieur (non réentraîné) sur le texte anonymisé.
4. Publier aussi la variante réentraînée sur anonymisé — les deux chiffres ne
   disent pas la même chose (adaptation possible ou non côté aval).

---

## 7. Le Privacy-Utility Operating Point

Ne pas publier « F1 = 91 % ». Publier une table de points de fonctionnement :

| Policy | Re-ID Risk ↓ | Utility ↑ | Latency |
|--------|-------------:|----------:|--------:|
| P0 | 31 % | 98 % | 100 ms |
| P1 | 17 % | 96 % | 220 ms |
| P2 | 8 % | 93 % | 500 ms |
| P3 | 3 % | 87 % | 1.2 s |
| P4 | 1 % | 74 % | 2.4 s |

*(format cible ; valeurs illustratives)*

Et tracer la frontière :

```text
Privacy
↑
│       ●
│      ●
│    ●
│   ●
│ ●
└────────────────→ Utility
```

Orientation partagée avec Tau-Eval [@loiseau2025taueval] et les travaux
d'anonymisation adaptative. Les politiques P0…P4 sont définies dans
`configs/policy/`.

---

## 8. Efficacité

Contrainte « modèles locaux < 30 B » ⇒ le coût est un résultat, pas une note de
bas de page.

| Métrique | Unité |
|----------|-------|
| Latence par document | ms (médiane et p95) |
| Débit | tokens/s |
| RAM CPU | Go |
| VRAM | Go |
| Coût énergétique | Wh par 1 000 documents (optionnel) |

À publier pour chaque baseline (Presidio, GLiNER/XLM-R, petit LLM) et chaque
politique.

---

## 9. Statuts de métrique

Repris de la V1 (`MetricStatus`) :

| Statut | Signification |
|--------|---------------|
| `OFFICIAL` | Protocole officiel du dataset, volumétrie complète, licence connue |
| `SAMPLED` | Sous-échantillon, plan d'échantillonnage documenté |
| `DIAGNOSTIC` | Interne, non comparable à la littérature |
| `PROXY` | Approximation d'une métrique officielle non réimplémentée |
| `UNAVAILABLE` / `FAILED` | Non calculable / erreur |

**Règle** : une métrique `DIAGNOSTIC` ou `PROXY` NE DOIT PAS être présentée
comme comparable à un chiffre publié. MultiCoNER, MEDDOCAN et tout $k$ calculé
sur SynthPAI sont `DIAGNOSTIC` par construction.

---

## 10. Format de rapport

```json
{
  "run_id": "2026-09-14T10:22:00Z-a3f1",
  "schema_version": "2.0",
  "system": { "detector": "gliner-multi", "policy": "P2", "attacker": "A" },
  "dataset": "hr_qi", "split": "test",
  "primary": {
    "reid_success_rate": { "value": 0.08, "status": "OFFICIAL", "direction": "MINIMIZE" },
    "utility_retention": { "value": 0.93, "status": "OFFICIAL", "direction": "MAXIMIZE" }
  },
  "diagnostic": {
    "qicr": 0.71, "rcr_at_10": 0.88,
    "ece": 0.041, "brier": 0.093, "male_k": 0.62,
    "entity_recall_direct": 0.98, "entity_recall_quasi": 0.79,
    "dilr": 0.01, "irr": 0.07
  },
  "by_language":   { "fr": { "...": 0 }, "en": { "...": 0 } },
  "by_domain":     { "hr": { "...": 0 } },
  "by_expression": { "EXPLICIT": {}, "NON_STANDARD": {}, "IMPLICIT": {} },
  "efficiency": { "latency_p50_ms": 480, "latency_p95_ms": 910, "vram_gb": 11.2 }
}
```

Les trois ventilations (`by_language`, `by_domain`, `by_expression`) sont
**obligatoires** : ce sont elles qui montrent où le système échoue, et
l'agrégat seul serait trompeur.

---

## 11. Tests de sanité obligatoires

Contrôles automatiques, qui attrapent les erreurs d'implémentation les plus
coûteuses :

| # | Test | Attendu |
|---|------|---------|
| S1 | Texte non anonymisé | $R_{succ}$ élevé, `UtilityRetention` = 1.0 |
| S2 | Texte entièrement supprimé | $R_{succ}$ ≈ 0, `UtilityRetention` faible |
| S3 | Politique plus stricte | $R_{succ}$ décroît, utilité décroît (monotonie) |
| S4 | Mode `NON_STANDARD` vs `EXPLICIT` | Risque plus élevé en non standard (tendance RAT-Bench 44 % → 69 %) |
| S5 | Portée `author` vs `document` | $R_{succ}$ plus élevé au niveau auteur |
| S6 | Entity recall vs span recall | Valeurs différentes (sinon la coréférence est ignorée) |

Un pipeline qui échoue S3 ou S5 a un bug, quelles que soient ses autres valeurs.

## 12. Journal des modifications

| Version | Date | Changement |
|---------|------|-----------|
| 1.0 | 2026-08-30 | Création. Cinq niveaux, QICR/RCR@k, garde-fou de circularité, format de rapport, six tests de sanité. |
