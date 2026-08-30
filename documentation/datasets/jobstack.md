# JobStack

| | |
|---|---|
| **Clé interne** | `jobstack` |
| **Priorité** | P1 |
| **Benchmark** | B1 (PII Detection) |
| **Statut de la fiche** | Stable · v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom | JobStack — De-identification of Privacy-related Entities in Job Postings |
| Référence | [@jensen2021jobstack] — arXiv `2105.11223`, NoDaLiDa 2021 |
| Type | Texte réel |
| Langue | Anglais |
| Domaine | **RH** — offres d'emploi |

## 2. Rôle et priorité

Le seul corpus **réel** et **public** du domaine RH de la batterie. Il traite la
désidentification dans les offres d'emploi : détection d'informations privées
telles que noms et coordonnées de contact.

Classé **P1** et non P0 pour une raison précise : il couvre la PII **explicite**
RH, pas le risque combinatoire. Il n'est pas un benchmark de

$$
\text{emploi} + \text{ancienneté} + \text{localisation} + \text{trajectoire} \rightarrow k
$$

Utile pour la première passe (B1), pas pour la métrique finale.

## 3. Contenu et volumétrie

Volumétrie exacte à confirmer à l'acquisition. Le corpus est constitué d'offres
d'emploi annotées en entités liées à la vie privée (noms de personnes,
organisations, coordonnées, lieux, professions).

## 4. Structure brute

Format de type CoNLL / BIO, annotations au niveau token. À confirmer.

Point de vigilance : le passage d'annotations **token BIO** à des **spans
caractères** est une source classique d'erreurs d'offsets. L'adaptateur doit
reconstruire les offsets caractères et les valider
(`text[start:end] == span_text`).

## 5. Accès et acquisition

| | |
|---|---|
| Source | Auteurs (ITU Copenhague / IT University) |
| Méthode | **Demande d'accès aux auteurs** |
| Prérequis | Accord des auteurs, délai à prévoir |
| Cache local | `data/raw/jobstack/` |

Comme pour MIMIC-III, le délai est administratif. Si le corpus est jugé utile,
lancer la demande tôt — mais il n'est pas bloquant pour le projet.

## 6. Licence et conformité

- Accès restreint, sur demande. Redistribution **interdite** sans accord.
- Les offres d'emploi sont des documents publiés, mais elles contiennent des
  coordonnées de personnes **réelles** (recruteurs). Ne jamais publier
  d'exemple ré-identifié.
- Champ `license` du manifeste : `restricted-on-request`.

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs | ✅ |
| QI indirects | ❌ |
| QI implicites | ❌ |
| Combinaisons | ❌ |
| Profil latent | ❌ |
| Population de référence | ❌ |
| Multilingue | ❌ (anglais) |
| **Domaine RH** | ✅ |
| **Texte réel** | ✅ |

## 8. Apport pour le projet

1. **Ancrage réel du domaine RH** : sans lui, tous les résultats RH du projet
   sont synthétiques. Même limité à la PII explicite, il fournit une preuve que
   le détecteur fonctionne sur du texte RH authentique.
2. **Contrôle de sur-ajustement** : un détecteur entraîné sur OpenPII (RH
   synthétique inexistant) et HR-QI-Bench (synthétique) doit être testé sur du
   réel. JobStack est le seul candidat.
3. Diagnostic du **transfert de domaine** : écart entre F1 OpenPII et F1
   JobStack = coût du changement de domaine sur la couche PII.

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| PII explicite seulement | Aucune mesure de QI, QICR, k ou risque. |
| Offres d'emploi ≠ demandes RH | Le registre est institutionnel, pas personnel. Les QI d'un candidat n'y figurent pas. |
| Anglais | Aucune mesure FR. |
| Accès sur demande | Non reproductible par un tiers sans la même démarche → métriques marquées `SAMPLED` ou `DIAGNOSTIC`. |

> **Le piège principal** : présenter JobStack comme « le benchmark RH » du
> projet. Ce serait faux et attaquable en review. C'est un benchmark de
> désidentification d'offres d'emploi.

## 10. Mapping vers le schéma interne

| Objet JobStack | Objet interne | Notes |
|----------------|---------------|-------|
| offre d'emploi | `Document` | `domain = "hr"`, `language = "en"`, `meta.subdomain = "job_posting"` |
| entité BIO | `Annotation` | conversion token → caractères obligatoire et validée |
| type d'entité | `Annotation.qi_category` | via `label_map` ; les types `PROFESSION`, `LOCATION`, `ORGANIZATION` doivent être mappés en `QUASI`, pas en `DIRECT` |

## 11. Splits et protocole

- Splits officiels des auteurs.
- Protocole `diagnostic` par défaut (accès restreint → non reproductible).

## 12. Plan d'implémentation

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Demander l'accès aux auteurs | accord |
| 2 | Inspecter le format, documenter | §4 |
| 3 | Implémenter la conversion BIO → spans caractères, avec validation stricte | `src/anonymisation/datasets/_bio.py` (réutilisable pour MultiCoNER) |
| 4 | `label_map` avec décision explicite DIRECT/QUASI par type | `configs/datasets/jobstack.yaml` |
| 5 | `JobStackAdapter` | `src/anonymisation/datasets/jobstack.py` |
| 6 | Mesurer l'écart de F1 avec OpenPII (transfert de domaine) | rapport |

L'utilitaire BIO de l'étape 3 est mutualisé avec MultiCoNER II et MEDDOCAN :
l'écrire proprement une fois.

## 13. Critères d'acceptation

- [ ] `text[start:end] == span_text` pour 100 % des spans reconstruits.
- [ ] Aucun type d'entité non mappé.
- [ ] Les types non identifiants directs sont bien classés `QUASI`.
- [ ] Le F1 obtenu est comparé à celui d'OpenPII, l'écart est documenté.
- [ ] Aucune donnée versionnée.

## 14. Questions ouvertes

- L'accès est-il toujours accordé en 2026 ?
- Le corpus vaut-il le coût administratif, au vu de son apport limité ?
  → **Recommandation** : lancer la demande (coût nul), mais ne pas bloquer le
  projet dessus. Si l'accès n'arrive pas, le manque est acceptable et doit être
  déclaré comme limite dans la publication.
