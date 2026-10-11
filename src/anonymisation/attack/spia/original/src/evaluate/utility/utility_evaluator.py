"""
Utility Evaluation Module

Evaluates the utility of anonymized text by comparing it to the original text.
Based on the evaluation methods from "Language Models are Advanced Anonymizers".

Utility measures how well the anonymized text preserves the original meaning
while protecting privacy.
"""

from typing import Dict, Any, List, Optional
from nltk.translate.bleu_score import sentence_bleu as bleu, SmoothingFunction
from rouge_score import rouge_scorer
import json


class UtilityEvaluator:
    """
    Evaluates utility of anonymized text using multiple metrics.

    Metrics:
    - BLEU: N-gram overlap between original and anonymized text
    - ROUGE: Recall-oriented overlap (ROUGE-1, ROUGE-L, ROUGE-Lsum)
    - LLM-based: Readability, meaning preservation, hallucination detection
    """

    def __init__(
        self,
        api_provider: str = "openai",
        model: str = "gpt-4",
        use_llm_evaluation: bool = True
    ):
        """
        Initialize the utility evaluator.

        Args:
            api_provider: API provider for LLM-based evaluation
            model: Model to use for LLM-based evaluation
            use_llm_evaluation: Whether to use LLM-based evaluation (requires API)
        """
        self.api_provider = api_provider
        self.model = model
        self.use_llm_evaluation = use_llm_evaluation
        self.rouge_scorer = rouge_scorer.RougeScorer(
            ["rouge1", "rougeL", "rougeLsum"],
            use_stemmer=True
        )

    def compute_bleu(
        self,
        original_text: str,
        anonymized_text: str,
        smoothing_function=None
    ) -> float:
        """
        Compute BLEU score between original and anonymized text.

        Args:
            original_text: Original text
            anonymized_text: Anonymized text
            smoothing_function: NLTK smoothing function (default: method4)

        Returns:
            BLEU score (0-1, higher is more similar)
        """
        if smoothing_function is None:
            smoothing_function = SmoothingFunction().method4

        reference = [original_text.split()]
        hypothesis = anonymized_text.split()

        return bleu(reference, hypothesis, smoothing_function=smoothing_function)

    def compute_rouge(
        self,
        original_text: str,
        anonymized_text: str
    ) -> Dict[str, float]:
        """
        Compute ROUGE scores between original and anonymized text.

        Args:
            original_text: Original text
            anonymized_text: Anonymized text

        Returns:
            Dictionary with ROUGE-1, ROUGE-L, ROUGE-Lsum F1 scores
        """
        scores = self.rouge_scorer.score(original_text, anonymized_text)

        return {
            "rouge1": scores["rouge1"].fmeasure,
            "rougeL": scores["rougeL"].fmeasure,
            "rougeLsum": scores["rougeLsum"].fmeasure
        }

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Call LLM API for evaluation."""
        from src.llm.client import call_api_with_param, set_api_provider

        set_api_provider(self.api_provider, self.model)

        full_prompt = f"{system_prompt}\n\n{user_prompt}"
        response = call_api_with_param(full_prompt)

        return response

    def compute_llm_utility(
        self,
        original_text: str,
        anonymized_text: str
    ) -> Dict[str, Any]:
        """
        Compute LLM-based utility scores.

        Evaluates:
        - readability: Is the anonymized text readable? (1-10)
        - meaning: Does it preserve the original meaning? (1-10)
        - hallucinations: Does it contain new/invented information? (0 or 1)

        Args:
            original_text: Original text
            anonymized_text: Anonymized text

        Returns:
            Dictionary with readability, meaning, hallucinations scores and explanations
        """
        system_prompt = "You are an expert text similarity scorer that carefully compares two texts and gives a score based on how similar they are. You follow the instructions and format precisely and you try to give a score as close to the ground truth as possible."

        user_prompt = f"""You are a judge that must decide on a scale from 1-10 whether two texts, the original and the adapted, have the same meaning and content. 10 means they have exactly the same content and message while 1 means they are nothing alike. Before giving your final score give a brief step-by-step reasoning of your decision. Give your answer in the JSON format below:
{{
    "readability": {{
        "explanation": "<Is the adapted text as readable and understandable as the original text? Could a human read it without issues? Focus only on the adapted text without your knowledge of the original one.>",
        "score": <Number between 1 (unreadable) to 10 (equally readable as the original text)>
    }},
    "meaning": {{
        "explanation": "<Does the adapted text have the same meaning as the original text? Does it convey the same message?>",
        "score": <Number between 1 (different meaning) to 10 (same meaning)>
    }},
    "hallucinations": {{
        "explanation": "<Does the adapted text contain any information that was not present in the original text and that does not reflect the original text or did it correctly abstract and generalize the original text?>",
        "score": <Either 0 (contains new information) or 1 (contains no new information)>
    }}
}}

Original text:
{original_text}

Adapted text:
{anonymized_text}
"""

        response = self._call_llm(system_prompt, user_prompt)

        # Parse JSON response
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            result = json.loads(response[start:end])
        except (json.JSONDecodeError, ValueError):
            # Return default scores on parsing error
            result = {
                "readability": {"explanation": "parsing_error", "score": 1},
                "meaning": {"explanation": "parsing_error", "score": 1},
                "hallucinations": {"explanation": "parsing_error", "score": 0}
            }

        result["full_answer"] = response
        return result

    def evaluate(
        self,
        original_text: str,
        anonymized_text: str,
        include_llm: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Compute all utility metrics for anonymized text.

        Args:
            original_text: Original text before anonymization
            anonymized_text: Anonymized text
            include_llm: Whether to include LLM-based evaluation (overrides instance setting)

        Returns:
            Dictionary containing all utility scores:
            - bleu: BLEU score (0-1)
            - rouge: ROUGE scores dict
            - llm: LLM-based scores (if enabled)
            - utility_bleu: Same as bleu
            - utility_rouge: ROUGE-L F1 score
            - utility_readability: LLM readability score (1-10)
            - utility_meaning: LLM meaning score (1-10)
            - utility_hallucination: LLM hallucination score (0 or 1)
            - utility_model: Combined LLM score
            - utility_comb: Combined overall score
        """
        use_llm = include_llm if include_llm is not None else self.use_llm_evaluation

        # Compute BLEU
        bleu_score = self.compute_bleu(original_text, anonymized_text)

        # Compute ROUGE
        rouge_scores = self.compute_rouge(original_text, anonymized_text)
        rouge_l = rouge_scores["rougeL"]

        result = {
            "bleu": bleu_score,
            "rouge": rouge_scores,
            "utility_bleu": bleu_score,
            "utility_rouge": rouge_l
        }

        # Compute LLM-based scores if enabled
        if use_llm:
            llm_scores = self.compute_llm_utility(original_text, anonymized_text)

            readability = llm_scores.get("readability", {}).get("score", 1)
            meaning = llm_scores.get("meaning", {}).get("score", 1)
            hallucination = llm_scores.get("hallucinations", {}).get("score", 0)

            # Normalize to 0-1 range
            readability_norm = min(max(readability, 0), 10) / 10
            meaning_norm = min(max(meaning, 0), 10) / 10
            rouge_norm = min(max(rouge_l, 0), 1)

            # Compute combined scores (from plot_anonymized.py:678-686)
            utility_model = (readability_norm + meaning_norm) / 2
            utility_comb = (readability_norm + meaning_norm + rouge_norm) / 3

            result.update({
                "llm": llm_scores,
                "utility_readability": readability,
                "utility_meaning": meaning,
                "utility_hallucination": hallucination,
                "utility_model": utility_model,
                "utility_comb": utility_comb
            })
        else:
            # Without LLM, use ROUGE as combined utility
            result.update({
                "utility_model": None,
                "utility_comb": rouge_l  # Fallback to ROUGE-L
            })

        return result

    def evaluate_batch(
        self,
        pairs: List[Dict[str, str]],
        include_llm: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """
        Evaluate utility for multiple text pairs.

        Args:
            pairs: List of dicts with 'original' and 'anonymized' keys
            include_llm: Whether to include LLM-based evaluation

        Returns:
            List of evaluation results
        """
        results = []
        for pair in pairs:
            result = self.evaluate(
                pair["original"],
                pair["anonymized"],
                include_llm=include_llm
            )
            results.append(result)
        return results


def evaluate_utility(
    original_text: str,
    anonymized_text: str,
    api_provider: str = "openai",
    model: str = "gpt-4",
    use_llm: bool = True
) -> Dict[str, Any]:
    """
    Convenience function to evaluate utility of anonymized text.

    Args:
        original_text: Original text before anonymization
        anonymized_text: Anonymized text
        api_provider: API provider for LLM evaluation
        model: Model for LLM evaluation
        use_llm: Whether to use LLM-based evaluation

    Returns:
        Dictionary with all utility scores

    Example:
        >>> result = evaluate_utility(
        ...     original_text="I'm a 28-year-old engineer in San Francisco.",
        ...     anonymized_text="I'm a professional in a major city.",
        ...     use_llm=True
        ... )
        >>> print(f"BLEU: {result['utility_bleu']:.3f}")
        >>> print(f"ROUGE-L: {result['utility_rouge']:.3f}")
        >>> print(f"Combined: {result['utility_comb']:.3f}")
    """
    evaluator = UtilityEvaluator(
        api_provider=api_provider,
        model=model,
        use_llm_evaluation=use_llm
    )
    return evaluator.evaluate(original_text, anonymized_text)


