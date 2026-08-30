# TAB — Text Anonymization Benchmark

| | |
|---|---|
| **Clé interne** | `tab` |
| **Priorité** | **P0** |
| **Benchmark** | B2 (Indirect QI Detection) |
| **Statut de la fiche** | Stable · v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom complet | The Text Anonymization Benchmark (TAB) |
| Référence | [@pilan2022tab] — *Computational Linguistics* 48(4):1053–1101, 2022 |
| Type | Texte réel, annoté manuellement |
| Langue | Anglais |
| Domaine | Juridique — arrêts de la Cour européenne des droits de l'homme (CEDH) |

## 2. Rôle et priorité

**Référence d'annotation du projet.** TAB est la seule ressource qui traite
l'anonymisation comme un problème d'anonymisation et non comme du NER. Il pose
implicitement :

> quelles informations doivent être masquées pour empêcher la divulgation de
> l'identité ?

et pas :

> quels tokens sont des noms ?

C'est aussi la source des **métriques privacy-oriented** reprises au niveau 1 de
[SPEC-07](../specifications/SPEC-07-metriques.md).

## 3. Contenu et volumétrie

| | |
|---|---|
| Documents | **1 268 affaires CEDH** |
| Annotations | Informations personnelles, types d'identifiants, attributs confidentiels, **coréférences** |
| Annotateurs | Plusieurs annotateurs par document (permet de mesurer l'accord) |
| Taille disque | ~50–150 Mo (à confirmer) |

### Ce qui est annoté

- **Identifiants directs** (`DIRECT`) — identifient seuls.
- **Quasi-identifiants** (`QUASI`) — identifient en combinaison.
- **Attributs confidentiels** — sensibles mais pas nécessairement identifiants.
- **Chaînes de coréférence** — une même personne mentionnée plusieurs fois.

La coréférence est un point structurant : elle est la raison pour laquelle le
rappel doit être calculé au niveau **entité**, pas au niveau span.

## 4. Structure brute

Format JSON, un enregistrement par affaire, avec le texte, les annotations par
annotateur, et les clusters d'entités. Structure exacte à figer en §4 lors du
premier téléchargement.

Points à vérifier impérativement :

1. Comment sont encodés les **offsets** (caractères ? tokens ?).
2. Comment sont représentés les **désaccords entre annotateurs**.
3. Comment sont représentés les **clusters de coréférence**.

## 5. Accès et acquisition

| | |
|---|---|
| Source | Dépôt officiel des auteurs (NorwAI / Univ. Oslo) + Hugging Face |
| Méthode | `scripts/download_tab.py` |
| Prérequis | Aucun |
| Cache local | `data/raw/tab/` |

**Note V1** : `eval/core/tab_official.py` et
`eval/core/dataset_adapters/tab.py` existent dans le dépôt V1, avec un cache
`eval/datasets/TAB`. À lire avant de réimplémenter — en particulier la logique
de métrique « officielle » qui a déjà été alignée sur le papier.

## 6. Licence et conformité

- Les arrêts CEDH sont des documents publics ; les annotations sont diffusées
  sous licence ouverte de recherche (version exacte à confirmer).
- Redistribution du corpus annoté : autorisée sous conditions, citation
  obligatoire de [@pilan2022tab].
- Pas de contrainte RGPD supplémentaire (documents déjà publics), mais les
  personnes citées sont **réelles** : ne jamais publier d'exemple ré-identifié
  produit par notre attaquant.

> ⚠️ Conséquence directe pour [SPEC-08](../specifications/SPEC-08-attaquants.md) :
> les sorties d'attaquant sur TAB ne doivent jamais être publiées verbatim, ni
> versionnées. Seules les métriques agrégées le sont.

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs | ✅ |
| QI indirects | ✅ |
| QI implicites | ◐ |
| Combinaisons annotées | ◐ (implicite via coréférence + types) |
| Coréférences | ✅ |
| Attributs confidentiels | ✅ |
| Population de référence | ❌ |
| Attaquant | ❌ |
| Multilingue | ❌ (anglais) |
| Domaine RH/support/forum | ❌ |
| Texte réel | ✅ |

## 8. Apport pour le projet

1. **Source de la taxonomie** (avec IPI) — voir
   [SPEC-01](../specifications/SPEC-01-taxonomie-qi.md).
2. **Source des métriques de niveau 1** :
   - entity-level recall pour les identifiants directs ;
   - entity-level recall pour les quasi-identifiants ;
   - weighted token-level precision ;
   - mesure d'utilité pondérée par l'information portée par le token masqué.
3. **Seul corpus de texte réel** avec annotation QI de qualité dans la batterie
   P0 — il ancre les résultats, qui seraient sinon entièrement synthétiques.
4. **Preuve que le rappel de spans ne suffit pas** — argument central du
   cadrage.

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| Domaine juridique | Ne doit **pas** devenir le benchmark principal. Les QI y sont juridiques (dates de procédure, numéros d'affaire), pas RH ni techniques. |
| Anglais seul | Aucune mesure multilingue possible. |
| Pas de population de référence | Aucun k calculable directement. TAB mesure la **détection**, pas le **risque**. |
| Pas d'attaquant | Ne mesure pas la résistance. |
| Désaccords entre annotateurs | Doivent être traités explicitement (union ? majorité ? annotateur de référence ?) — décision à documenter, elle change les chiffres. |
| Registre formel | Très éloigné des tickets support et des messages de forum. |

## 10. Mapping vers le schéma interne

| Objet TAB | Objet interne | Notes |
|-----------|---------------|-------|
| affaire | `Document` | `domain = "legal"`, `language = "en"` |
| annotation de span | `Annotation` | `identifier_type` depuis `DIRECT`/`QUASI` |
| type d'entité TAB | `Annotation.qi_category` | via `label_map` vers SPEC-01 |
| cluster de coréférence | `Annotation.entity_id` | indispensable au rappel entity-level |
| attribut confidentiel | `Annotation.confidential = true` | orthogonal à `identifier_type` |
| annotateur | `Annotation.annotator_id` | conservé pour l'agrégation |

**Décision d'agrégation des annotateurs** (à figer avant les premières
mesures) : par défaut, **union** des annotations pour le calcul du rappel
(logique privacy-first : tout ce qu'un annotateur a jugé identifiant l'est), et
**intersection** pour la précision. Toute mesure publiée doit préciser la règle
utilisée.

## 11. Splits et protocole

- Utiliser les splits officiels train/dev/test de TAB. Ne pas resplitter.
- Protocole `official` conditionné à : 1 268 documents observés, checksum
  conforme, règle d'agrégation déclarée.
- Métriques calculées avec l'implémentation officielle du papier lorsque
  disponible (reprendre `eval/core/tab_official.py` de la V1), sinon marquer
  `MetricStatus.PROXY`.

## 12. Plan d'implémentation de l'adaptateur

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Lire `eval/core/tab_official.py` (V1) | note de format §4 |
| 2 | Télécharger + checksum | `data/raw/tab/` |
| 3 | Cartographier les types TAB → codes SPEC-01 | `configs/datasets/tab.yaml` |
| 4 | Implémenter `TabAdapter` avec gestion des coréférences | `src/anonymisation/datasets/tab.py` |
| 5 | Implémenter la règle d'agrégation multi-annotateurs (paramétrable) | `aggregation: union \| majority \| annotator:<id>` |
| 6 | Porter les 4 métriques officielles | `src/anonymisation/metrics/tab_official.py` |
| 7 | Vérifier la reproduction d'un score de référence du papier | rapport |

## 13. Critères d'acceptation

- [ ] 1 268 documents chargés.
- [ ] `text[start:end] == span_text` pour 100 % des annotations.
- [ ] Tous les types TAB sont mappés ; zéro étiquette inconnue.
- [ ] Les clusters de coréférence sont préservés et le rappel entity-level
      diffère du rappel span-level (preuve que la coréférence est bien prise en
      compte).
- [ ] Les trois modes d'agrégation produisent des scores différents et
      documentés.
- [ ] Reproduction d'au moins un score publié du papier à ±2 points.

## 14. Questions ouvertes

- Quelle version exacte du corpus et quelle licence ?
- Le code officiel des métriques est-il disponible et directement réutilisable ?
- Faut-il enrichir TAB d'une couche « combinaisons » annotée à la main sur un
  sous-échantillon, pour disposer d'une vérité QICR sur du texte réel ? (coût à
  évaluer — ce serait un apport publiable en soi)
