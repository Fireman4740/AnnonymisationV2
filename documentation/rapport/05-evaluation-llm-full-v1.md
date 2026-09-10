# 05 — Évaluation de `llm-full-v1` (première campagne)

| | |
|---|---|
| **Statut** | Diagnostic — échantillons de 15 documents, non publiable en l'état |
| **Date** | 2026-09-09 |
| **Système** | `llm-full-v1` ([src/anonymisation/pipelines/llm_full/](../../src/anonymisation/pipelines/llm_full/)) |
| **Backend** | `qwen_local` — vLLM Qwen3.8-27B (W4A16), local, `enable_thinking=false` |
| **Baseline** | `regex-only-v1` |

---

## 1. Ce qui a été construit

Un système enregistré (`anonv2 systems list`) qui fait **toute** la tâche
d'anonymisation en un seul appel LLM par document : détection des
identifiants directs et quasi-identifiants, choix de l'action
(SUPPRESS/PSEUDONYMIZE/GENERALIZE), texte de remplacement.

Ce que le code garde pour lui, jamais confié au modèle :

- **localisation des offsets** — recherche exacte du span renvoyé dans le
  texte original (jamais d'offset inventé par le LLM) ;
- **légalité de l'action** — validée contre `ALLOWED_ACTIONS` (SPEC-01 §8) ;
  une action illégale ou un remplacement vide replient sur `SUPPRESS`,
  journalisé, jamais silencieux ;
- **application au texte** — la même fonction `apply_decisions` que les
  systèmes déterministes.

Infrastructure ajoutée : `anonymisation.llm` (client openai-compatible, cache
disque obligatoire indexé par sha256(backend+modèle+prompt+params), erreurs
nommées jamais confondues avec « aucune entité » — contrainte C3 de SPEC-10),
profil `pipelines/llm_full/profile.yaml`, backend `qwen_local` déjà déclaré dans
`configs/llm/backends.yaml`.

**Organisation** : chaque pipeline est un dossier autonome
(`src/anonymisation/pipelines/<nom>/` : code, profil, tests, notice) — voir
[la carte des pipelines](../../src/anonymisation/pipelines/README.md) et le
[guide de création](../guides/creer-un-pipeline.md). Ajouter une architecture
ou une config ne touche qu'un seul fichier partagé.

## 2. Protocole de cette campagne

Trois corpus ingérés, 15 documents chacun (`--limit 15`), comparés à la
baseline `regex-only-v1` (motifs déclaratifs, aucun QI, aucune couche
sémantique) :

| Corpus | Split | Nature |
|--------|-------|--------|
| `openpii` | validation | PII synthétique multilingue (FR) |
| `tab` | test | Jugements CEDH réels, anglais, longs |
| `quasifr` | hard_quasi_id | QI combinatoires difficiles, français — le cas visé par le projet |

Commandes (reproductibles) :

```bash
anonv2 predict --dataset <ds> --split <split> --system llm-full \
  --profile llm_full --limit 15 --param backend=qwen_local --out runs/eval-llm-<ds>
anonv2 predict --dataset <ds> --split <split> --system regex-only \
  --profile deterministic --limit 15 --out runs/eval-regex-<ds>
anonv2 score --run runs/eval-<sys>-<ds> --protocol <protocole-du-manifeste>
anonv2 compare --runs runs/eval-regex-<ds> runs/eval-llm-<ds> --out runs/compare-<ds>.md
```

## 3. Résultats

Toutes les valeurs portent `PROXY`/`DIAGNOSTIC` (échantillon de 15, adversaire
`exact-match`/TF-IDF) : elles ne sont **pas** publiables comme métriques
officielles, seulement comparables entre les deux runs de cette campagne.

| Corpus | Système | CPR ↑ | IPR ↑ | Leak direct ↓ | Leak global (incl. QI) ↓ | ER_direct ↑ | ER_quasi ↑ | Latence p50 | Erreur |
|--------|---------|------:|------:|---------------:|--------------------------:|------------:|-----------:|-------------:|-------:|
| openpii | llm-full | **0.956** | **0.953** | **0.000** | **0.044** (2/45) | 0.967 | **0.667** | 1.49 s | 0 % |
| openpii | regex-only | 0.156 | 0.172 | 0.767 | 0.844 (38/45) | 0.200 | 0.000 | 0 ms | 0 % |
| tab | llm-full | **0.813** | **0.813** | **0.000** | **0.188** (3/16) | 1.000 | **0.462** | 10.0 s | **6.7 %** |
| tab | regex-only | 0.000 | 0.000 | 1.000 | 1.000 (16/16) | 0.000 | 0.000 | 0 ms | 0 % |
| quasifr (dur) | llm-full | **0.978** | **0.983** | — (0 span direct) | **0.022** (1/46) | — | **0.587** | 2.03 s | 0 % |
| quasifr (dur) | regex-only | 0.000 | 0.000 | — (0 span direct) | 1.000 (46/46) | — | 0.000 | 0 ms | 0 % |

CPR/IPR = *Collective/Individual Protection Rate* (SPEC-07 §5, 1 = protection
totale). ER_quasi = rappel entity-level sur les quasi-identifiants. « Leak
direct » = fraction des identifiants directs gold encore retrouvables
verbatim dans le texte anonymisé ; « Leak global » inclut aussi les
quasi-identifiants gold (c'est la colonne la plus parlante pour ce projet,
puisque `regex-only` ne touche jamais aux QI par construction).

## 4. Lecture honnête des résultats

**Le signal attendu est net et confirmé.** `llm-full-v1` protège 5 à 6 fois
mieux que `regex-only-v1` sur CPR/IPR dans les trois corpus, parce qu'il est
le seul système du dépôt qui touche aux quasi-identifiants (ER_quasi
0.46–0.67 contre 0.00 pour regex-only, qui ne détecte que des motifs PII
explicites). Sur `quasifr/hard_quasi_id` — le cas de figure central du
cadrage du projet (« *je suis le seul doctorant de mon équipe…* ») —
`regex-only` protège **0 %** des combinaisons, `llm-full` **97,8 %** (CPR).
C'est exactement l'écart que la revue de littérature
([02-etat-de-l-art §7](02-etat-de-l-art.md#7-openpii--ai4privacy)) prédisait
entre un détecteur PII classique et un système capable de raisonner sur les QI.

**Trois limites réelles, découvertes par cette campagne, pas supposées :**

1. **Documents longs → réponse tronquée.** Sur `tab` (jugements CEDH, souvent
   > 10 000 caractères), 1 document sur 15 a produit un JSON tronqué
   (`Unterminated string`), classé `error` par construction (contrainte C3/C4
   de SPEC-10 : jamais confondu avec « 0 entité »). Le run est donc
   **automatiquement refusé par le contrôle qualité intégré** (`AVERTISSEMENT
   BLOQUANT : taux d'erreur 6.67% > seuil de 5%`). Un appel unique JSON pour
   un document entier ne passe pas à l'échelle des textes longs — une
   architecture à découper en chunks ou à faire dialoguer sur des extraits est
   nécessaire pour ce régime (piste pour une seconde architecture, voir §5).
2. **Le modèle propose parfois des actions hors périmètre.** Sur plusieurs
   documents `tab`, le modèle a proposé `PSEUDONYMIZE` pour un
   quasi-identifiant (`SUP_ORG`), action réservée aux identifiants directs
   par SPEC-01 §8. Le garde-fou de validation a correctement replié sur
   `SUPPRESS` à chaque fois — la légalité de l'action ne doit **pas** être
   confiée au LLM, ce que la conception avait anticipé et que cette campagne
   confirme empiriquement.
3. **TRIR sature à 1.0 pour les deux systèmes.** L'attaquant TF-IDF-centroïde
   utilisé par le protocole `score` ré-identifie 100 % des documents dans les
   deux runs, y compris `llm-full`. À `n=15` candidats et avec un adversaire
   volontairement faible (pas de LLM adversaire), c'est attendu et **ne
   contredit pas** CPR/IPR : TRIR mesure une discrimination entre documents
   d'un même petit lot, pas l'absence de fuite d'attribut. Ne pas
   sur-interpréter ce chiffre sans un attaquant LLM et un pool candidat plus
   large (SPEC-08).

## 5. Ce que cette campagne ne montre pas encore

- **Aucune mesure d'utilité métier** (`utility_retention` est `unavailable`
  faute de tâche downstream déclarée sur ces corpus) — seul un proxy textuel
  (ROUGE-L) est disponible, et il n'est pas la métrique principale du projet
  (SPEC-07 §5, avertissement explicite contre son usage comme utilité
  première).
- **`n=15`** : trop petit pour publier un intervalle de confiance. Un run
  complet (`--limit` omis) est le prochain pas naturel, en isolant d'abord
  `tab` derrière une architecture qui gère les documents longs.
- **Un seul backend testé** (`qwen_local`). Comparer à `sonnet` (attaquant B
  de SPEC-08, backend distant — réservé aux corpus `structure.synthetic:
  true`) donnerait une borne de qualité.

## 6. Prochaine étape recommandée

1. Architecture n°2 dans son propre dossier `pipelines/llm_windowed/` :
   découpage par fenêtre glissante pour les documents longs (résout la limite 1
   de ce rapport), avec son `profile.yaml` et ses tests.
2. Lever `--limit` sur `openpii` et `quasifr` (`tab` après l'architecture
   n°2) pour une campagne au statut `sampled` puis `official`.
3. Brancher un attaquant réel (SPEC-08, niveau A) à la place du TF-IDF-centroïde
   pour un TRIR discriminant.
