# MEDDOCAN

| | |
|---|---|
| **Clé interne** | `meddocan` |
| **Priorité** | P2 |
| **Benchmark** | B1 — volet généralisation cross-domaine |
| **Statut de la fiche** | Stable · v1.0 · 2026-08-30 |

---

## 1. Identité

| Champ | Valeur |
|-------|--------|
| Nom | MEDDOCAN — Medical Document Anonymization |
| Référence | [@marimon2019meddocan] — Zenodo `records/4279323` |
| Type | Cas cliniques annotés (gold standard) |
| Langue | **Espagnol** |
| Domaine | Clinique |

## 2. Rôle et priorité

**Un seul usage : le test de généralisation cross-domaine.** Rien d'autre.

Il permet de vérifier que le pipeline :

- ne dépend pas du domaine RH ;
- détecte des formes linguistiques différentes ;
- reste stable en espagnol ;
- fonctionne sur du texte sensible à **forte densité d'informations
  personnelles** — profil très différent d'un ticket support ou d'un message de
  forum.

Ce dernier point est le plus utile : un texte clinique est saturé de PII et de
QI, ce qui teste le comportement du système en régime de charge maximale.

Classé **P2** : le projet reste valide sans lui.

## 3. Contenu et volumétrie

| | |
|---|---|
| Documents | ~1 000 cas cliniques |
| Annotations | Gold standard, ~29 types de PHI |
| Splits | train / dev / test officiels |
| Taille disque | < 100 Mo |

## 4. Structure brute

Format **BRAT** (fichiers `.txt` + `.ann`) et/ou XML i2b2-like, selon les
distributions.

Le format BRAT donne directement des offsets caractères — donc **pas de
conversion BIO** ici, contrairement à JobStack et MultiCoNER. C'est le plus
simple à ingérer de la batterie.

## 5. Accès et acquisition

| | |
|---|---|
| Source | Zenodo `https://zenodo.org/records/4279323` |
| Méthode | Téléchargement direct, `scripts/download_meddocan.py` |
| Prérequis | Aucun |
| Cache local | `data/raw/meddocan/` |

## 6. Licence et conformité

- Licence Creative Commons via Zenodo (version exacte à relever).
- Les cas cliniques MEDDOCAN sont **déjà anonymisés / synthétisés** par les
  organisateurs : les identifiants présents sont des substituts, pas des données
  de patients réels. À **confirmer** avant usage, car c'est ce qui autorise le
  traitement.
- Malgré cela : ne pas versionner (règle `.gitignore` `**/*meddocan*/`), par
  cohérence avec le traitement de toutes les données cliniques.

## 7. Couverture

| Besoin | Couvert |
|--------|:-------:|
| Identifiants directs | ✅ (très dense) |
| QI indirects | ◐ |
| QI implicites | ❌ |
| Combinaisons | ❌ |
| Population de référence | ❌ |
| Multilingue | ❌ (**espagnol seul**) |
| Domaine du projet | ❌ |
| Texte réel | ✅ |

## 8. Apport pour le projet

1. **Preuve de non-dépendance au domaine.** Un système qui ne fonctionne que sur
   RH/support/forums serait fragile en review. MEDDOCAN fournit un contre-test
   bon marché.
2. **Espagnol** — une langue du périmètre multilingue élargi, sur du texte réel.
3. **Régime de densité maximale** — teste la robustesse quand presque chaque
   phrase contient un identifiant, cas où les systèmes à seuil se dégradent.
4. **Comparabilité externe** : de nombreux systèmes publient des scores
   MEDDOCAN, ce qui donne un point de calibrage de la qualité du détecteur.

## 9. Limites et pièges

| Limite | Conséquence |
|--------|-------------|
| Hors domaine total | Aucun résultat MEDDOCAN ne dit quoi que ce soit sur le RH ou le support. |
| PHI ≠ QI | La taxonomie MEDDOCAN est une taxonomie de PHI réglementaire (proche HIPAA), pas une taxonomie de risque combinatoire. |
| Espagnol seul | Ne renseigne pas sur le français. |
| Déjà anonymisé | Les identifiants sont des substituts, potentiellement plus réguliers que les vrais → F1 surestimé. |

> **Piège** : publier un bon score MEDDOCAN comme preuve de qualité générale du
> système. C'est un test de non-régression cross-domaine, rien de plus.
> Métriques marquées `DIAGNOSTIC`.

## 10. Mapping vers le schéma interne

| Objet MEDDOCAN | Objet interne | Notes |
|----------------|---------------|-------|
| fichier `.txt` | `Document` | `domain = "clinical"`, `language = "es"` |
| annotation `.ann` (BRAT) | `Annotation` | offsets caractères directs |
| type PHI (~29) | `Annotation.qi_category` | mapping vers SPEC-01 ; la plupart en `DIRECT`, quelques-uns en `QUASI` (profession, territoire, âge > 89) |

## 11. Splits et protocole

- Splits officiels train/dev/test.
- Protocole `diagnostic` uniquement.
- À exécuter **une fois par version majeure du détecteur**, pas à chaque
  itération — c'est un test de garde-fou, pas un signal de développement.

## 12. Plan d'implémentation

| # | Étape | Sortie |
|---|-------|--------|
| 1 | Télécharger depuis Zenodo + checksum | `data/raw/meddocan/` |
| 2 | Écrire un parseur BRAT générique (réutilisable) | `src/anonymisation/datasets/_brat.py` |
| 3 | Mapper les ~29 types PHI | `configs/datasets/meddocan.yaml` |
| 4 | `MeddocanAdapter` | `src/anonymisation/datasets/meddocan.py` |
| 5 | Intégrer au test de garde-fou cross-domaine | suite `crossdomain` |

Le parseur BRAT de l'étape 2 est un investissement rentable : c'est le format
d'annotation le plus courant si le projet ouvre un jour une campagne
d'annotation manuelle sur HR-QI-Bench.

## 13. Critères d'acceptation

- [ ] Parseur BRAT validé : `text[start:end] == span_text` sur 100 % des
      annotations.
- [ ] Les ~29 types sont mappés, aucun inconnu.
- [ ] Le score obtenu est situé par rapport aux scores publiés de la campagne
      (ordre de grandeur cohérent).
- [ ] Les métriques sont marquées `DIAGNOSTIC` et n'entrent pas dans le score
      principal.

## 14. Questions ouvertes

- Les données sont-elles réellement synthétiques / anonymisées ? À confirmer
  avant de retirer la restriction `.gitignore`.
- Vaut-il la peine d'ajouter un second corpus clinique en français (par exemple
  DEFT / CAS) pour tester la densité maximale **en français** ? → piste à
  évaluer en lot L5, pas avant.
