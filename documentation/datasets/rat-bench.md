# RAT-Bench — acquisition et évaluation reproductibles

Le protocole anglais suit le papier [RAT-Bench](https://www.alphaxiv.org/pdf/2602.12806)
et le [code officiel](https://github.com/imperial-aisp/rat-bench/tree/8e9f03d00cb0559508d8ee86bc743875aa6bcf95).
Les révisions sont figées dans `scripts/fetch_ratbench.py` et les fichiers acquis
sont identifiés par SHA-256 dans `RAT-Bench/SOURCES.json`.

## Sources et emplacement

- Textes : `imperial-cpg/rat-bench@e439e9171dd43c5e26d91b678e3df6264fea5239`,
  `benchmark/english/level_{1,2,3}.jsonl` : 300 documents et profils au total.
- Population : échantillon **PUMS 2010 officiel** distribué par le lien Google Drive
  du README amont, déjà rééchantillonné selon PWGTP. Chaque ligne a le même poids ;
  réappliquer PWGTP compterait deux fois les poids. ACS 2022 et l'exemple de
  100 lignes du dépôt amont ne conviennent pas à cette reproduction.
- Tables : pickles officiels au commit figé, vérifiés **avant** désérialisation,
  puis convertis en JSON en conservant l'ordre d'insertion des options.
- Cache local recommandé : `data/raw/RAT-Bench/english.jsonl`,
  `data/raw/RAT-Bench/cache/pums_pwgtp_sample_.csv`,
  `data/raw/RAT-Bench/cache/pums_population.parquet`,
  `data/raw/RAT-Bench/cache/maps/*.json`.
- Pivot : `data/processed/ratbench/eval/`, produit exclusivement par ingestion.
- Texte/code RAT-Bench : MIT ; PUMS : microdonnées publiques US Census.
  CorrectMatch est une dépendance GPL-3.0 distincte.

```bash
export ANONV2_V1_DATASETS="$PWD/data/raw"
uv run --isolated --no-project --with huggingface-hub --with gdown \
  --with pandas --with pyarrow python scripts/fetch_ratbench.py --root "$ANONV2_V1_DATASETS"
uv sync --locked --python 3.11 --extra datasets --extra metrics --extra attack --extra dev
uv run --locked --extra datasets anonv2 datasets ingest ratbench --split eval
```

Une acquisition déjà complète est revérifiée sans retéléchargement. Aucun corpus
brut, pivot ni secret n'est commité. Le noyau conserve Python ≥3.10 ; l'extra
`attack` exige Python ≥3.11 pour CorrectMatch. Julia et ses paquets sont résolus
par `juliapkg.json` dans l'environnement du worktree, au premier import.

## Chaîne d'évaluation

```bash
# Fournir OPENROUTER_API_KEY dans l'environnement, sans l'inscrire dans le YAML.
uv run --locked anonv2 predict --dataset ratbench --split eval \
  --system passthrough --profile deterministic --limit 2 --out runs/sanity-pass
uv run --locked --extra attack anonv2 attack --run runs/sanity-pass \
  --attacker ratbench --backend openrouter_nemotron_super --workers 1
uv run --locked --extra attack anonv2 judge --run runs/sanity-pass \
  --backend openrouter_nemotron_super --workers 1
uv run --locked anonv2 score --run runs/sanity-pass --protocol ratbench-v1
```

L'attaquant ne reçoit que le texte anonymisé, les attributs demandés, le scénario
et les options démographiques. Les profils gold ne servent qu'à juger ses
réponses. Son prompt reproduit l'anglais officiel. Les règles de jugement
Jaro-Winkler reprennent le code amont, y compris ses particularités CIT et OCCP,
explicitement documentées dans `correctness.py`.

Les QI correctement devinés alimentent CorrectMatch. Les codes des colonnes et de
la cible subissent la même bijection ordonnée vers 1…K, nécessaire pour les trous
de la colonne DOB. Une cible absente du support de l'échantillon est une erreur
explicite ; aucun risque n'est inventé. Le calcul moyenne dix estimations finies
par cible sur N = 306 169 200, constante du chemin `compute_reid_risk` officiel.
Ce risque stochastique est figé dans `attacks.jsonl` : la relecture du score est
reproductible, une nouvelle attaque n'est pas garantie identique.

Le succès RAT-Bench (`reid_success_rate`) vaut 1 si un identifiant direct est
deviné ou si la correctness CorrectMatch atteint 0,2. Le bootstrap porte sur
les documents ; il ne mesure pas l'incertitude des appels LLM et du modèle copule.
Ce n'est pas un k_true, un risque observé ou une garantie opérationnelle.

Le juge reprend le [prompt et la formule SPIA](https://github.com/maisonOP/spia/blob/3fa78a1b3c75788c6294f40024fc79e1ef42923f/src/evaluate/utility/utility_evaluator.py) :
`(readability/10 + meaning/10 + ROUGE-L F1)/3`, avec stemmer de Porter.
Les réponses et composants sont conservés dans `judgments.jsonl`.
Le ROUGE-L interne sans stemmer reste un proxy lexical séparé.

Les locks des deux étapes relient sorties, prédictions et gold par empreintes.
`score` refuse les documents manquants/étrangers/dupliqués, les fichiers modifiés,
les protocoles incompatibles et les dénominateurs divergents. Une panne LLM ou un
JSON invalide est compté en erreur, jamais comme protection ni note par défaut.
Au-delà de 5 % d'erreurs d'une étape, ses métriques deviennent indisponibles et
la scorecard non publiable. `score` ne relance ni LLM ni CorrectMatch.

Une archive `git archive` conserve le commit via `.git_archival.txt` et
`export-subst`. Sans dépôt Git, la propreté de l'arbre reste inconnue : le
scoring diagnostic est permis, la publication demeure bloquée. Un marqueur
non substitué ou malformé n'est jamais accepté comme identité de commit.

## Comparabilité et travaux restants

Gemma 4 26B et Nemotron Super via OpenRouter sont configurés en `:free`, avec
prix maximum nul et sans changement automatique de modèle. Après des réponses
429 de Gemma, les rôles d'évaluation choisissent explicitement Nemotron comme
référence externe (120 B, au-dessus de la limite des modèles locaux évalués).
Gemma reste disponible par `--backend openrouter_gemma4_26b`. Les quotas peuvent faire échouer le test.
L'attaquant diffère de GPT-4.1 utilisé dans RAT-Bench : les résultats restent
**DIAGNOSTIC**, même avec un protocole et des données fidèles. Le juge gratuit
n'est pas encore validé contre des annotations humaines.

Le split `eval` conserve les trois niveaux officiels, sans prétendre disposer
d'un split de calibration représentatif. La sélection `--limit 2` est un test de
fonctionnement uniquement. Une campagne complète doit couvrir les niveaux,
scénarios, langues, comparer les systèmes sur les mêmes documents et documenter
les erreurs et intervalles d'incertitude.

CPR/IPR restent les proxies littéraux actuels : `anonv2 attack --attacker ratbench`
ne met pas en œuvre l'inférence et l'appariement **multi-sujets** de SPIA. Restent
à terminer H-3 (SPIA), H-4 (QICR/RCR@k), H-5 (calibration indépendante), H-6
(validation humaine et réentraînement aval), H-7 (comparaisons appariées) et H-8/H-9
(sanité complète et reproduction publiée). Voir `EPIC-H-fiabilite-evaluation.md`.
