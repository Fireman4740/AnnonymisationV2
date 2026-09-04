# SPEC-01 — Taxonomie unifiée des quasi-identifiants

| | |
|---|---|
| **Statut** | Gelé |
| **Version** | 1.1 |
| **Date** | 2026-09-04 |
| **Dépend de** | — |
| **Utilisée par** | SPEC-02, SPEC-03, SPEC-06, SPEC-07 |

---

## 1. Objet

Cette spécification définit **le vocabulaire d'annotation unique** du projet :
les codes de catégories, les axes orthogonaux qui qualifient chaque annotation,
et les règles de combinaison.

Tout adaptateur de dataset DOIT mapper ses étiquettes source vers ces codes.
Aucune étiquette source ne DOIT rester non mappée.

## 2. Origine

La taxonomie dérive de trois sources, conformément à
[02-etat-de-l-art §5](../rapport/02-etat-de-l-art.md) :

| Source | Apport |
|--------|--------|
| TAB [@pilan2022tab] | Distinction identifiant direct / quasi-identifiant / attribut confidentiel, coréférence |
| IPI [@baroud2025ipi] | Les catégories d'identifiants indirects et la logique multi-adversaires |
| Domaines du projet | Blocs RH, support et forums, absents de la littérature |

> ✅ **Réconciliation effectuée (v1.1, 2026-09-04, ticket F-2)** : les 9 catégories
d'IPI ont été confrontées ligne à ligne au bloc générique — voir §9. La
décomposition en 13 codes `GEN_*` est confirmée ; les écarts restants (événements,
temps clinique) y sont documentés.

## 3. Structure : quatre axes orthogonaux

Une annotation n'est **pas** décrite par une seule étiquette. Elle porte quatre
attributs indépendants :

```
                     ┌─ identifier_type   : quel rôle dans l'identification ?
                     ├─ qi_category       : de quel attribut parle-t-on ?
Annotation ──────────┤
                     ├─ expression_mode   : comment est-ce dit ?
                     └─ sensitivity       : est-ce une donnée sensible au sens RGPD ?
```

Confondre ces axes est l'erreur de conception la plus courante dans les
schémas existants. Les séparer permet, par exemple, de mesurer séparément le
rappel sur les QI **implicites** (le cas difficile) sans changer de taxonomie.

### 3.1 Axe `identifier_type`

| Code | Définition | Exemple |
|------|------------|---------|
| `DIRECT` | Identifie une personne **seul**, sans autre information | « Jean Dupont », `jean@ex.fr`, n° de sécurité sociale |
| `QUASI` | N'identifie que **combiné** à d'autres attributs | « doctorant », « Lille », « moins de 30 ans » |
| `SENSITIVE_ONLY` | Sensible mais non identifiant (divulgation d'attribut) | « je suis en dépression », si aucun lien identitaire |
| `IGNORED` | Reconnu par la source, hors périmètre du projet | `Creative Work` de MultiCoNER |

`IGNORED` existe pour rendre tout mapping **total**. Une étiquette source hors
périmètre DOIT être mappée explicitement vers `IGNORED`, jamais omise.

### 3.2 Axe `expression_mode`

Repris de RAT-Bench [@krco2026ratbench], c'est l'axe de difficulté du projet.

| Code | Définition | Exemple |
|------|------------|---------|
| `EXPLICIT` | Formulation standard et directe | « j'ai 28 ans » |
| `NON_STANDARD` | Formulation inhabituelle, mais l'information est présente | « je suis né la même année que la chute du Mur » |
| `IMPLICIT` | L'information doit être **inférée**, elle n'est pas énoncée | « j'ai soutenu ma thèse l'an dernier » → doctorant, ~26–32 ans |

RAT-Bench rapporte un risque passant d'environ 44 % à 69 % entre régimes
standard et non standard, et conclut que l'implicite reste très difficile à
anonymiser. **Toute métrique du projet DOIT être déclinable selon cet axe.**

### 3.3 Axe `sensitivity`

Aligné sur l'article 9 du RGPD (catégories particulières de données).

| Code | Couvre |
|------|--------|
| `NONE` | Donnée ordinaire |
| `HEALTH` | Santé, handicap, traitement |
| `BELIEF` | Origine raciale ou ethnique, opinions politiques, convictions religieuses ou philosophiques |
| `UNION` | Appartenance syndicale |
| `SEXLIFE` | Vie sexuelle, orientation sexuelle |
| `BIOMETRIC` | Données biométriques, génétiques |
| `JUDICIAL` | Condamnations, infractions |

Cet axe est **orthogonal** à `identifier_type` : une donnée peut être sensible
sans être identifiante, et inversement. Il ne participe pas au calcul de $k$,
mais il PEUT être utilisé par la politique d'anonymisation pour durcir le seuil.

### 3.4 Axe `qi_category`

Le contenu du §4.

## 4. Les codes de catégorie

### 4.1 Bloc `DIR_*` — identifiants directs

| Code | Couvre |
|------|--------|
| `DIR_NAME` | Nom, prénom, surnom d'une personne physique |
| `DIR_EMAIL` | Adresse électronique |
| `DIR_PHONE` | Numéro de téléphone |
| `DIR_ADDRESS` | Adresse postale précise (niveau rue/numéro) |
| `DIR_ID_NUMBER` | Numéro national, passeport, permis, matricule salarié |
| `DIR_ACCOUNT` | Compte bancaire, carte, numéro client |
| `DIR_ONLINE_ID` | Pseudonyme, handle, URL de profil |
| `DIR_DEVICE_ID` | IP, MAC, identifiant d'appareil, cookie |
| `DIR_BIOMETRIC` | Empreinte, photo de visage, voix |
| `DIR_CASE_REF` | Numéro d'affaire, de dossier, de ticket nominatif |

### 4.2 Bloc `GEN_*` — quasi-identifiants génériques

| Code | Couvre | Exemple |
|------|--------|---------|
| `GEN_AGE` | Âge, date de naissance, tranche d'âge, génération | « moins de 30 ans » |
| `GEN_GENDER` | Genre, sexe | « en tant que femme ingénieure » |
| `GEN_GEO` | Localisation : pays, région, ville, quartier, lieu de travail | « Lille » |
| `GEN_DATE_EVENT` | Événement daté de la vie de la personne | « mon déménagement en mars » |
| `GEN_OCCUPATION` | Profession, métier, activité | « doctorant » |
| `GEN_EDUCATION` | Diplôme, niveau, établissement, discipline | « thèse en physique » |
| `GEN_AFFILIATION` | Organisation d'appartenance : employeur, école, association, club | « chez un équipementier automobile » |
| `GEN_FAMILY` | Situation familiale, composition du foyer, liens de parenté | « père de jumeaux » |
| `GEN_HEALTH_STATE` | État de santé, handicap, traitement | « arrêt maladie » |
| `GEN_SOCIOECON` | Revenu, statut socio-économique, logement, patrimoine | « je gagne autour du SMIC » |
| `GEN_ORIGIN_BELIEF` | Nationalité, origine, langue maternelle, religion, opinions | « je suis arrivé d'Espagne en 2015 » |
| `GEN_LIFESTYLE` | Pratique, loisir, appartenance rare ou distinctive | « je fais du curling en compétition » |
| `GEN_PHYSICAL` | Trait physique distinctif | « je mesure 2 m 05 » |

**13 codes.** Réconciliés avec les 9 catégories IPI en §9 (v1.1).

### 4.3 Bloc `HR_*` — quasi-identifiants du domaine RH

| Code | Couvre |
|------|--------|
| `HR_JOB_TITLE` | Intitulé de poste, fonction précise |
| `HR_SENIORITY` | Ancienneté, années d'expérience |
| `HR_HIERARCHY` | Niveau hiérarchique, encadrement, nombre de subordonnés |
| `HR_DEPARTMENT` | Service, équipe, direction |
| `HR_CONTRACT` | Type de contrat, temps de travail, statut |
| `HR_EMPLOYER_SIZE` | Taille de l'employeur, secteur |
| `HR_WORKSITE` | Site, établissement, localisation de travail |
| `HR_SALARY_BAND` | Rémunération, grille, prime |
| `HR_CAREER_EVENT` | Mobilité, promotion, litige, rupture, événement rare |
| `HR_ADMIN_PROCEDURE` | Démarche administrative en cours (arrêt, congé, formation, réclamation) |

`HR_ADMIN_PROCEDURE` mérite une note : dans l'exemple canonique du projet, c'est
le troisième terme de la combinaison `{âge<30, doctorant, arrêt maladie}`. Ce
n'est pas un attribut permanent de la personne, mais **il restreint la
population** au sous-ensemble de ceux qui ont fait cette démarche à ce moment —
donc il compte dans $k$.

### 4.4 Bloc `SUP_*` — quasi-identifiants du domaine support

| Code | Couvre |
|------|--------|
| `SUP_PRODUCT` | Produit, module, offre |
| `SUP_VERSION` | Version, build, niveau de correctif |
| `SUP_OS` | Système d'exploitation et version |
| `SUP_DEVICE` | Type de terminal, matériel |
| `SUP_ENVIRONMENT` | Architecture technique, connecteurs, intégrations, déploiement |
| `SUP_ROLE` | Rôle de l'utilisateur dans le système (admin, lecteur…) |
| `SUP_INCIDENT_TIME` | Horaire ou périodicité de l'incident |
| `SUP_TIMEZONE` | Fuseau horaire, plage d'activité |
| `SUP_ORG` | Organisation cliente, secteur, taille |
| `SUP_SCALE` | Volumétrie, nombre d'utilisateurs, nombre de sites |

### 4.5 Bloc `FOR_*` — quasi-identifiants du domaine forums

| Code | Couvre | Statut |
|------|--------|--------|
| `FOR_COMMUNITY` | Communauté, sous-forum, groupe d'appartenance | actif |
| `FOR_RELATION` | Mention d'une autre personne du forum, lien social | actif |
| `FOR_ACTIVITY_PATTERN` | Rythme de publication, horaires, ancienneté sur le forum | actif |
| `FOR_STYLE` | Signature stylométrique | **hors périmètre v1**, documenté comme limite connue |

### 4.6 Codes de service

| Code | Usage |
|------|-------|
| `OTHER_QI` | QI réel non couvert par un code existant. **Son usage déclenche une alerte** : plus de 1 % d'`OTHER_QI` sur un dataset signale une taxonomie incomplète. |
| `IGNORED` | Étiquette source hors périmètre. |

## 5. Métadonnées additionnelles par annotation

| Champ | Valeurs | Rôle |
|-------|---------|------|
| `granularity` | `EXACT` \| `RANGE` \| `COARSE` | « 28 ans » vs « moins de 30 ans » vs « jeune ». Détermine la force du QI et l'action de généralisation possible. |
| `stability` | `STABLE` \| `VOLATILE` | Une date de naissance est stable ; un poste actuel ne l'est pas. Un QI volatile perd sa valeur identifiante avec le temps. |
| `subject` | `SELF` \| `THIRD_PARTY` | La personne parle-t-elle d'elle ou d'autrui ? Un QI sur un tiers engage la protection **de ce tiers**. |
| `confidence` | [0,1] | Confiance de l'annotateur ou du détecteur. |

Le champ `subject` est souvent oublié et pose un vrai problème dans les tickets
support et les messages RH : « mon manager, qui gère 40 personnes sur le site de
Belfort » est un QI **sur le manager**, pas sur l'auteur.

## 6. Combinaisons de QI

### 6.1 Définition

Une **combinaison** est un ensemble non vide de valeurs de QI attribuées à un
même sujet, dans un même `scope`.

```
Combination = (target_type, target_id, scope, {(qi_category, value_normalized)}, k_true, risk_true)
```

| Champ | Valeurs |
|-------|---------|
| `target_type` | `person` \| `organization` |
| `scope` | `document` \| `thread` \| `author` |

Le `scope` est indispensable : la même personne peut être non identifiable dans
un message isolé et parfaitement identifiable dans l'union de ses messages.
Invariant attendu :

$$
k_{author} \leq k_{thread} \leq k_{document}
$$

### 6.2 Normalisation des valeurs

Pour calculer $k$, il faut comparer des valeurs, donc les normaliser :

| Catégorie | Forme normalisée |
|-----------|------------------|
| `GEN_AGE` | intervalle `[min, max]` en années |
| `GEN_GEO` | code géographique hiérarchique (`FR`, `FR-59`, `FR-59350`) |
| `GEN_OCCUPATION` | code d'une nomenclature (PCS-ESE pour la France, ESCO pour l'Europe) |
| `GEN_EDUCATION` | niveau CITE/ISCED + discipline |
| `HR_EMPLOYER_SIZE` | tranche d'effectifs |
| `SUP_VERSION` | version sémantique normalisée |
| `SUP_INCIDENT_TIME` | plage horaire + fuseau |

**Sans normalisation, pas de $k$.** Les tables de normalisation vivent dans
`configs/populations/` et sont partagées entre le moteur de risque et les
adaptateurs. Voir [SPEC-06](SPEC-06-population-et-risque.md).

### 6.3 Combinaison « à risque »

Une combinaison est dite **à risque** si $k_{true} \leq k_{seuil}$, avec
$k_{seuil}$ paramétrable (défaut : 10, correspondant à un risque prosecutor de
10 %). C'est cette définition qui alimente le dénominateur de **QICR**
([SPEC-07 §2](SPEC-07-metriques.md)).

## 7. Règles d'annotation

1. Un span PEUT porter **plusieurs** `qi_category` (multi-label). Exemple :
   « je suis infirmière au CHU de Lille » porte `GEN_OCCUPATION`,
   `GEN_AFFILIATION` et `GEN_GEO`.
2. Un span de type `DIRECT` NE DOIT PAS porter aussi un code `GEN_*`.
3. Une annotation `IMPLICIT` PEUT n'avoir **aucun offset** (`start = end = null`)
   lorsqu'elle résulte d'une inférence sur l'ensemble du document. Le schéma de
   données DOIT l'accepter (exigence de SynthPAI, voir SPEC-02).
4. Toute annotation DOIT porter un `entity_id` si le corpus fournit des
   coréférences, sinon `null`.
5. Le `subject` DOIT être renseigné ; en son absence, `SELF` est la valeur par
   défaut **explicite** (elle est écrite, pas supposée).

## 8. Actions d'anonymisation applicables

La taxonomie détermine les actions possibles. Table de référence pour le moteur
de politique :

| `identifier_type` | Actions autorisées |
|-------------------|--------------------|
| `DIRECT` | `SUPPRESS`, `PSEUDONYMIZE` |
| `QUASI` avec `granularity = EXACT` | `GENERALIZE` (→ `RANGE` ou `COARSE`), `SUPPRESS` |
| `QUASI` avec `granularity = COARSE` | `SUPPRESS` uniquement (plus rien à généraliser) |
| `SENSITIVE_ONLY` | `KEEP` ou `SUPPRESS` selon la politique |
| `IGNORED` | `KEEP` |

La généralisation est l'action la plus intéressante du point de vue de
l'utilité : elle réduit $k^{-1}$ sans détruire l'information. Sa disponibilité
dépend de `granularity`, d'où l'importance de ce champ.

## 9. Table de réconciliation avec IPI [@baroud2025ipi]

Les 9 catégories d'identifiants indirects d'IPI (corpus : 100 *discharge
summaries* MIMIC-III, 6 199 annotations — le corpus est **MIMIC-III**, pas
MIMIC-IV) confrontées ligne à ligne au bloc `GEN_*` de §4.2. Définitions
verbatim de l'appendix A de la publication ; compte = table 1.

| # | Catégorie IPI | Définition (guidelines) | n (% des 6 199) | Code(s) SPEC-01 | Écart |
|---|---------------|-------------------------|-----------------|-----------------|-------|
| 1 | `appearance` | Poids, taille, description du corps ou modifications corporelles (cicatrice, très grand, très petit, variation de poids sur une période, tatouage, piercing) | 132 (2,13 %) | `GEN_PHYSICAL` | Mineur : les modifications médicales (greffe, amputation) porteront aussi `sensitivity = HEALTH` — l'axe est orthogonal, pas d'écart de couverture. |
| 2 | `circumstances` | Événement (accident, tempête, incendie) ayant causé une blessure ou survenu au centre ; patient agressif, refus de soin, sortie AMA ; mode d'admission ; déclarations, demandes, plaintes | 99 (1,6 %) | aucun code — partiellement `GEN_DATE_EVENT` | **Écart réel** : IPI décrit des *événements* et des *comportements*, pas des attributs. La seule part mappable est la date de l'événement (`GEN_DATE_EVENT`). L'événement lui-même n'a pas de code de QI : il relèverait de `OTHER_QI` (et de `sensitivity = JUDICIAL` si plainte/procédure). |
| 3 | `sec` | Emploi (« retired police officer »), antécédents judiciaires, assurance santé, statut social (sans-abrisme, logement subventionné) | 59 (0,95 %) | `GEN_OCCUPATION` + `GEN_SOCIOECON` | L'antécédent judiciaire n'est pas un QI dans SPEC-01 : c'est l'axe `sensitivity = JUDICIAL` (art. 9 RGPD) qui le porte. L'assurance santé est couverte par `GEN_SOCIOECON` (statut, patrimoine). |
| 4 | `family` | Adoption, jumeau, FIV ; historique médical de la famille (« parent mort à 40 ans ») ; implication (fille = procureure de soins) | 273 (4,4 %) | `GEN_FAMILY` ; historique médical familial : `GEN_HEALTH_STATE` avec `subject = THIRD_PARTY` | Mineur : le projet gère explicitement le tiers par l'axe `subject`, ce qu'IPI ne formalise pas. |
| 5 | `fclt_personnel` | Hôpitaux, unités, laboratoires, services, établissements, équipes consultées, étages/chambres, spécialités, médecins externes | 1 421 (22,92 %) — la plus grosse catégorie | `GEN_AFFILIATION` (organisation de soin = organisation d'appartenance) ; médecin externe *nommé* : `DIR_NAME` | Nuance d'objet : IPI désigne l'organisation **de soin**, SPEC-01 toute affiliation (employeur, école, association). Seul sous-élément sans code propre : le médecin externe non nommé (spécialité seule) → `OTHER_QI`. |
| 6 | `time` | Âge, ou informations temporelles : 2ᵉ jour post-opératoire, 13ᵉ jour de grossesse, 6ᵉ jour de vie, heures exactes de prélèvement/posologie. Les durées liées à la maladie elle-même sont exclues | 4 006 (64,62 %) — l'essentiel des annotations | `GEN_AGE` (l'âge) ; `GEN_DATE_EVENT` (le daté) | **Écart réel** : le temps *clinique* (« post-op day 2 ») n'est pas un événement de vie de la personne ; `GEN_DATE_EVENT` est le réceptacle le plus proche mais sa définition (§4.2) vise la vie de la personne. Documenté comme limite, pas de nouveau code (fréquence dans la population non estimable — §10, point 3). |
| 7 | `lfstl` | Loisirs (sport, instrument), style de vie (régime, vie privée) | 144 (2,32 %) | `GEN_LIFESTYLE` | Aucune. (Tobac/alcool : `sensitivity = HEALTH` en sus.) |
| 8 | `details` | PII non détecté par les anonymiseurs automatiques, ou description indirecte d'un PII (« vit dans un foyer de transition », « a eu 18 ans avant la pandémie », n° de licence) | 32 (0,52 %) | **Pas un code — une propriété structurelle** : l'axe `expression_mode` (`IMPLICIT` / `NON_STANDARD`) appliqué au code du PII sous-jacent (adresse → `DIR_ADDRESS` / `GEN_GEO`, âge → `GEN_AGE`, licence → `DIR_ID_NUMBER`) | Aucune : c'est l'apport de la taxonomie à quatre axes. IPI traite le problème comme une catégorie résiduelle ; SPEC-01 le décompose. |
| 9 | `other` | Informations non médicales sensibles : langue, ethnie (« Caucasian », « AAF »), orientation sexuelle | 33 (0,53 %) | `GEN_ORIGIN_BELIEF` (langue, origine, opinions) | L'orientation sexuelle n'a pas de code QI dédié : portée par l'axe `sensitivity = SEXLIFE` (art. 9 RGPD) ; le code porteur, quand l'information identifie, reste `GEN_ORIGIN_BELIEF`. |

### 9.1 Codes `GEN_*` sans équivalent IPI

Quatre des 13 codes du bloc générique n'ont **pas** d'équivalent IPI — ce sont
des extensions du projet, cohérentes avec l'origine déclarée du §2 (IPI + TAB +
domaines du projet) :

| Code | Raison de l'absence dans IPI |
|------|------------------------------|
| `GEN_GENDER` | IPI ne l'annotait pas : le sexe est un champ structurel de MIMIC (démo), hors des *discharge summaries*. |
| `GEN_GEO` | Corpus mono-site (Beth Israel Deaconess, Boston) : la géographie n'y est pas discriminante. IPI n'a pas de catégorie lieu ; les adresses y sont traitées comme PII directs (`details`). |
| `GEN_EDUCATION` | Non annoté dans MIMIC-III (champ démo non exploité par IPI). |
| `GEN_HEALTH_STATE` | Corpus clinique : la santé du patient est le *domaine*, pas l'identifiant. Le code du projet couvre le cas hors clinique (arrêt maladie, handicap — l'exemple canonique du projet). |

Les blocs `HR_*`, `SUP_*`, `FOR_*` n'ont de même aucun équivalent IPI : le
corpus IPI est clinique mono-domaine (limites §9 de la fiche [`ipi-mimic.md`](../datasets/ipi-mimic.md)).

### 9.2 Conclusion de la réconciliation

- **9 catégories IPI → couverture totale** : 7 correspondent à un code
  `GEN_*` (parfois complété par un axe), 1 est une propriété structurelle
  (`details` → `expression_mode`), 1 est un écart réel documenté
  (`circumstances` → événements/comportements, sans code d'attribut).
- **13 codes `GEN_*`** : 9 couverts par IPI (à des degrés divers), 4 sans
  équivalent (extensions projet).
- La décomposition en 13 codes est **confirmée** : elle raffine IPI sans la
  contredire, et les axes `expression_mode` / `sensitivity` absorbent ce que
  IPI traitait comme catégories résiduelles.
- **Statut** : SPEC-01 passe à `Gelé` (v1.1) : la campagne d'expériences en
  cours peut s'appuyer sur cette taxonomie.

## 10. Extensibilité

Ajouter un code DOIT suivre cette procédure :

1. Justifier que le QI n'est couvert par aucun code existant.
2. Fournir une définition, deux exemples, et une forme normalisée.
3. Fournir la source de population permettant de calculer $k$ sur cet attribut —
   **un QI dont on ne sait pas estimer la fréquence dans la population est
   inutilisable par le moteur de risque.**
4. Incrémenter la version de SPEC-01 et mettre à jour tous les `label_map`.

Le point 3 est la barrière qui empêche la taxonomie de gonfler indéfiniment.

## 11. Journal des modifications

| Version | Date | Changement |
|---------|------|-----------|
| 1.0 | 2026-08-30 | Création. Bloc DIR (10), GEN (13), HR (10), SUP (10), FOR (4). Table de réconciliation IPI ouverte. |
| 1.1 | 2026-09-04 | **Ticket F-2 — réconciliation IPI.** §9 rempli : les 9 catégories d'IPI (MIMIC-III, 6 199 annotations) confrontées ligne à ligne au bloc `GEN_*` — 7 mappées sur un code `GEN_*` (parfois complété par un axe), `details` absorbée par l'axe `expression_mode`, `circumstances` documentée comme écart réel (événements/comportements, sans code d'attribut) ; 4 codes `GEN_*` sans équivalent IPI (extensions projet) listés en §9.1. Note d'alerte du §2 convertie en confirmation. Statut `Stable` → `Gelé` : la taxonomie fige pour la campagne d'expériences en cours. |
