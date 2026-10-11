"""
Parser for annotation agreement evaluation LLM responses
"""


def parse_agreement_response(response: str) -> str:
    """
    Parse LLM response for annotation agreement evaluation

    Args:
        response: Raw LLM response text

    Returns:
        One of: "yes", "no", "less precise"
    """
    if not response:
        return "no"

    response_lower = response.strip().lower()

    # Direct matches
    if "yes" in response_lower and "no" not in response_lower:
        return "yes"
    elif "less precise" in response_lower:
        return "less precise"
    elif "no" in response_lower:
        return "no"

    # Fallback to first word
    first_word = response_lower.split()[0] if response_lower.split() else ""
    if first_word in ["yes", "no"]:
        return first_word

    # Default to no if unclear
    return "no"
