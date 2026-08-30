# OpenPII 500k — AI4Privacy

| | |
|---|---|
| **Clé interne** | `openpii` |
| **Priorité** | **P0** |
| **Benchmark** | B1 (PII Detection) |
| **Statut de la fiche** | Stable · v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom | `ai4privacy/open-pii-masking-500k-ai4privacy` |
| Référence | [@ai4privacy2024openpii] |
| Type | **Synthétique** |
| Langues | **8**, dont le **français** (> 112 000 exemples FR annoncés dans cette version) |
| Classes | **20 classes PII** |
| Volume | ~500 000 exemples |
| Domaine | Généraliste |

## 2. Rôle et priorité

**La couche PII multilingue du projet.** C'est le dataset qui permet de traiter
correctement la partie « identifiants directs » — noms, emails, téléphones,
adresses, identifiants divers — et surtout de le faire **en français**, ce
qu'aucun autre corpus P0 ne permet.

C'est aussi le **premier adaptateur à implémenter** : le plus simple, il valide
la chaîne d'ingestion complète sur un cas facile avant d'attaquer TAB et
RAT-Bench.

## 3. Contenu et volumétrie

| | |
|---|---|
| Exemples | ~500 000 |
| Langues | 8 |
| Français | > 112 000 exemples |
| Classes PII | 20 |
| Taille disque | ~1–3 Go |

Volumétrie exacte par langue à relever à l'ingestion et à figer dans le
manifeste (`metadata.per_language_counts`), car elle conditionne toute mesure
« F1 par langue ».

## 4. Structure brute

Format Hugging Face, avec pour chaque exemple : le texte source, le texte
masqué, la liste des entités PII avec leurs offsets et leur classe, et des
métadonnées de langue / locale.

Structure exacte à figer au premier chargement. Points à vérifier :

1. Les offsets portent-ils sur le texte source ou sur une version tokenisée ?
2. Le texte masqué est-il aligné caractère à caractère avec le source ?
3. Les 20 classes sont-elles identiques dans toutes les langues ?

## 5. Accès et acquisition

| | |
|---|---|
| Source | `huggingface.co/datasets/ai4privacy/open-pii-masking-500k-ai4privacy` |
| Méthode | `datasets.load_dataset(...)` via `scripts/download_openpii.py` |
| Prérequis | Aucun a priori (vérifier un éventuel gating) |
| Cache local | `data/raw/openpii/` |

## 6. Licence et conformité

- Données **synthétiques** → aucune contrainte RGPD sur les personnes.
- Licence AI4Privacy : à relever précisément sur la carte du dataset (les
  différentes versions publiées par AI4Privacy n'ont pas toutes la même
  licence — **vérifier la version exacte utilisée**).
- Le champ `version` du manifeste doit épingler la révision HF (commit hash),
  pas seulement le nom du dataset.

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs | ✅ |
| **QI indirects** | ❌ |
| QI implicites | ❌ |
| Combinaisons | ❌ |
| Profil latent | ❌ |
| Population de référence | ❌ |
| **Multilingue** | ✅ |
| **Français** | ✅ |
| Domaine RH/support/forum | ❌ |
| Texte réel | ❌ |

## 8. Apport pour le projet

1. **La seule couverture française P0** pour la détection d'identifiants
   directs.
2. Volume suffisant pour **entraîner ou fine-tuner** un détecteur (GLiNER,
   XLM-R), contrairement à TAB ou IPI.
3. Permet de publier un **F1 par langue** sur la partie PII, qui est le
   prérequis de crédibilité avant de parler de QI.
4. Baseline de comparaison avec Presidio (B1 de
   [02-etat-de-l-art §14](../rapport/02-etat-de-l-art.md)).

## 9. Limites et pièges

> ⚠️ **OpenPII ≠ benchmark de QI indirects.**

C'est l'avertissement le plus important de la fiche. Un modèle peut obtenir un
F1 excellent sur OpenPII et échouer complètement sur :

> « je suis le seul doctorant de mon équipe à travailler sur ce sujet »

RAT-Bench [@krco2026ratbench] confirme explicitement ce décalage : de bonnes
performances sur des PII synthétiques ne garantissent en rien une protection
contre la ré-identification par combinaison d'attributs.

| Limite | Conséquence |
|--------|-------------|
| Aucun QI indirect | Ne mesure aucune des questions 2, 3, 4 du cadrage. |
| Synthétique | Formulations régulières, peu de bruit, peu d'implicite. Le F1 y est structurellement surestimé. |
| Généraliste | Aucun signal RH / support / forum. |
| Risque de sur-optimisation | Un modèle entraîné uniquement dessus apprendra des motifs de surface. Toujours l'évaluer aussi sur MultiCoNER II (bruité) et TAB (réel). |

**Règle de communication** : ne jamais présenter un score OpenPII comme un
résultat du projet. Il n'est qu'un contrôle de bon fonctionnement de la couche
basse.

## 10. Mapping vers le schéma interne

| Objet OpenPII | Objet interne | Notes |
|---------------|---------------|-------|
| exemple | `Document` | `domain = "generic"`, `language` depuis la métadonnée |
| entité PII | `Annotation` | `identifier_type = "DIRECT"` pour les classes identifiantes ; certaines classes (ex. `JOBTITLE`, `CITY`) doivent être mappées en `QUASI` |
| classe PII (20) | `Annotation.qi_category` | via `label_map` vers SPEC-01 |
| texte masqué | `Document.meta.masked_text` | conservé, utile comme référence de transformation |

> **Décision de mapping non triviale** : plusieurs des 20 classes OpenPII ne sont
> pas des identifiants directs (profession, ville, date de naissance…). Les
> classer mécaniquement en `DIRECT` fausserait le DILR
> ([SPEC-07 §4](../specifications/SPEC-07-metriques.md)). Le `label_map` doit
> être établi classe par classe, revu, et documenté dans
> `configs/datasets/openpii.yaml`.

## 11. Splits et protocole

- Reprendre les splits HF officiels.
- Toute métrique doit être produite **par langue** ; la moyenne toutes langues
  confondues est trompeuse (déséquilibre des volumes).
- Protocole `official` si volumétrie + révision HF + licence sont figées.

## 12. Plan d'implémentation de l'adaptateur

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Charger, inspecter le schéma, compter par langue | note §4 + `per_language_counts` |
| 2 | Épingler la révision HF | `configs/datasets/openpii.yaml` |
| 3 | Établir le `label_map` classe par classe (revue manuelle des 20 classes) | mapping documenté |
| 4 | Implémenter `OpenPiiAdapter` | `src/anonymisation/datasets/openpii.py` |
| 5 | Vérifier l'alignement des offsets sur le texte source | test automatique |
| 6 | Produire les métriques B1 par langue | rapport |
| 7 | Comparer à la baseline Presidio | rapport |

**Cet adaptateur est le premier à écrire.** Il sert de patron aux autres et
valide `DatasetAdapter`, le registre, le manifeste et la validation.

## 13. Critères d'acceptation

- [ ] Chargement complet sans erreur, volumétrie conforme au manifeste.
- [ ] `text[start:end] == span_text` pour 100 % des annotations, toutes langues.
- [ ] Les 20 classes sont mappées explicitement ; aucune classe par défaut.
- [ ] Le comptage par langue est produit et stocké dans le manifeste.
- [ ] Le français représente bien > 100 000 exemples (contrôle de l'annonce).
- [ ] Une baseline Presidio tourne de bout en bout sur ce dataset.

## 14. Questions ouvertes

- Quelle licence exacte pour la révision retenue ?
- Les 20 classes sont-elles homogènes entre langues, ou certaines sont-elles
  absentes de certaines langues ? (impacte le macro-F1 par langue)
- Quelle proportion des classes doit basculer en `QUASI` ? Décision à trancher
  et à figer avant toute mesure de DILR.
