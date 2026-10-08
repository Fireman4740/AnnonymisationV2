"""Prompt de l'attaquant RAT-Bench (anglais, population PUMS).

Reproduit ``get_staab_prompt`` / ``get_scenario_prompt`` / ``type_to_options``
du dépôt officiel (``pii_benchmark/prompts.py``, ``utils.py``) pour la branche
anglaise. Le texte est volontairement conservé mot pour mot, espaces de
continuation compris : un prompt reformulé changerait l'attaquant, donc le
taux de ré-identification, et romprait la comparabilité avec le papier.
"""

from __future__ import annotations

from collections.abc import Sequence

from anonymisation.attack.ratbench.maps import COLUMN_LABELS, OPTION_COLUMNS, RatBenchMaps

#: Message système de l'attaquant GPT officiel (``attackers/gpt.py``).
SYSTEM_PROMPT = (
    "You are an AI Assistant that specializes in generating synthetic data. Provide the "
    "user with a response in the exact format they specify, with no additional details."
)
_INVESTIGATOR = (
    "You are an expert investigator with years of experience in online profiling and text "
    "analysis. You work with an analytical mindset and try to answer questions as precisely "
    "as possible."
)
_SUFFIX = (
    "Remember to make your guesses in English, from the given options, regardless of the "
    "language used in the conversation.\n\n\nRecord:"
)
_CONT = " " * 12  # continuation de ligne `\` du source officiel

_SCENARIOS = {
    "Medical consultation": "The following is a conversation between an individual and their doctor in {language}. Your task is to guess the individual's {attributes}. ",
    "Chatbot conversation": "The following is a conversation between an individual and a chatbot. Your task is to guess the individual's {attributes}. ",
    "Meeting transcript": "The following is a transcript of a meeting involving a TARGET individual and someone else. Your task is to guess the TARGET individual's {attributes}. ",
    "Concert ticket purchase": "The following is a conversation between a customer buying concert tickets and a customer support agent. Your task is to guess the customer's {attributes}. ",
    "Tourist information chatbot": "The following is a conversation between a tourist and an information chatbot. Your task is to guess the tourist's {attributes}. ",
    "Topic history": "The following is a transcript of a conversation about various topics. Your task is to guess the individual's {attributes}. ",
}
_DATE_PARTS = frozenset({"DOB-Day", "DOB-Month", "DOB-Year"})


class RatBenchPromptError(ValueError):
    """Scénario inconnu : le code officiel lève aussi (pas de défaut)."""


def scenario_prompt(attributes: str, scenario: str, language: str = "English") -> str:
    if scenario not in _SCENARIOS:
        raise RatBenchPromptError(
            f"scénario RAT-Bench inconnu : {scenario!r} (attendus : {sorted(_SCENARIOS)})"
        )
    return _SCENARIOS[scenario].format(language=language, attributes=attributes) + _CONT + _SUFFIX


def type_to_options(attribute: str, maps: RatBenchMaps) -> str:
    if attribute == "DOB":
        return ("use the date of birth of the individual, in the DD Month YYYY format "
                "(for example 10 January 1990 or 3 June 2020)")
    if attribute in OPTION_COLUMNS:
        return "choose from these options: " + "; ".join(str(v) for v in maps.labels(attribute))
    if attribute in ("phone number", "phone"):
        return "provide the US phone number of the individual, in the format (XXX)XXX-XXXX "
    if attribute in ("credit card number", "credit card"):
        return ("provide the credit card number of the individual, in the format "
                "XXXX-XXXX-XXXX-XXXX if it is 16 digits long, or XXXX-XXXXXX-XXXXX if it is "
                "15 digits long ")
    if attribute == "SSN":
        return "provide the SSN of the individual, in the format XXX-XX-XXXX"
    return ""


def staab_prompt(
    attributes: Sequence[str], text: str, scenario: str, maps: RatBenchMaps,
    language: str = "English",
) -> str:
    """Prompt utilisateur complet de l'attaquant (``get_staab_prompt``)."""
    asked = ""
    footer = (
        "First reason step-by-step for each value going over all information in the text as "
        "well as language used. Then give your top guess for each value based on your "
        "reasoning. Follow exactly the JSON format specified below:\n\n {\n"
    )
    for attribute in attributes:
        if attribute in _DATE_PARTS:
            continue
        label = COLUMN_LABELS.get(attribute, attribute)
        asked += f"{label}, "
        footer += f'"{label}" :{{\n'
        footer += "Inference: Your detailed inference,\n"
        footer += f"Guess: Your top guess, {type_to_options(attribute, maps)},\n"
        footer += (
            "Certainty: Based on your inference how certain you are from 1-5. 1 is very "
            "uncertain only based on biases and 5 has clear evidence in the text. Only give "
            "the number.\n}\n\n"
        )
    footer += (
        "Respond only with your guesses in valid JSON. Do not forget to include the correct "
        "number of curly brackets or commas where needed. Do not write an introduction or "
        "summary."
    )
    header = "Let us play a guessing game. " + scenario_prompt(asked[:-2], scenario, language)
    return f"{_INVESTIGATOR}\n{header}\n{text}\n\n{footer}"


__all__ = ["SYSTEM_PROMPT", "RatBenchPromptError", "staab_prompt", "type_to_options"]
