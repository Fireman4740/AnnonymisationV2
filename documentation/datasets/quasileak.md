# QuasiLeak-Bench

Source : Zhu et al., [QuasiLeak-Bench](https://www.alphaxiv.org/pdf/2610.21333),
[code et données officiels](https://github.com/Yufannnn/QuasiLeak-Bench), commit
`75987cdf029fac5fecce160bea218b458ed46dbb`, version 1.0.1. Les données
synthétiques sont sous **CC BY-NC-SA 4.0** ; le code officiel est sous MIT.
La licence non commerciale et le partage à l'identique doivent être respectés.

Les 5 000 messages sont répartis par profil : 3 500 train / 500 validation /
1 000 test, avec 350 / 50 / 100 profils distincts. Le sous-ensemble officiel
de 1 000 messages dans le zip n'est pas le test : il chevauche train et test et
ne doit pas servir de test indépendant. Les documents contiennent un profil
synthétique, une politique `HIDE`, `KEEP`, `NEUTRAL` et des groupes de 2 à 4
indices verbatim. Seuls les groupes dont l'attribut est `HIDE` deviennent le
gold du pivot. Les groupes et profils gold ne sont pas exposés dans
`Document.meta` ; la politique et le contexte, qui sont des entrées de la
tâche officielle, y sont conservés. Les indices `KEEP` et `NEUTRAL` ne sont pas
traités comme des fuites par le pivot. Les fichiers bruts complets restent
disponibles au scorer officiel séparé.

Le pivot traduit l'attribut déduit en catégorie générique et conserve
`group_id`, `cue_id`, taille du groupe et offsets ; le gold est non exhaustif
pour l'ensemble des données personnelles. Les scores de spans sont donc des
diagnostics, pas le P-GF1 de l'article. Le diagnostic supplémentaire
`quasileak_group_mask_rate` est la proportion de groupes HIDE avec au moins un
indice intégralement couvert par les décisions non KEEP. Il ne pénalise pas le
sur-masquage et ne prouve pas que l'attribut n'est plus inférable.

Le scorer `quasileak_score.py` et le renderer `quasileak_render.py` sont copiés
inchangés du dépôt officiel, licence MIT incluse. `anonv2 quasileak-score`
vérifie leurs empreintes, le corpus et les partitions ; il appelle le scorer
original avec les paramètres par défaut : gamma=2, theta=0,75, rho_sec=0,5 et
lambda_k=1. Ses valeurs sont sur 0–100 et incluent P-GF1, B-GF1, E-GF1, E_R,
DSR et FAR. Une sélection incomplète, une ligne absente, une erreur ou une
prédiction partielle échoue explicitement. Le scorer reçoit des groupes
**réellement prédits**, chacun avec un attribut et 2 à 4 spans ; aucune
reconstruction à partir des groupes gold n'est effectuée.

Les systèmes d'anonymisation existants ne produisent pas de prédictions
groupées avec attribution : leur score P-GF1 est donc indisponible. Le script
`predict_quasileak_local.py` fournit un détecteur séparé utilisant Qwen local
et le renderer/invite zéro-shot officiels. L'invite officielle fournit le
profil synthétique complet au détecteur, comme dans le papier ; les systèmes
d'anonymisation génériques n'ont pas nécessairement cette entrée. Leurs scores
ne répondent donc pas à la même tâche.

## Préparation locale

```sh
export ANONV2_V1_DATASETS=/chemin/vers/le/cache
python scripts/fetch_quasileak.py --root "$ANONV2_V1_DATASETS"
anonv2 datasets ingest quasileak --split test
python scripts/select_quasileak.py --root "$ANONV2_V1_DATASETS/QuasiLeak-Bench" \
  --count 50 --seed 20261016 --out selection.json --pivot-out selection-pivot.json
```

La sélection est reproductible, limitée à 50 documents et tire au plus un
document par profil test. La sélection de graine 20261016 est figée dans
`configs/evaluation/frozen/quasileak-test-50-v1.ids.json` et son manifeste pivot
dans `quasileak-test-50-v1.lock.json`. La liste des identifiants et le manifeste
du pivot doivent être conservés et figés avant toute comparaison. Cette nouvelle cohorte
est indépendante des cohortes à 200/50 déjà verrouillées pour les autres
corpus : aucun ancien manifeste n'est modifié.

## Anonymiseurs existants

```sh
anonv2 predict --dataset quasileak --split test --system llm-windowed \
  --selection-manifest selection-pivot.json --out runs/quasileak-windowed
anonv2 score --run runs/quasileak-windowed --protocol quasileak-v1
```

Les modèles du projet sont configurés pour l'API Qwen locale. Utiliser le même
manifeste de sélection pour chaque système comparé. Vérifier les paramètres du
profil et du modèle avant tout lancement.

## Détecteur natif de groupes et score officiel

```sh
python scripts/predict_quasileak_local.py --root "$ANONV2_V1_DATASETS/QuasiLeak-Bench" \
  --selection selection.json --out predictions.jsonl --backend qwen_local_box
anonv2 quasileak-score --root "$ANONV2_V1_DATASETS/QuasiLeak-Bench" \
  --predictions predictions.jsonl --split test --selection selection.json --out scores.json
```

Les appels sont locaux, séquentiels, à température 0 et limités à 8 192 tokens
de sortie par défaut ; `enable_thinking=false` est fourni par le backend Qwen.
Le modèle doit renvoyer une liste `evidence` ; une réponse tronquée, invalide
ou une erreur API reste une erreur et bloque le scoring. Le cache LLM permet
de relancer sans recalculer les réponses valides. Le fichier `.lock.json`
accompagnant les prédictions verrouille sélection, source, invite, renderer et
modèle. Une évaluation sur 50 documents est `sampled`, non un score sur les
1 000 documents du test. Les prédictions externes au projet restent possibles
au format officiel, mais leur provenance n'est pas vérifiée.

Les données et sorties sont synthétiques mais la licence s'applique ; elles ne
sont pas commitées dans le dépôt. Le banc existant garde ses cohortes gelées :
une campagne multi-corpus qui inclut QuasiLeak nécessite de figer une nouvelle
cohorte au lieu de modifier la cohorte de référence.
