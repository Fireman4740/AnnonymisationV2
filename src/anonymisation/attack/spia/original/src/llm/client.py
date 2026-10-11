"""Cale de transport pour le code SPIA original (``src/llm/client.py``).

Seul fichier NON recopié tel quel. L'original instancie les SDK OpenAI,
Anthropic et Ollama à l'import et lit ses clés dans ``.env`` ; ici le
transport passe par le client du projet (cache obligatoire, réponse vide ou
tronquée = erreur, SPEC-10 C3). Tout le reste est conservé :

* les imports de prompts, à l'identique ;
* les six fonctions qui construisent les prompts et appellent le modèle,
  extraites **mot pour mot** de l'original (sha256 6c9a6e944eff9afa373886de974334ecead673445e865873efccfecadfbd3b5a) ;
* la température par défaut de ``call_api_with_param`` (0,1) et le passage
  des paramètres ``max_tokens`` éventuels.

``call_api_with_param`` délègue à un transport installé par
:func:`anonymisation.attack.spia.runner.spia_transport`. Les exceptions
qu'avale le code original (``except Exception`` → score 0 ou repli) sont
**journalisées** par le transport : le runner les compte et classe le
document en erreur plutôt que de laisser une panne devenir « non inféré ».
"""
import re
import warnings

from config.prompts.analysis_subjects import ANALYSIS_AND_COUNT_SUBJECTS_TAB, ANALYSIS_AND_COUNT_SUBJECTS_PANORAMA
from config.prompts.annotate_pii import ANNOTATE_CODE_PII, ANNOTATE_NON_CODE_PII
from config.prompts.align_subjects import ALIGN_SUBJECTS_ACROSS_ANNOTATIONS, ALIGN_SUBJECTS_ACROSS_ANNOTATIONS_ANON
from config.prompts.eval_annotation_agreement import EVALUATE_ANNOTATION_AGREEMENT_GT, EVALUATE_ANNOTATION_AGREEMENT_AB

#: Transport installé par le runner : ``callable(prompt, temperature, max_tokens) -> str``.
_TRANSPORT = None


def install_transport(transport):
    global _TRANSPORT
    _TRANSPORT = transport


def set_api_provider(provider, model):
    """Sans effet : le modèle est fixé par le backend du projet (lock d'attaque)."""


def call_api_with_param(prompt, **kwargs):
    """Transport du projet ; température par défaut 0,1 comme l'original."""
    if _TRANSPORT is None:
        raise RuntimeError("transport SPIA non installé (anonymisation.attack.spia.runner)")
    return _TRANSPORT(prompt, kwargs.get("temperature", 0.1), kwargs.get("max_tokens"))


def fix_json_with_llm(malformed_response, error_message):
    """
    Ask LLM to fix malformed JSON response.

    Args:
        malformed_response: The original malformed JSON string
        error_message: The parsing error message

    Returns:
        tuple: (status, fixed_response)
            - status: "success" or "error"
            - fixed_response: Fixed JSON string or error message
    """
    try:
        # Create a prompt asking the LLM to fix the JSON
        fix_prompt = f"""The following response has a JSON formatting error. Please fix it to be valid JSON with proper double quotes (") for all field names and string values.

Original Response:
{malformed_response}

Error:
{error_message}

Requirements:
1. All field names MUST use double quotes (")
2. All string values MUST use double quotes (")
3. Remove any extra text that is not part of the JSON
4. Ensure all brackets are properly closed
5. Output ONLY the fixed JSON, nothing else

Fixed JSON:"""

        fixed_response = call_api_with_param(fix_prompt)

        # Clean the response
        fixed_response = fixed_response.strip()
        fixed_response = fixed_response.replace("```json", "")
        fixed_response = fixed_response.replace("```", "")
        fixed_response = fixed_response.strip()

        return "success", fixed_response

    except Exception as e:
        return "error", f"Failed to fix JSON with LLM: {str(e)}"


def get_subjects_analysis(text, dataset_type="tab"):
    """Get subjects analysis using dataset-specific prompt

    Args:
        text: The text to analyze
        dataset_type: "tab" for TAB/ECHR data, "panorama" for PANORAMA data

    Returns:
        tuple: (status, response)
    """
    try:
        if dataset_type.lower() == "panorama":
            prompt = ANALYSIS_AND_COUNT_SUBJECTS_PANORAMA.format(text=text)
        else:  # default to TAB
            prompt = ANALYSIS_AND_COUNT_SUBJECTS_TAB.format(text=text)
        response = call_api_with_param(prompt)
        return "success", response
    except Exception as e:
        return "error", f"error: {str(e)}"


def get_subject_profiling_code(text, subjects_analysis_result):
    """Get subject profiling for code-based PII (structured identifiers)."""
    try:
        # Example result_format for the prompt
        result_format = [
            {"id": 0, "description": "Subject description", "PIIs": [
                {"tag": "IDENTIFICATION_NUMBER", "keyword": "ID-123", "certainty": 5},
                {"tag": "PHONE_NUMBER", "keyword": "+1-555-0100", "certainty": 5}
            ]}
        ]
        prompt = ANNOTATE_CODE_PII.format(
            text=text,
            result_of_subjects_analysis=subjects_analysis_result,
            result_format=result_format
        )
        response = call_api_with_param(prompt)
        return "success", response
    except Exception as e:
        return "error", f"error: {str(e)}"


def get_subject_profiling_non_code(text, subjects_analysis_result):
    """Get subject profiling for non-code PII (demographic/social attributes)."""
    try:
        # Example result_format for the prompt
        result_format = [
            {"id": 0, "description": "Subject description", "PIIs": [
                {"tag": "NAME", "keyword": "John Doe", "certainty": 5},
                {"tag": "OCCUPATION", "keyword": "Engineer", "certainty": 4}
            ]}
        ]
        prompt = ANNOTATE_NON_CODE_PII.format(
            text=text,
            result_of_subjects_analysis=subjects_analysis_result,
            result_format=result_format
        )
        response = call_api_with_param(prompt)
        return "success", response
    except Exception as e:
        return "error", f"error: {str(e)}"


def get_alignment_analysis(text, annotation_a, annotation_b, anonymized_text=None):
    """
    Get subject alignment analysis across two annotations

    Args:
        text (str): The document text (original text)
        annotation_a (list): List of subjects from annotation A (GT, based on original text)
        annotation_b (list): List of subjects from annotation B (LLM, based on original or anonymized text)
        anonymized_text (str): Anonymized text. If provided, uses anon prompt template.

    Returns:
        tuple: (status, response) where status is "success" or "error"
    """
    try:
        # Format annotations for prompt
        def format_annotation(subjects):
            lines = []
            for subj in subjects:
                lines.append(f"Subject ID: {subj['id']}")
                lines.append(f"Description: {subj.get('description', '')}")
                lines.append("PIIs:")
                for pii in subj.get('PIIs', []):
                    if pii.get('keyword') and pii.get('certainty', 0) > 0:
                        lines.append(f"  - {pii['tag']}: {pii['keyword']} (certainty: {pii['certainty']})")
                lines.append("")
            return "\n".join(lines)

        annotation_a_str = format_annotation(annotation_a)
        annotation_b_str = format_annotation(annotation_b)

        # Auto-detect prompt type based on anonymized_text presence
        if anonymized_text is not None:
            prompt_template = ALIGN_SUBJECTS_ACROSS_ANNOTATIONS_ANON
            prompt = prompt_template.format(
                original_text=text,
                anonymized_text=anonymized_text,
                annotation_a=annotation_a_str,
                annotation_b=annotation_b_str
            )
        else:
            prompt_template = ALIGN_SUBJECTS_ACROSS_ANNOTATIONS
            prompt = prompt_template.format(
                text=text,
                annotation_a=annotation_a_str,
                annotation_b=annotation_b_str
            )

        response = call_api_with_param(prompt)
        return "success", response
    except Exception as e:
        return "error", f"error: {str(e)}"


def get_annotation_agreement_evaluation(keyword_a, keyword_b, evaluation_mode="inter_annotator"):
    """
    Evaluate annotation agreement between two keywords using LLM

    Args:
        keyword_a (str): First keyword (ground truth or Annotator A)
        keyword_b (str): Second keyword (prediction or Annotator B)
        evaluation_mode (str): "ground_truth" or "inter_annotator" (default)

    Returns:
        str: Raw LLM response text
    """
    # Select appropriate prompt based on evaluation mode
    if evaluation_mode == "ground_truth":
        prompt_template = EVALUATE_ANNOTATION_AGREEMENT_GT
    else:
        prompt_template = EVALUATE_ANNOTATION_AGREEMENT_AB

    try:
        prompt = prompt_template.format(
            keyword_a=keyword_a,
            keyword_b=keyword_b
        )
        response = call_api_with_param(prompt)
        return response
    except Exception as e:
        raise RuntimeError(f"LLM evaluation failed: {str(e)}")
