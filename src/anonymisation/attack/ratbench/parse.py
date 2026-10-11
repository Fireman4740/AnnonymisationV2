"""Lecture de la réponse de l'attaquant — portage de ``parse_output_gpt``.

Le code officiel (``pii_benchmark/utils.py`` au commit figé) lit la réponse
**ligne à ligne et seulement ainsi** : une ligne dont la clé (avant le premier
``:``) est un libellé connu (``att_names``) ouvre un attribut, les trois lignes
suivantes donnent ``Inference`` / ``Guess`` / ``Certainty``. Aucune lecture JSON
préalable : une réponse au JSON compact sur une ligne ne produit aucune
devinette, exactement comme chez l'officiel. Le portage reproduit aussi :

* le saut des lignes ``{``, ``""`` et ``},`` ;
* l'arrêt silencieux sur une exception (fin de réponse au milieu d'un
  attribut) en conservant les attributs déjà lus — devinettes partielles ;
* la traduction du libellé en colonne par ``get_att_key`` (table PUMS seule :
  les tables MEX/SRB/NL ne concernent pas la population US portée ici).

Seul écart, imposé par SPEC-10 C3 : une réponse dont **aucun** attribut n'est
lisible est une erreur du document, jamais « rien deviné ». Un attribut absent
parmi d'autres lus est en revanche une devinette vide (fausse), comme chez
l'officiel.
"""

from __future__ import annotations

from typing import Any

from anonymisation.attack.ratbench.maps import LABEL_TO_COLUMN

#: ``att_names`` officiel, mot pour mot (ordre conservé). Une clé hors de cette
#: liste n'ouvre jamais d'attribut — même « AGEP », absent de la liste.
ATT_NAMES: frozenset[str] = frozenset({
    "sex", "race", "citizenship status", "education level", "occupation",
    "marital status", "employment status", "state of residence", "DOB",
    "date of birth",
    "age", "urban status", "ever given birth", "date of first marriage",
    "age at first marriage", "partner's age", "ethnicity", "language spoken",
    "phone number", "SSN", "JMBG", "email", "credit card number", "name",
    "address", "zip code",
    "Income", "Hearing difficulty", "Mobility status (lived here 1 year ago)",
    "Ability to speak English", "Gave birth to child within the past 12 months",
    "Insurance through a current or former employer or union",
    "Interest, dividends, and net rental income past 12 months",
    "Travel time to work", "Language other than English spoken at home",
    "Number of times married",
    "Credit card number", "Crypto wallet number", "Date or time", "email address",
    "IBAN code", "IP address", "Nationality, religious or political group",
    "Location", "Full person name", "Phone number", "Medical license", "URL",
    "US bank number", "US drivers license",
    "US Individual Taxpayer Identification Number", "US passport number", "US SSN",
    "tipo de vivienda", "sexo", "edad", "entidad o pais de nacimiento",
    "servicio de salud", "religion", "habla lengua indigena", "habla espanol",
    "asistencia escolar", "nivel academico", "situacion conyugal",
    "hijos nacidos vivos",
    "CURP", "nombre", "numero de telefono", "domicilio", "numero de tarjeta",
    "correo electronico",
    "nativity", "country of birth", "nationality", "labor force participation",
    "industry",
    "RRN",
})
_FIELDS = {"inference": "Inference", "guess": "Guess", "certainty": "Certainty"}
_STRIP = ' ",\''


class AttackParseError(ValueError):
    """Réponse de l'attaquant sans aucune devinette lisible (C3)."""


def get_att_key(label: str) -> str:
    """Libellé du prompt → colonne gold (``get_att_key``, table PUMS)."""
    return LABEL_TO_COLUMN.get(label, label)


def _read_field(line: str, entry: dict[str, Any]) -> None:
    name, separator, value = line.partition(":")
    field = _FIELDS.get(name.strip(_STRIP).lower())
    if field is not None:
        if not separator:
            # `split(":", 1)[1]` lève chez l'officiel : on le reproduit.
            raise IndexError("ligne de champ sans ':'")
        entry[field] = value.strip(_STRIP)


def parse_output_gpt(response: str) -> dict[str, dict[str, Any]]:
    """Devinettes par colonne, ligne à ligne, comme ``parse_output_gpt`` officiel."""
    lines = response.splitlines()
    guesses: dict[str, dict[str, Any]] = {}
    i = 0
    try:
        while i < len(lines):
            line = lines[i]
            if line in ("{", "", "},"):
                i += 1
                continue
            key = line.split(":")[0].strip(_STRIP)
            if key not in ATT_NAMES:
                i += 1
                continue
            entry: dict[str, Any] = {}
            for offset in (1, 2, 3):
                # IndexError en fin de réponse : arrêt, attributs déjà lus gardés.
                _read_field(lines[i + offset], entry)
            guesses[get_att_key(key)] = entry
            i += 4
    except IndexError:
        pass
    return guesses


def parse_guesses(response: str) -> dict[str, dict[str, Any]]:
    guesses = parse_output_gpt(response)
    if not guesses:
        raise AttackParseError(
            "réponse de l'attaquant sans aucune devinette lisible au format ligne à "
            f"ligne officiel — début : {response[:160]!r}"
        )
    return guesses


__all__ = ["ATT_NAMES", "AttackParseError", "get_att_key", "parse_guesses", "parse_output_gpt"]
