# SPEC-08 — Modèles d'attaquants

| | |
|---|---|
| **Statut** | Brouillon |
| **Version** | 0.9 |
| **Date** | 2026-08-30 |
| **Dépend de** | SPEC-06, SPEC-07 |

---

## 1. Objet

La métrique principale du projet ($R_{succ}$) n'existe que relativement à un
attaquant. Cette spécification définit **qui attaque, avec quoi, et selon quel
protocole**, ainsi que les garde-fous éthiques.

Sans attaquant spécifié, un $R_{succ}$ ne veut rien dire.

## 2. Les trois niveaux

| Niveau | Adversaire | Accès | Usage |
|--------|-----------|-------|-------|
| **A** | LLM local 7–14 B | Texte anonymisé seul, pas d'accès externe | **Benchmark quotidien** — risque résiduel hors ligne |
| **B** | LLM plus puissant (< 30 B, ou modèle de référence) | Idem | Vérifie que la protection ne tient pas qu'aux limites d'un petit modèle |
| **C** | Agent avec recherche web + sources auxiliaires | Texte + web + population de référence | **Stress-test final** |

### Pourquoi trois et pas un

Un système protégé contre A mais pas contre B est protégé par la faiblesse de
l'adversaire, pas par l'anonymisation. C'est une propriété fragile : le
lendemain, un meilleur modèle local existe.

Le niveau C **change la nature de la menace**. AURA [@li2026aura] montre que des
indices faibles peuvent être reliés à des sources publiques et conduire à une
ré-identification que ni A ni B n'obtiendraient. InferLink [@ko2026inferlink] va
plus loin en séparant le type de cue, l'intention et la connaissance préalable
de l'attaquant, et propose des métriques automatiques de succès de linkage.

## 3. Ce que fait un attaquant

Trois tâches distinctes, à ne pas confondre :

| Tâche | Sortie | Métrique |
|-------|--------|----------|
| **T1 — Inférence d'attributs** | $\hat{Q}$ : les QI reconstitués depuis le texte anonymisé | Précision/rappel par catégorie QI |
| **T2 — Linkage** | Un ou plusieurs candidats dans la population $P$ | Top-1 / Top-5 identity accuracy |
| **T3 — Récupération d'identifiant direct** | Nom, email, etc. | DILR |

$R_{succ}$ est défini sur **T2**. T1 est le diagnostic intermédiaire : il dit
*pourquoi* T2 réussit.

## 4. Protocole d'attaque

```
document anonymisé
        │
        ▼
[T1] inférence d'attributs  ──→ Q̂ = {(catégorie, valeur, confiance)}
        │
        ▼
[T2] linkage sur la population de référence
        │
        ├─ EC_P(Q̂) = candidats compatibles
        ├─ classement des candidats
        └─ top-1, top-5
        │
        ▼
[eval] la vraie personne est-elle dans le top-1 / top-5 ?
```

### Règles

1. L'attaquant reçoit **uniquement** le texte anonymisé, jamais l'original,
   jamais les annotations, jamais le profil latent.
2. L'attaquant connaît la **population de référence** — hypothèse conservatrice
   et réaliste (les données INSEE sont publiques).
3. L'attaquant connaît le **domaine** et la nature du corpus (RH, support,
   forum) : cette information est disponible en pratique.
4. Le budget (nombre d'appels, de requêtes web) est **déclaré** et identique
   entre systèmes comparés.

### Portées

L'attaque DOIT être menée aux trois portées :

| Portée | Entrée de l'attaquant |
|--------|----------------------|
| `document` | Un document anonymisé |
| `thread` | Le fil complet anonymisé |
| `author` | Tout l'historique anonymisé du même auteur |

L'écart entre `document` et `author` mesure l'effet d'agrégation, qui est le
phénomène central du domaine forums
([`forum-qi-bench §4`](../datasets/forum-qi-bench.md)).

## 5. Attaquant A — LLM local

| Aspect | Choix |
|--------|-------|
| Modèles | Qwen 7B, Llama 8B, Mistral 7B (au moins deux, pour ne pas dépendre d'un seul) |
| Exécution | Locale, hors ligne |
| Prompt | Gabarit fixe, versionné, par domaine et par langue |
| Température | Basse (0.1–0.3) — l'attaquant cherche la précision |
| Sorties | JSON structuré : $\hat{Q}$ + candidats + justification |

C'est l'attaquant du cycle de développement quotidien : rapide, reproductible,
gratuit.

## 6. Attaquant B — LLM plus puissant

Même protocole, modèle plus capable (jusqu'à 30 B sous contrainte projet, ou un
modèle de référence hors contrainte à titre de borne supérieure).

Résultat attendu et à publier : **l'écart A → B**. Un écart important signale
une protection fragile.

## 7. Attaquant C — Agent avec recherche web

| Aspect | Choix |
|--------|-------|
| Capacités | Recherche web, consultation de sources publiques, chaînage multi-étapes |
| Budget | Nombre de requêtes plafonné et déclaré |
| Cible | **Corpus synthétiques uniquement** (voir §8) |
| Références | AURA [@li2026aura], InferLink [@ko2026inferlink] |

Décomposition inspirée d'InferLink, à conserver dans le rapport :

- **type de cue** exploitée (démographique, professionnelle, temporelle…) ;
- **intention** de l'attaque ;
- **connaissance préalable** supposée.

## 8. Garde-fous éthiques — normatifs

Cette section est **contraignante**. Le projet développe un outil de
ré-identification ; l'encadrer n'est pas une formalité.

| # | Règle |
|---|-------|
| **E1** | L'attaquant C (recherche web) NE DOIT être exécuté que sur des corpus **synthétiques** (`hr_qi`, `support_qi`, `forum_qi`, `ratbench`, `synthpai`). |
| **E2** | Il NE DOIT PAS être exécuté sur TAB, IPI/MIMIC, JobStack, MEDDOCAN, MultiCoNER — corpus contenant des **personnes réelles**. |
| **E3** | Aucune sortie d'attaquant identifiant une personne réelle NE DOIT être journalisée, versionnée ou publiée. Seules les métriques agrégées le sont. |
| **E4** | Les journaux d'attaque sur corpus réels sont limités à des **compteurs** : succès/échec, catégorie de QI exploitée. Jamais le contenu. |
| **E5** | Toute publication d'exemple qualitatif DOIT porter sur un individu **synthétique**. |
| **E6** | Le code d'attaque N'EST PAS un livrable diffusable séparément du cadre d'évaluation. |

E1 et E2 sont des **contrôles automatiques** : l'attaquant C refuse de démarrer
si le manifeste du dataset ne porte pas `structure.synthetic: true`. Ce n'est
pas une consigne dans la documentation, c'est une garde dans le code.

## 9. Reproductibilité

| Élément | Traitement |
|---------|-----------|
| Prompts | Versionnés dans `configs/attack/prompts/<niveau>/<domaine>/<langue>.txt` |
| Modèles | Version et quantisation figées dans le rapport |
| Températures, seeds | Déclarées |
| Budget web (C) | Plafond déclaré ; les résultats web étant non reproductibles dans le temps, publier la **date d'exécution** |

L'attaquant C n'est pas reproductible au sens strict (le web change). Le
déclarer honnêtement est préférable à prétendre le contraire : son rôle est de
borner le risque, pas de fournir un chiffre stable.

## 10. Interaction avec le moteur de risque

Deux chiffres à ne jamais confondre :

| | Origine | Nature |
|---|---------|--------|
| **Risque prédit** | Moteur de risque (SPEC-06) | Estimation *a priori*, calibrée |
| **Risque réalisé** ($R_{succ}$) | Attaquant | Mesure *a posteriori*, empirique |

La corrélation entre les deux est un **résultat majeur** du projet : elle valide
(ou invalide) le moteur de risque. À publier comme telle, avec la corrélation de
Spearman et un diagramme de fiabilité.

Un moteur qui prédit bien et un attaquant qui réussit peu, c'est le résultat
recherché. Un moteur qui prédit un risque faible là où l'attaquant réussit,
c'est un échec de calibration à publier honnêtement.

## 11. Critères de sortie

- [ ] Les trois niveaux sont implémentés, avec prompts versionnés.
- [ ] Les gardes E1/E2 sont implémentées **en code** et testées (test qui
      vérifie que C refuse de démarrer sur TAB).
- [ ] Aucun log d'attaque ne contient de texte issu d'un corpus réel.
- [ ] L'attaque est menée aux trois portées.
- [ ] L'écart A → B → C est mesuré et publié.
- [ ] La corrélation risque prédit / risque réalisé est calculée.
- [ ] Test S4 de [SPEC-07 §11](SPEC-07-metriques.md) : le mode `NON_STANDARD`
      produit un risque supérieur au mode `EXPLICIT`.

## 12. Questions ouvertes

- Quel modèle exactement pour B, sous contrainte < 30 B ?
- Comment plafonner le budget web de C de façon comparable entre systèmes ?
- Faut-il un attaquant « humain » sur un petit échantillon, comme borne de
  référence ? (coûteux mais très convaincant en publication)
- L'attaquant doit-il être adaptatif (apprendre des échecs) ? Cela le
  rapprocherait du cas réel mais compliquerait la comparabilité.

## 13. Journal des modifications

| Version | Date | Changement |
|---------|------|-----------|
| 0.9 | 2026-08-30 | Création. Trois niveaux, protocole T1/T2/T3, garde-fous E1–E6 normatifs. |
