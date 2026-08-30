# Support-QI-Bench — corpus tickets support à construire

| | |
|---|---|
| **Clé interne** | `support_qi` |
| **Priorité** | **P0** |
| **Benchmark** | B2, B3, B4 |
| **Statut** | **À construire** · fiche v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom | Indirect-QI Re-identification Benchmark — volet support |
| Origine | Production propre au projet |
| Type | Synthétique à profil latent, ou dé-identifié depuis des tickets réels |
| Langues | FR (primaire), EN (secondaire) |
| Domaine | Support / helpdesk — tickets, échanges avec un service technique |

## 2. Rôle et priorité

Le domaine support est, avec le RH, **le plus faiblement benchmarké** de la
littérature. Il présente pourtant une particularité qui le rend
scientifiquement intéressant : ses quasi-identifiants sont **techniques et
temporels**, pas démographiques.

Un ticket support ne dit pas « j'ai 28 ans ». Il dit :

> « depuis la mise à jour 4.2.1 sur Windows Server 2022, la synchro plante tous
> les matins vers 7 h chez nous, on est le seul site à utiliser le connecteur
> Oracle »

Aucune PII. Et pourtant : produit × version × OS × horaire × configuration rare
× organisation → classe d'équivalence potentiellement de taille 1.

C'est un cas que **aucun dataset existant ne couvre**, et c'est probablement
l'exemple le plus convaincant à mettre en avant dans une publication.

## 3. Contenu cible

| | Cible |
|---|---|
| Profils latents (utilisateur × organisation) | **600** |
| Tickets | **3 000** |
| Langue | 70 % FR, 30 % EN |
| Population de référence | Parc client synthétique (organisations × produits × configurations) |

### Types de documents

| Type | Part cible |
|------|-----------:|
| Ticket initial d'incident | 45 % |
| Échange de suivi (relance, précision technique) | 30 % |
| Demande de changement / configuration | 15 % |
| Retour post-résolution | 10 % |

## 4. Quasi-identifiants du domaine support

Codes détaillés dans [SPEC-01](../specifications/SPEC-01-taxonomie-qi.md), bloc support :

produit · version · OS · type de terminal · localisation · fuseau horaire ·
horaire d'incident · rôle utilisateur · environnement technique ·
**combinaison produit × version × organisation × heure**.

Spécificités par rapport au bloc RH :

| Particularité | Conséquence technique |
|---------------|----------------------|
| **QI temporels** (horaire d'incident, fuseau) | Le risque dépend du **moment**, pas seulement du contenu. Le moteur de risque doit accepter des attributs temporels. |
| **QI de configuration rare** | Une version obsolète ou un connecteur peu déployé est un QI très fort. Le k dépend d'un **parc**, pas d'une population humaine. |
| **QI organisationnels** | La cible peut être une **organisation**, pas une personne. Modèle de risque à deux niveaux. |
| **Cumul par thread** | Un ticket seul est anodin ; le fil complet ne l'est pas. |

> **Conséquence pour SPEC-06** : la population de référence du support n'est pas
> démographique mais **un parc installé**. Le formalisme reste identique
> ($k = |EC_P(Q)|$), seule la nature de $P$ change. C'est un bon test de la
> généralité du moteur.

## 5. Structure exigée

Profil latent à deux niveaux :

```text
ORG_ID        = O0231
org_size      = 400-600
org_sector    = manufacturing
org_country   = FR
org_sites     = 3

PERSON_ID     = P01742
org           = O0231
support_role  = administrator
product       = X
version       = 4.2.1
os            = Windows Server 2022
timezone      = Europe/Paris
environment   = on-premise + connecteur Oracle
```

puis plusieurs tickets rattachés au même couple (personne, organisation).

## 6. Voies de construction

Identiques au corpus RH ([`hr-qi-bench.md §6`](hr-qi-bench.md)) : voie A
synthétique recommandée, voie B (tickets réels dé-identifiés) en validation
externe sous contrainte RGPD.

**Particularité support** : les tickets réels sont souvent plus faciles à
obtenir en interne que les données RH (moins sensibles au sens RGPD), mais ils
contiennent des **secrets d'affaires** (noms de clients, architectures). La
contrainte n'est pas la même mais elle existe.

## 7. Population de référence — le parc

| Dimension | Source |
|-----------|--------|
| Distribution des versions déployées | Télémétrie produit, ou modèle synthétique de cycle de vie des versions |
| Distribution des OS | Parts de marché sectorielles |
| Distribution des tailles d'organisation | INSEE / bases sectorielles |
| Distribution des configurations | Modèle synthétique, avec une **queue longue** explicite |

La **queue longue est le cœur du problème** : c'est là que $k = 1$. Le parc
synthétique doit la modéliser explicitement (loi de puissance sur les
configurations), sinon le benchmark ne contiendra que des cas faciles.

## 8. Tâches d'utilité associées

| Tâche | Étiquette |
|-------|-----------|
| Classification de ticket | catégorie |
| **Routage** | équipe destinataire |
| Détection de priorité | P1..P4 |
| Prédiction d'intention | intention |
| Suggestion de résolution | article de base de connaissances |

Le routage est la tâche de référence : c'est celle qui a le plus de valeur
industrielle et qui souffre le plus d'une anonymisation agressive (masquer le
produit et la version détruit le routage). C'est donc **le meilleur révélateur
du compromis privacy-utility** de toute la batterie.

> Exemple de résultat cible : routage F1 = 0.91 → 0.88 après anonymisation →
> `UtilityRetention` = 96.7 %.

## 9. Couverture visée

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs | ✅ |
| QI indirects **techniques** | ✅ (unique dans la batterie) |
| QI **temporels** | ✅ (unique) |
| QI implicites | ✅ |
| Combinaisons annotées | ✅ |
| Profil latent à deux niveaux (personne + organisation) | ✅ |
| Population de référence (parc) | ✅ |
| Français | ✅ |
| Tâches d'utilité | ✅ |

## 10. Mapping vers le schéma interne

Produit directement au format SPEC-02, avec deux extensions :

- `Profile.org_id` — rattachement organisationnel ;
- `organizations.jsonl` — nouvelle table, profil latent d'organisation ;
- `Annotation.qi_category` peut porter des codes du bloc support (`SUP_*`) ;
- `Combination.target_type` ∈ {`person`, `organization`} — le risque est calculé
  sur l'une ou l'autre cible.

Ce dernier point est une **exigence à répercuter dans SPEC-02 et SPEC-06** :
le moteur de risque doit être paramétré par le type de cible.

## 11. Splits et protocole

- Split **par `org_id`**, pas seulement par `person_id` — sinon fuite via
  l'organisation (plusieurs personnes d'une même organisation partagent produit,
  version, configuration).
- Axe `difficulty` explicite.
- Évaluation à trois granularités : ticket · thread · organisation.

## 12. Plan de construction

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Modéliser le parc (organisations, produits, versions, configurations, queue longue) | `configs/populations/support-parc.yaml` |
| 2 | Échantillonner 200 organisations et 600 utilisateurs | `organizations.jsonl`, `profiles.jsonl` |
| 3 | Calculer `k_true` par combinaison, pour les deux types de cible | `combinations.jsonl` |
| 4 | Générer les tickets (3 modes d'expression, FR/EN) | `documents.jsonl` |
| 5 | Dériver les annotations du plan de génération | `annotations.jsonl` |
| 6 | Produire les étiquettes d'utilité (routage en priorité) | `tasks.jsonl` |
| 7 | Contrôle humain 5 % + revue de plausibilité technique | rapport |
| 8 | Geler version et checksum | `configs/datasets/support_qi.yaml` |

## 13. Critères d'acceptation

- [ ] 600 profils rattachés à ~200 organisations, 3 000 tickets.
- [ ] La distribution des configurations présente une queue longue vérifiable
      (au moins 10 % des organisations ont une configuration de $k \leq 3$).
- [ ] `k_true` calculable pour les deux types de cible.
- [ ] Aucun `org_id` présent dans deux splits.
- [ ] Un classifieur de routage entraîné sur le texte original atteint un F1 de
      référence ≥ 0.85 (sinon la tâche d'utilité est trop bruitée pour mesurer
      quoi que ce soit).
- [ ] L'évaluation thread-level détecte plus de QI que l'évaluation
      ticket-level.

## 14. Questions ouvertes

- Le produit modélisé doit-il être fictif, ou faut-il s'appuyer sur un logiciel
  réel pour le réalisme ? (fictif recommandé : évite tout problème de marque et
  de secret d'affaires)
- Comment modéliser réalistement la queue longue des configurations sans
  télémétrie réelle ?
- Le risque organisationnel entre-t-il dans le périmètre RGPD ? (non au sens
  strict, mais il relève du secret d'affaires — à traiter comme une exigence
  distincte)
- Faut-il intégrer des pièces jointes / logs, qui sont en pratique la première
  source de fuite dans les tickets réels ?
