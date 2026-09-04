# Spécifications techniques — index

| | |
|---|---|
| **Statut** | Stable |
| **Version** | 1.0 |
| **Date** | 2026-08-30 |

Ces neuf spécifications définissent ce que le code doit faire. Elles sont
normatives : le code s'y conforme, et une divergence est un défaut à trancher
explicitement, jamais à ignorer.

---

## 1. Ordre de lecture

```
SPEC-01  Taxonomie QI            ─┐
                                  ├─→  SPEC-02  Schéma de données  ─┐
SPEC-06  Population et risque    ─┘                                 │
                                                                    ├─→ SPEC-03 Registre & adaptateurs
                                                                    │        │
                                                                    │        ▼
                                                                    │   SPEC-04 Pipeline d'ingestion
                                                                    │        │
                                                     SPEC-05 Génération corpus internes
                                                                             │
                                                     SPEC-07 Métriques  ─────┤
                                                                             ▼
                                                     SPEC-08 Attaquants
                                                                             │
                                                     SPEC-09 Qualité, licences, CI
```

**Pour démarrer l'implémentation des datasets** : SPEC-01 → SPEC-02 → SPEC-03 →
SPEC-04. Les cinq autres peuvent attendre le lot suivant.

## 2. Liste

| Spec | Titre | Statut | Ce qu'elle fixe |
|------|-------|--------|-----------------|
| [SPEC-01](SPEC-01-taxonomie-qi.md) | Taxonomie unifiée des quasi-identifiants | Gelé | Les codes de catégories QI, les axes d'annotation, les règles de combinaison |
| [SPEC-02](SPEC-02-schema-donnees.md) | Schéma de données interne | Stable | Les six tables JSONL, leurs champs, leurs invariants |
| [SPEC-03](SPEC-03-registre-et-adaptateurs.md) | Registre et contrat d'adaptateur | Stable | L'interface `DatasetAdapter`, le manifeste YAML, le registre |
| [SPEC-04](SPEC-04-pipeline-ingestion.md) | Pipeline d'ingestion | Stable | Acquisition → normalisation → validation → cache, et les codes d'erreur |
| [SPEC-05](SPEC-05-generation-corpus-synthetiques.md) | Génération des corpus internes | Brouillon | Le protocole profil latent → texte → annotation dérivée |
| [SPEC-06](SPEC-06-population-et-risque.md) | Populations de référence et risque | Brouillon | Le k combinatoire, les modèles de risque, les populations |
| [SPEC-07](SPEC-07-metriques.md) | Métriques | Stable | Les 5 niveaux, formules, statuts, format de rapport |
| [SPEC-08](SPEC-08-attaquants.md) | Modèles d'attaquants | Brouillon | Les niveaux A/B/C, le protocole d'attaque, les garde-fous éthiques |
| [SPEC-09](SPEC-09-qualite-licences-ci.md) | Qualité, licences, CI | Stable | Les contrôles automatiques, la conformité, la chaîne d'intégration |

## 3. Conventions normatives

Le vocabulaire suit RFC 2119, en français :

- **DOIT / NE DOIT PAS** — obligation absolue. Une violation est un bug bloquant.
- **DEVRAIT / NE DEVRAIT PAS** — recommandation forte ; toute dérogation doit
  être motivée par écrit dans le code ou le manifeste.
- **PEUT** — facultatif.

## 4. Cycle de vie d'une spécification

| Statut | Signification |
|--------|---------------|
| `Brouillon` | En cours d'écriture. Le code peut la précéder. |
| `Stable` | Normative. Le code doit s'y conformer. Modification = incrément de version + journal. |
| `Gelé` | Ne change plus pendant la campagne d'expériences en cours (garantit la reproductibilité des résultats publiés). |
| `Obsolète` | Remplacée ; conserve un lien vers la spec successeur. |

Chaque spec porte un en-tête avec `Statut`, `Version`, `Date`, et une section
finale « Journal des modifications ».

## 5. Règle d'or

> **Aucune valeur par défaut silencieuse.**

Si une étiquette source n'est pas mappée, si une licence est inconnue, si une
volumétrie ne correspond pas au manifeste, si un offset ne retombe pas sur le
texte — le système **échoue bruyamment**. Il ne devine pas.

C'est la règle qui protège la validité de toutes les mesures publiées, et elle
prime sur la commodité de développement.
