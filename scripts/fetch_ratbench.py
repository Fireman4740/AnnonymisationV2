"""Acquisition reproductible des sources RAT-Bench (texte + population PUMS).

Place sous ``$ANONV2_V1_DATASETS/RAT-Bench/`` exactement ce qu'attend le
manifeste ``configs/datasets/ratbench.yaml`` :

* ``english.jsonl`` — niveaux 1 à 3 du benchmark anglais, Hugging Face
  ``imperial-cpg/rat-bench`` à une révision figée (licence MIT) ;
* ``cache/pums_pwgtp_sample_.csv`` — l'échantillon PUMS 2010 **officiel** du
  dépôt ``imperial-aisp/rat-bench`` (Google Drive référencé par son README),
  déjà rééchantillonné selon les poids PWGTP : chaque ligne pèse autant ;
* ``cache/pums_population.parquet`` — le même échantillon en parquet (colonnes
  codées, lecture rapide) ;
* ``cache/maps/*.json`` — les tables code ↔ libellé officielles (converties
  depuis les pickles du dépôt, à un commit figé).

Pourquoi l'échantillon officiel plutôt que l'ACS brut (approche v1) : les
profils RAT-Bench ont été tirés de PUMS 2010 avec ces codages ; le risque
publié par le papier est calculé sur ce fichier. Reprendre l'ACS 2022 aurait
changé à la fois la population et les codes.

Chaque fichier téléchargé est vérifié par SHA-256 : une source qui change en
amont fait échouer le script au lieu de produire en silence d'autres chiffres.
Les pickles ne sont désérialisés qu'APRÈS vérification de leur empreinte (un
pickle exécute du code à la lecture).

Usage ::

    uv run --isolated --no-project --with huggingface_hub --with gdown \\
        --with pandas --with pyarrow python scripts/fetch_ratbench.py --root "$ANONV2_V1_DATASETS"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HF_REPO = "imperial-cpg/rat-bench"
HF_REVISION = "e439e9171dd43c5e26d91b678e3df6264fea5239"
HF_LEVELS = {
    1: "05732f2f1f79a4749f00668cbf405cbdaf5b400b19b1808def5eb5eeff2803d3",
    2: "1457ddd873d859885467a8d64af6466cff8a209b6fa5b354abe02f4780dd9e93",
    3: "0d380e87858317e67badbb4dd7a8d1ebbac3f688562e6444703b8075ed3c6457",
}

GITHUB_REPO = "imperial-aisp/rat-bench"
GITHUB_COMMIT = "8e9f03d00cb0559508d8ee86bc743875aa6bcf95"
MAPS = {
    "CIT": "80d2baa6454f08e7cd0f5c6dc75a81a21b9859cdfc0bbf75e2946a99ffd02d17",
    "DOB-Day": "607465db12c265d35438c93c104d2460903ba30a1b6b83a384bf74bbdae68353",
    "DOB-Month": "227d8ebd5b8b4ced19c247c150237358874009568cb055ff54de463c4ef47b42",
    "DOB-Year": "5228b195753e26656a46503ab77fb782cc561aca6de271cdc0bedeebc2e4475e",
    "DOB": "dc62093bcc0dcf47125798082fd9548cc311ffb6a8842f0fb674b2c122625513",
    "ESR": "2f5e5e677d57ae480c2394105629a1d7e9ad482aaceba7fb2bba003bea527762",
    "MAR": "1f60be88902ddba9cdcdd3ea95d29cb1355cc868ceee2e150e12ec41abcd9987",
    "OCCP": "926a048c4625880cd2e8e11ebee0a7d9bcc341396c90b8e66f893acdee9b7b3f",
    "OCCP_type": "779f2f2c7a34753e0e477ea0d94373bd8ac569e432658e9967b7ac0d02320b62",
    "PUMA_FULL": "418bd4fa89ee68aa02ad4e34020b939cc944f5685872172e6f5f8324cebdfb96",
    "RAC2P": "ffdf6d8196a5948307265e6ba70adcf2a1e1d4f9bcfff46110b8ddfec14c1562",
    "SCHL": "7088d4bd3cfc09601a482037c14745d8617cc2fbc4e7d0b4d438a32e1428aebd",
    "SEX": "76465c6a49419eb2bb487cbdade471366c688846c0380f69c015cf944225b784",
    "ST": "c46a1692c1d8dedc003c2a982d5ab420ca606a6f59e3b7e0b8fd729949ac776e",
    "zip_to_puma": "445d50141589aefba5e470c18ef38de5f38480b632fd254a4de19d1920abdc81",
}

PUMS_DRIVE_ID = "1Wpm9kwIDi9eS7-AALM2b_mjec79wHlE_"
PUMS_ZIP_SHA256 = "5eb40e6bc7dfa1c8ac9bf2630153f361c40a6627dfb3ee9b5d5835d9eeba5505"
PUMS_CSV_NAME = "pums_pwgtp_sample_.csv"
#: Colonnes codées utilisées par CorrectMatch dans le code officiel.
PUMS_COLUMNS = (
    "OCCP", "RAC2P", "ST", "CIT", "ESR", "SCHL", "MAR", "SEX",
    "PUMA_FULL", "DOB", "DOB-Day", "DOB-Month", "DOB-Year",
)


class FetchError(RuntimeError):
    """Source introuvable ou empreinte divergente."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _check(path: Path, expected: str) -> None:
    actual = _sha256(path)
    if actual != expected:
        raise FetchError(
            f"{path} : empreinte {actual[:12]}… ≠ attendue {expected[:12]}… — la "
            "source amont a changé ; mettre à jour la révision ET l'empreinte "
            "délibérément, jamais l'une sans l'autre."
        )


def fetch_text(target: Path) -> None:
    from huggingface_hub import hf_hub_download

    lines: list[str] = []
    for level, expected in HF_LEVELS.items():
        path = Path(hf_hub_download(
            HF_REPO, f"benchmark/english/level_{level}.jsonl",
            repo_type="dataset", revision=HF_REVISION,
        ))
        _check(path, expected)
        lines.extend(line for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fetch_maps(maps_dir: Path) -> None:
    maps_dir.mkdir(parents=True, exist_ok=True)
    for name, expected in MAPS.items():
        # `zip_to_puma` est le seul fichier sans suffixe `_map` dans le dépôt.
        filename = f"{name}.pickle" if name == "zip_to_puma" else f"{name}_map.pickle"
        url = (f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_COMMIT}/"
               f"data/maps/{filename}")
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "map.pickle"
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 — URL figée
                raw.write_bytes(response.read())
            _check(raw, expected)  # AVANT toute désérialisation
            mapping = pickle.loads(raw.read_bytes())  # noqa: S301 — contenu vérifié
        if not isinstance(mapping, dict):
            raise FetchError(f"table {name} : dict attendu, obtenu {type(mapping).__name__}")
        # Liste de paires : les clés ne sont pas toutes des chaînes (codes int).
        # L'ORDRE D'INSERTION est conservé : le prompt officiel énumère les
        # options dans cet ordre, le trier changerait le prompt de l'attaquant.
        pairs = [[k, v] for k, v in mapping.items()]
        (maps_dir / f"{name}.json").write_text(
            json.dumps({"source": f"{GITHUB_REPO}@{GITHUB_COMMIT}", "pairs": pairs},
                       ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def fetch_pums(cache: Path) -> None:
    import gdown
    import pandas as pd

    csv_path = cache / PUMS_CSV_NAME
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "pums.zip"
        gdown.download(id=PUMS_DRIVE_ID, output=str(archive), quiet=True)
        if not archive.is_file():
            raise FetchError("téléchargement Google Drive PUMS échoué (quota ou lien retiré)")
        _check(archive, PUMS_ZIP_SHA256)
        with zipfile.ZipFile(archive) as zf:
            with zf.open(PUMS_CSV_NAME) as src, csv_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    frame = pd.read_csv(csv_path, usecols=list(PUMS_COLUMNS))
    if frame.isna().any().any():
        raise FetchError(f"{csv_path} : valeurs manquantes dans les colonnes codées")
    frame = frame.astype("int64")
    frame.to_parquet(cache / "pums_population.parquet", index=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True,
                        help="racine des corpus (valeur de ANONV2_V1_DATASETS)")
    args = parser.parse_args(argv)
    base = args.root / "RAT-Bench"
    cache = base / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    previous = base / "SOURCES.json"
    if previous.is_file():
        manifest = json.loads(previous.read_text(encoding="utf-8"))
        required = {"english.jsonl", "cache/pums_population.parquet", f"cache/{PUMS_CSV_NAME}",
                    *(f"cache/maps/{name}.json" for name in MAPS)}
        files = manifest.get("files", {})
        if (manifest.get("hf") == {"repo": HF_REPO, "revision": HF_REVISION}
                and manifest.get("github") == {"repo": GITHUB_REPO, "commit": GITHUB_COMMIT}
                and manifest.get("pums", {}).get("zip_sha256") == PUMS_ZIP_SHA256
                and required <= files.keys()):
            for name in sorted(required):
                _check(base / name, files[name])
            print(f"RAT-Bench déjà acquis et vérifié sous {base}")
            return 0
    fetch_text(base / "english.jsonl")
    fetch_maps(cache / "maps")
    fetch_pums(cache)
    manifest = {
        "hf": {"repo": HF_REPO, "revision": HF_REVISION},
        "github": {"repo": GITHUB_REPO, "commit": GITHUB_COMMIT},
        "pums": {"drive_id": PUMS_DRIVE_ID, "zip_sha256": PUMS_ZIP_SHA256},
        "files": {
            str(p.relative_to(base)): _sha256(p)
            for p in sorted(base.rglob("*")) if p.is_file() and p.name != "SOURCES.json"
        },
    }
    (base / "SOURCES.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                                       encoding="utf-8")
    print(f"RAT-Bench prêt sous {base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
