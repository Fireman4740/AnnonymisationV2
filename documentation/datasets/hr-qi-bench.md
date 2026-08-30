# HR-QI-Bench — corpus RH à construire

| | |
|---|---|
| **Clé interne** | `hr_qi` |
| **Priorité** | **P0** |
| **Benchmark** | B2, B3, B4 |
| **Statut** | **À construire** · fiche v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom | Indirect-QI Re-identification Benchmark — volet RH |
| Origine | **Production propre au projet** |
| Type | Synthétique à profil latent, ou dé-identifié depuis des données réelles |
| Langues | FR (primaire), EN (secondaire) |
| Domaine | RH — candidatures, profils, tickets RH internes, échanges avec un service du personnel |

## 2. Rôle et priorité

C'est **le corpus qui porte la contribution du projet**. La revue de littérature
conclut sans ambiguïté que le domaine RH est **très faiblement benchmarké** pour
les quasi-identifiants : JobStack couvre la PII explicite des offres d'emploi,
rien ne couvre

$$
\text{emploi} + \text{ancienneté} + \text{localisation} + \text{trajectoire} \rightarrow k
$$

Sans ce corpus, le projet ne peut publier aucun résultat RH.

## 3. Contenu cible

| | Cible |
|---|---|
| Profils latents | **600** |
| Documents | **3 000** (≈ 5 par personne) |
| Langue | 70 % FR, 30 % EN |
| Population de référence | France (INSEE) — voir [SPEC-06 §4](../specifications/SPEC-06-population-et-risque.md) |

### Types de documents

| Type | Part cible | Exemple |
|------|-----------:|---------|
| Ticket RH / demande administrative | 40 % | « j'ai moins de 30 ans et je suis doctorant et je cherche comment mettre un arrêt maladie » |
| Message à un manager / RH | 25 % | demande de mobilité, de formation, de congé |
| Extrait de CV / lettre de motivation | 20 % | parcours, diplômes, employeurs |
| Entretien annuel / feedback | 15 % | trajectoire, objectifs, difficultés |

## 4. Structure exigée

Chaque individu possède un **profil latent** :

```text
PERSON_ID     = P01742
age           = 28
education     = PhD
occupation    = researcher
location      = Lille
employer_size = 300-500
seniority     = 6
contract      = CDI
department    = Physics
```

puis **plusieurs observations textuelles** du même individu, avec la chaîne
complète :

```text
profile → documents → QI expressed → QI implicit → QI combination → ground-truth population
```

C'est cette structure qui permet de mesurer le **k combinatoire réel** et donc
QICR, MAE-k et R_succ.

## 5. Quasi-identifiants du domaine RH

Codes détaillés dans [SPEC-01](../specifications/SPEC-01-taxonomie-qi.md), bloc RH :

tranche d'âge · ancienneté · diplôme · fonction · niveau hiérarchique ·
département · localisation · historique professionnel · type de contrat ·
**combinaison employeur × rôle × localisation** · événements professionnels
rares.

La dernière ligne est la plus importante : c'est un **objet de risque unique**,
pas trois entités indépendantes. Un « responsable qualité chez un fabricant de
turbines à Belfort » est identifiable même sans nom.

## 6. Deux voies de construction

### Voie A — génération synthétique à profil latent (recommandée pour démarrer)

| Avantage | Inconvénient |
|----------|--------------|
| Aucun risque RGPD | Réalisme limité |
| Population de référence maîtrisée → **k gold exact** | Risque de biais du générateur |
| Difficulté contrôlable (explicite / non standard / implicite) | Le détecteur peut apprendre le style du générateur |
| Publiable et redistribuable | — |

Protocole : [SPEC-05](../specifications/SPEC-05-generation-corpus-synthetiques.md).
Modèle méthodologique : RAT-Bench et SynthPAI.

### Voie B — dé-identification de données RH réelles

| Avantage | Inconvénient |
|----------|--------------|
| Réalisme maximal | **RGPD** : base légale, minimisation, DPIA, durée de conservation |
| Distributions authentiques | Le k gold n'est pas connu, il doit être estimé |
| Crédibilité industrielle | Non redistribuable → résultats non reproductibles par un tiers |

**Décision recommandée** : commencer par la voie A, garder la voie B comme
validation externe sur un échantillon réduit, en interne uniquement.

> ⚠️ Si la voie B est engagée : la fiche doit être complétée d'une section
> conformité (base légale, finalité, DPIA, responsable de traitement) **avant**
> toute ingestion. Voir [SPEC-09](../specifications/SPEC-09-qualite-licences-ci.md).

## 7. Population de référence

Sans population, pas de k, donc pas de risque.

| Source | Usage |
|--------|-------|
| INSEE — recensement, emploi par catégorie socioprofessionnelle × département | distribution jointe approchée |
| INSEE — niveaux de diplôme par âge et région | attribut `education` |
| DARES / bases sectorielles | taille d'entreprise, type de contrat |

Le passage de marginales à une jointe est le point difficile : voir
[SPEC-06 §5](../specifications/SPEC-06-population-et-risque.md) (copule /
modèle génératif, d'après [@rocher2019estimating]).

## 8. Tâches d'utilité associées

Indispensables pour mesurer `UtilityRetention`
([SPEC-07 §5](../specifications/SPEC-07-metriques.md)) :

| Tâche | Étiquette à produire |
|-------|----------------------|
| Classification du type de demande RH | catégorie (congé, paie, mobilité, formation, santé…) |
| Extraction de compétences | liste de compétences |
| Classification de poste | famille de métier |
| Matching compétence / emploi | score de pertinence |
| Détection d'urgence / criticité | niveau |

**Ces étiquettes doivent être produites en même temps que le corpus**, pas
après. Un corpus sans étiquettes d'utilité ne permet de mesurer que la moitié du
compromis.

## 9. Couverture visée

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs | ✅ |
| QI indirects | ✅ |
| QI implicites | ✅ |
| **Combinaisons annotées** | ✅ |
| **Profil latent** | ✅ |
| Multi-documents par personne | ✅ |
| **Population de référence FR** | ✅ |
| Attaquant | ✅ |
| Français | ✅ |
| **Tâches d'utilité** | ✅ |
| Texte réel | ◐ (voie B seulement) |

## 10. Mapping vers le schéma interne

Le corpus est **produit directement au format interne** — c'est le seul de la
batterie dans ce cas. Aucun adaptateur de conversion n'est nécessaire ; il faut
en revanche un **générateur** conforme à SPEC-02 :

- `profiles.jsonl` — profils latents ;
- `documents.jsonl` — textes, `domain = "hr"` ;
- `annotations.jsonl` — spans QI avec `expression_mode` ;
- `combinations.jsonl` — combinaisons à risque avec `k_true` et `risk_true` ;
- `tasks.jsonl` — étiquettes d'utilité.

## 11. Splits et protocole

- Split **par `person_id`**, jamais par document.
- Réserver un **split « held-out profils »** : des personnes jamais vues, pour
  mesurer la généralisation du moteur de risque.
- Prévoir un axe `difficulty` explicite (explicite / non standard / implicite)
  pour reproduire l'analyse de RAT-Bench sur notre domaine.

## 12. Plan de construction

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Figer les attributs du profil RH et leurs domaines de valeurs | schéma de profil |
| 2 | Construire la population de référence FR | `configs/populations/fr-hr.yaml` |
| 3 | Échantillonner 600 profils depuis cette population | `profiles.jsonl` |
| 4 | Calculer le `k_true` de chaque combinaison de QI | `combinations.jsonl` |
| 5 | Générer les documents (LLM local, 3 modes d'expression) | `documents.jsonl` |
| 6 | Annoter automatiquement les spans à la génération (l'annotation est **dérivée du plan de génération**, pas post-hoc) | `annotations.jsonl` |
| 7 | Contrôle qualité humain sur un échantillon de 5 % | rapport de qualité |
| 8 | Produire les étiquettes d'utilité | `tasks.jsonl` |
| 9 | Geler la version, checksum, manifeste | `configs/datasets/hr_qi.yaml` |

**Le point 6 est la clé** : générer le texte *à partir* d'un plan d'attributs
donne l'annotation gratuitement et sans erreur d'annotateur. C'est l'avantage
décisif du synthétique et la raison pour laquelle la voie A démarre.

## 13. Critères d'acceptation

- [ ] 600 profils, 3 000 documents, tous rattachés à un profil existant.
- [ ] Chaque document porte au moins une combinaison de QI référencée dans
      `combinations.jsonl`.
- [ ] Le `k_true` est calculable pour 100 % des combinaisons.
- [ ] Les trois modes d'expression sont représentés (≥ 20 % chacun).
- [ ] Le contrôle humain sur 5 % valide : (a) le texte est plausible, (b)
      l'annotation correspond au texte, (c) aucun QI non planifié n'a été
      introduit par le générateur.
- [ ] Les étiquettes d'utilité permettent d'entraîner un classifieur atteignant
      un F1 de référence non trivial sur le texte original.
- [ ] Aucune fuite de profil entre splits.

## 14. Risques et questions ouvertes

| Risque | Mitigation |
|--------|-----------|
| **Le générateur introduit des QI non planifiés** (ex. il ajoute une ville par cohérence narrative) | Passe de détection automatique post-génération + contrôle humain ; tout QI non planifié est soit annoté, soit le document est rejeté |
| Le détecteur apprend le style du générateur plutôt que les QI | Varier les prompts, les modèles, les registres ; évaluer aussi sur TAB (réel) |
| Population de référence FR imparfaite | Documenter l'incertitude ; publier le k avec un intervalle, pas un point |
| Volume insuffisant pour un k fiable | Le k vient de la **population**, pas du corpus ; le corpus n'a besoin que de couvrir l'espace des combinaisons |

Questions ouvertes :

- Le corpus sera-t-il publié ? (fortement recommandé : c'est la contribution la
  plus réutilisable du projet)
- Quel modèle local pour la génération, et comment éviter qu'il soit le même que
  celui évalué ?
- Faut-il une version EN à contenu constant pour isoler l'effet de la langue ?
