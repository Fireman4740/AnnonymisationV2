# Glossaire

Vocabulaire du projet. En cas de conflit avec un usage externe, cette page fait
foi pour la documentation et le code.

---

## Identification

**Identifiant direct (`DIRECT`)**
Information qui identifie une personne **seule** : nom, email, numéro national,
adresse précise. Correspond à ce qu'un système de PII classique détecte.

**Quasi-identifiant (QI, `QUASI`)**
Information qui n'identifie **qu'en combinaison** avec d'autres : âge,
profession, ville, diplôme, version d'un logiciel. C'est l'objet central du
projet.

**Attribut confidentiel / sensible (`SENSITIVE_ONLY`)**
Information dont la divulgation nuit, sans nécessairement identifier : état de
santé, opinions. Axe **orthogonal** à l'identification — une donnée peut être
sensible sans être identifiante, et l'inverse.

**QI explicite / non standard / implicite**
Trois modes d'expression, du plus simple au plus difficile :
« j'ai 28 ans » · « je suis né la même année que la chute du Mur » ·
« j'ai soutenu ma thèse l'an dernier ». L'implicite est le régime où la
littérature échoue le plus.

---

## Risque

**Population de référence ($P$)**
L'ensemble des individus parmi lesquels la cible pourrait se trouver. Sans
population, aucun risque n'est calculable. Peut être humaine (INSEE) ou non
(parc installé, pour le support).

**Classe d'équivalence ($EC_P(Q)$)**
L'ensemble des individus de $P$ compatibles avec les QI observés $Q$.

**k-anonymité ($k$)**
$k(Q) = |EC_P(Q)|$. Un enregistrement est $k$-anonyme si au moins $k$ individus
partagent la même combinaison de QI. $k = 1$ signifie unique, donc identifié.

**$k$ combinatoire**
Le $k$ d'un **ensemble** de QI, par opposition au $k$ de chaque QI pris
isolément. C'est la quantité que le projet cherche à estimer depuis du texte
libre.

**Risque prosecutor**
L'attaquant sait que la cible figure dans le jeu de données. $R \approx 1/k$.
Modèle le plus conservateur.

**Risque journalist (k-map)**
L'attaquant ne sait pas si la cible y figure ; il raisonne sur la population
complète. Risque plus faible, plus réaliste.

**Risque marketer**
Risque **moyen** sur tous les enregistrements. Pertinent pour une divulgation
de masse, pas pour protéger un individu.

**Modèle par copule**
Estimation du risque quand la population n'est connue que par ses marginales
(cas de l'INSEE). Référence : Rocher et al., 2019.

**Portée (`scope`)**
Le périmètre d'observation des QI : `document`, `thread`, ou `author`. Un même
sujet est d'autant plus identifiable que la portée est large :
$k_{author} \leq k_{thread} \leq k_{document}$.

---

## Attaque

**Linkage (divulgation d'identité)**
Retrouver **qui** est l'auteur d'un texte anonymisé.

**Inference (divulgation d'attribut)**
Retrouver **quoi** sur une personne déjà localisée. Distinct du linkage.

**Ré-identification**
Le résultat d'un linkage réussi.

**$R_{succ}$ (Re-identification Success Rate)**
Proportion de documents ré-identifiés par un attaquant donné.
**Métrique principale du projet.** N'a de sens que relativement à un attaquant,
une population et une portée spécifiés.

**Attaquant A / B / C**
LLM local 7–14 B hors ligne · LLM plus puissant · agent avec recherche web. Voir
SPEC-08.

**DILR / IRR**
Direct Identifier Leak Rate · Indirect Re-ID Rate. Distinguer les deux est un
résultat en soi : un système peut ne laisser fuiter aucun nom et laisser
retrouver les gens par combinaison.

---

## Anonymisation

**Anonymisation**
Transformation rendant la ré-identification improbable. Dans ce projet, elle est
**pilotée par le risque** : l'intensité dépend du $k$ estimé.

**Pseudonymisation**
Remplacement d'un identifiant par un substitut cohérent. Réversible avec la
table de correspondance ; ce n'est pas de l'anonymisation au sens du RGPD.

**Généralisation**
Remplacement d'une valeur par une valeur moins précise : `28 ans` → `25–34 ans`,
`Lille` → `Hauts-de-France`. L'action la plus intéressante : elle réduit le
risque sans détruire l'information.

**Suppression**
Retrait pur et simple. Action de dernier recours.

**Politique d'anonymisation**
La table `seuil de risque → action`, configurable. Les politiques P0…P4
définissent les points de la courbe privacy-utility.

---

## Évaluation

**QICR (QI Combination Recall)**
Proportion des combinaisons de QI à risque **entièrement** détectées.
Métrique de diagnostic centrale du projet ; le F1 span-level ne la capture pas.

**RCR@k (Risky Combination Recall @ k)**
$P(\hat{k} \geq k \mid k_{true} \geq k)$. Mesure le **sur-masquage**. À publier
conjointement à QICR — séparément, chacun est manipulable.

**Utility Retention**
$Performance(\text{anonymisé}) / Performance(\text{original})$ sur une tâche
métier. Second axe du compromis.

**Privacy-Utility Operating Point**
Un point $(R_{succ}, UtilityRetention, latence)$ pour une politique donnée. Le
livrable de résultat du projet est une **courbe**, pas un F1.

**Calibration (ECE, Brier)**
Un score est calibré si « risque = 0.8 » correspond effectivement à ~80 % de
cas. Condition de validité de toute politique par seuils.

**Statut de métrique**
`OFFICIAL` · `SAMPLED` · `DIAGNOSTIC` · `PROXY` · `UNAVAILABLE` · `FAILED`.
Une métrique `DIAGNOSTIC` n'est pas comparable à un chiffre publié.

---

## Données

**Profil latent**
L'ensemble des attributs vrais d'un individu, connu du benchmark mais pas du
système évalué. C'est ce qui permet de calculer une vérité terrain exacte.

**Combinaison**
Un ensemble de QI attribués à un même sujet dans une portée donnée, avec son
$k_{true}$.

**Manifeste**
Le fichier YAML décrivant un dataset : source, licence, checksum, volumétrie,
`label_map`. Le registre refuse de charger un dataset mal manifesté.

**Lock (`.manifest.lock.json`)**
La copie figée du manifeste après ingestion, avec les checksums des fichiers
produits et la version de taxonomie. Ce qui rend une expérience reproductible.

**`label_map`**
La correspondance étiquette source → codes SPEC-01. Doit être **total** : une
étiquette non mappée fait échouer l'ingestion.
