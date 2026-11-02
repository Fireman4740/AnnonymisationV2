# Politique de divulgation HIDE / KEEP / NEUTRAL

Interface : `src/anonymisation/policy/disclosure.py`, configuration
`configs/policy/disclosure.yaml`, option `anonv2 predict --disclosure-policy <id>`.

## Ce que c'est

Une étape **déterministe, après la détection**, qui décide attribut par
attribut si une information détectée peut rester visible. Elle ne modifie
aucun prompt et ne rappelle aucun modèle : le détecteur voit exactement le
même texte avec ou sans politique, et l'écart se mesure sur les mêmes
détections (cache LLM inclus).

Distincte des politiques de risque P0–P4 (`--policy`), qui choisissent une
action selon le risque de ré-identification.

| Verdict | Condition | Effet sur la décision |
|---|---|---|
| `HIDE` | attribut listé `hide` | décision du système conservée |
| `KEEP` | attribut listé `keep` | décision remplacée par `KEEP` (texte en clair) |
| `NEUTRAL` | attribut listé `neutral` | selon `neutral_action` (obligatoire) |
| `UNGOVERNED` | catégorie hors table (DIRECT_*, HR_*, GEN_GEO…) | décision conservée |

La décision `KEEP` garde la trace de l'action initiale dans
`meta.disclosure`. Le lock du run enregistre la politique, l'empreinte de la
configuration et le décompte des verdicts ; la scorecard expose
`system.disclosure_policy` et `anonv2 compare` sépare les lignes.

## Sources de politique

- `document` : `Document.meta["policy"]` (`hide`, `keep`, `neutral`), fournie
  par le corpus comme entrée de la tâche (QuasiLeak-Bench). Un corpus qui n'en
  fournit pas fait **échouer** le run : choisir une politique statique.
- `static` : listes fixées dans le YAML, applicables à n'importe quel corpus
  (RH, forums, support). `all-hide` est un contrôle qui doit laisser le run
  inchangé.

Dans une campagne, `disclosure_policy` d'un système accepte une chaîne ou une
table par dataset avec une clé `default` explicite :
`{"quasileak": "document", "default": null}`.

## Refus explicites

- système sans capacité `decisions` (boîte noire) ;
- texte anonymisé non reproductible depuis les décisions (réécriture libre) ;
- politique incomplète (attribut absent des trois listes) ou attribut inconnu.

## Limites

Le verdict suit la catégorie choisie par le système : une erreur de
catégorisation n'est pas corrigée. La table d'attributs couvre les huit
attributs de QuasiLeak ; une politique pour d'autres attributs exige
d'étendre la table, testée contre le manifeste QuasiLeak.
