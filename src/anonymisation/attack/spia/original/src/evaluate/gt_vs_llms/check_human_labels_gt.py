"""
SPIA Human Label Checker
Evaluates inter-annotator agreement with rule/model/human fallback
Outputs evaluation results as JSON artifacts for further analysis
"""

import json
import re
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import os
from src.common_utils import load_jsonl_data
from src.evaluate.eval_utils import compare_pii_keywords, get_human_evaluation
from src.llm.client import get_annotation_agreement_evaluation
from src.llm.parser.annotation_agreement_parser import parse_agreement_response
from src.evaluate.calculate_inference_accuracy import calculate_statistics, print_statistics_summary, build_case_logs, print_case_logs


# ==================== LLM & Human Evaluation ====================

def get_model_evaluation(keyword_a: str, keyword_b: str, tag: str) -> str:
    """
    Use LLM to evaluate if two keywords match (GT evaluation mode)

    Args:
        keyword_a: Ground truth keyword
        keyword_b: LLM prediction keyword
        tag: PII tag type

    Returns:
        "yes", "no", or "less precise"
    """
    response = get_annotation_agreement_evaluation(keyword_a, keyword_b, "ground_truth")
    return parse_agreement_response(response)


def evaluate_with_fallback(keyword_a: str, keyword_b: str, tag: str, auto_score: float,
                          decider: str = "rule") -> tuple[float, str]:
    """
    Evaluate with fallback mechanism based on decider mode (GT evaluation)

    Args:
        keyword_a: Ground truth keyword
        keyword_b: LLM prediction keyword
        tag: PII tag type
        auto_score: Score from automatic rule-based evaluation
        decider: Evaluation strategy ("rule", "rule_model", "rule_model_human")

    Returns:
        tuple: (final_score, evaluation_method)
            - final_score: 0.0, 0.5, or 1.0
            - evaluation_method: "RULE", "MODEL", "HUMAN"
    """
    # If automatic evaluation succeeded, use it
    if auto_score > 0:
        return auto_score, "RULE"

    # Automatic evaluation failed (score = 0)
    if decider == "rule":
        return 0.0, "RULE"

    # Try model evaluation
    if decider in ["rule_model", "rule_model_human"]:
        try:
            model_result = get_model_evaluation(keyword_a, keyword_b, tag)
            if model_result == "yes":
                return 1.0, "MODEL"
            elif model_result == "less precise":
                return 0.5, "MODEL"
            elif model_result == "no":
                return 0.0, "MODEL"

            # If model gave unclear answer and we have human fallback
            if decider == "rule_model_human":
                human_result = get_human_evaluation(keyword_a, keyword_b, tag)
                if human_result == "yes":
                    return 1.0, "HUMAN"
                elif human_result == "less precise":
                    return 0.5, "HUMAN"
                else:
                    return 0.0, "HUMAN"

            return 0.0, "MODEL"  # Default if model unclear
        except Exception as e:
            print(f"  [ERROR] Model evaluation failed: {e}")
            if decider == "rule_model_human":
                # Fall back to human
                human_result = get_human_evaluation(keyword_a, keyword_b, tag)
                if human_result == "yes":
                    return 1.0, "HUMAN"
                elif human_result == "less precise":
                    return 0.5, "HUMAN"
                else:
                    return 0.0, "HUMAN"
            return 0.0, "MODEL"

    return 0.0, "RULE"


# ==================== Evaluation Functions ====================

def evaluate_subject_annotations(subject, config):
    """
    Evaluate GT (annotation_A) vs LLM (annotation_B) agreement for a subject
    Evaluates ALL tags present in GT (regardless of certainty)
    Each result includes certainty_A for filtering in statistics by certainty level
    """
    results = {}

    # Get ALL tags from GT (annotation_A) with non-empty keywords
    all_tags = set()
    for ann in subject["annotation_A"]:
        if ann.get("keyword"):  # Non-empty keyword
            all_tags.add(ann["tag"])

    # Filter tags if specified
    if config["tags_to_evaluate"]:
        all_tags = all_tags.intersection(set(config["tags_to_evaluate"]))

    for tag in all_tags:
        # GT annotations (all with non-empty keywords)
        anns_a = [a for a in subject["annotation_A"]
                  if a.get("tag") == tag and a.get("keyword")]
        # LLM annotations (no certainty filter)
        anns_b = [b for b in subject["annotation_B"]
                  if b.get("tag") == tag and b.get("certainty", 0)]

        # Skip if no valid GT annotations
        if not anns_a:
            continue

        # If GT has tag but LLM doesn't, it's a mismatch
        if not anns_b:
            results[tag] = {
                "keyword_A": anns_a[0]["keyword"],
                "keyword_B": "",
                "certainty_A": anns_a[0]["certainty"],
                "certainty_B": 0,
                "hardness_A": anns_a[0]["hardness"],
                "hardness_B": 0,
                "agreement_score": 0.0,
                "evaluation_method": "RULE",
                "match": False,
                "less_precise": False,
                "mismatch": True
            }
            continue

        # Find best matching pair among all GT-LLM combinations
        best_result = None
        best_score = -1.0

        for ann_a in anns_a:
            # Compare with all LLM annotations and find best match
            for ann_b in anns_b:
                # Step 1: Automatic rule-based comparison
                auto_score = compare_pii_keywords(
                    ann_a["keyword"],
                    ann_b["keyword"],
                    tag,
                    location_max_depth=config.get("location_max_depth", None)
                )

                # Step 2 & 3: Fallback evaluation (model/human) if needed
                final_score, evaluation_method = evaluate_with_fallback(
                    ann_a["keyword"],
                    ann_b["keyword"],
                    tag,
                    auto_score,
                    config.get("decider", "rule")
                )

                # Update best result if this is better
                if final_score > best_score:
                    best_score = final_score
                    best_result = {
                        "keyword_A": ann_a["keyword"],
                        "keyword_B": ann_b["keyword"],
                        "certainty_A": ann_a["certainty"],
                        "certainty_B": ann_b["certainty"],
                        "hardness_A": ann_a["hardness"],
                        "hardness_B": ann_b["hardness"],
                        "agreement_score": final_score,
                        "evaluation_method": evaluation_method,
                        "match": final_score >= 1.0,
                        "less_precise": 0.0 < final_score < 1.0,
                        "mismatch": final_score == 0.0
                    }

        # Save best result for this tag
        if best_result:
            results[tag] = best_result

    return results


def process_subject_wrapper(subject_data, config):
    """
    Wrapper function for parallel processing of subject annotations

    Args:
        subject_data: Dict with subject information and data_id
        config: Configuration dictionary

    Returns:
        Dict with subject_id, description, evaluations, and data_id for reassembly
    """
    try:
        evaluations = evaluate_subject_annotations({
            "id": subject_data["id"],
            "description": subject_data["description"],
            "annotation_A": subject_data["annotation_A"],
            "annotation_B": subject_data["annotation_B"]
        }, config)

        return {
            "data_id": subject_data["data_id"],
            "subject_id": subject_data["id"],
            "description": subject_data["description"],
            "evaluations": evaluations,
            "doc_index": subject_data["doc_index"],
            "subject_index": subject_data["subject_index"]
        }
    except Exception as e:
        print(f"\n[ERROR] Failed to process subject {subject_data['id']}: {e}")
        return {
            "data_id": subject_data["data_id"],
            "subject_id": subject_data["id"],
            "description": subject_data["description"],
            "evaluations": {},
            "doc_index": subject_data["doc_index"],
            "subject_index": subject_data["subject_index"],
            "error": str(e)
        }


# ==================== Main Evaluation ====================

def evaluate_annotations(input_file, output_file, config):
    """
    Main evaluation function with parallel processing for LLM evaluation
    Outputs evaluation results as JSON artifact
    """
    # Load JSONL data
    documents = load_jsonl_data(input_file)

    # Extract alignment metadata from first document (added by align_subject_based_ground_truth.py)
    alignment_stats = None
    if documents and "metadata" in documents[0]:
        metadata = documents[0]["metadata"]
        if "alignment_summary" in metadata:
            alignment_stats = metadata["alignment_summary"]

    # Prepare all subjects for parallel processing
    all_subjects = []
    for doc_idx, data in enumerate(documents):
        for subj_idx, subject in enumerate(data["subjects"]):
            subject_data = {
                "id": subject["id"],
                "description": subject["description"],
                "annotation_A": subject["PIIs"]["annotation_A"],
                "annotation_B": subject["PIIs"]["annotation_B"],
                "data_id": data["metadata"]["data_id"],
                "doc_index": doc_idx,
                "subject_index": subj_idx
            }
            all_subjects.append(subject_data)

    print(f"Processing {len(all_subjects)} subjects across {len(documents)} documents with {config.get('num_workers', 20)} workers...")

    # Process subjects in parallel
    results_map = {}
    with ThreadPoolExecutor(max_workers=config.get('num_workers', 20)) as executor:
        # Submit all tasks
        future_to_subject = {
            executor.submit(process_subject_wrapper, subject_data, config): subject_data
            for subject_data in all_subjects
        }

        # Process completed tasks with progress bar
        for future in tqdm(as_completed(future_to_subject), total=len(all_subjects), desc="Evaluating"):
            result = future.result()
            # Store result indexed by (doc_index, subject_index) for reassembly
            key = (result["doc_index"], result["subject_index"])
            results_map[key] = result

    # Reassemble results into original document structure
    all_results = []
    for doc_idx, data in enumerate(documents):
        doc_results = {
            "data_id": data["metadata"]["data_id"],
            "number_of_subjects": data["metadata"]["number_of_subjects"],
            "subjects": []
        }

        for subj_idx in range(len(data["subjects"])):
            key = (doc_idx, subj_idx)
            result = results_map.get(key)
            if result:
                doc_results["subjects"].append({
                    "subject_id": result["subject_id"],
                    "description": result["description"],
                    "evaluations": result["evaluations"]
                })
                if "error" in result:
                    print(f"[WARNING] Subject {result['subject_id']} had error: {result['error']}")

        all_results.append(doc_results)

    # Calculate statistics
    from src.evaluate.calculate_inference_accuracy import calculate_statistics, build_case_logs
    statistics = calculate_statistics(all_results)

    # Build case logs if requested
    case_logs = None
    if config.get('show_case_logs', True):
        case_logs = build_case_logs(all_results, filter_mode=config.get('case_log_filter', 'disagree'))

    # Save evaluation results as artifact with statistics and case logs
    # Build ordered dict to ensure field order: config, subject_alignment_statistics, pii_statistics, case_logs, detailed_results
    evaluation_data = {"config": config}

    # Add subject alignment statistics if available (before pii_statistics)
    if alignment_stats:
        evaluation_data["subject_alignment_statistics"] = alignment_stats

    evaluation_data["pii_statistics"] = statistics
    evaluation_data["case_logs"] = case_logs
    evaluation_data["detailed_results"] = all_results

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(evaluation_data, f, indent=2, ensure_ascii=False)

    print(f"\n✓ Evaluation complete. Results saved to: {output_file}")
    print(f"  Total documents: {len(all_results)}")
    total_subjects = sum(len(doc["subjects"]) for doc in all_results)
    print(f"  Total subjects: {total_subjects}")

    return evaluation_data

def parse_args():
    parser = argparse.ArgumentParser(
        description="Evaluate GT vs LLM annotations with configurable parameters",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Decider modes:
  rule            - Rule-based comparison only
  rule_model      - Rule → LLM evaluation for failures (default)
  rule_model_human - Rule → LLM → Human review for failures

Case log filters:
  all         - Show all evaluation cases
  low_score   - Show cases with score < 1.0 (default)
  mismatch    - Show only complete mismatches (score = 0.0)
        """
    )
    parser.add_argument("--input_file", type=str, required=True,
                        help="Input file from align_subject_based_ground_truth.py")
    parser.add_argument("--output_file", type=str, required=True,
                        help="Output JSON file for evaluation results")

    # Evaluation parameters
    parser.add_argument("--location_max_depth", type=int, default=4,
                        help="Max depth for LOCATION comparison (None=all levels)")
    parser.add_argument("--decider", type=str, default="rule_model",
                        choices=["rule", "rule_model", "rule_model_human"],
                        help="Evaluation strategy")
    parser.add_argument("--num_workers", type=int, default=20,
                        help="Number of parallel workers")
    parser.add_argument("--tags", type=str, nargs='+', default=None,
                        help="Specific tags to evaluate (default: all tags)")

    # LLM configuration (for rule_model and rule_model_human deciders)
    parser.add_argument("--api_provider", type=str, default="openai",
                        choices=["openai", "anthropic", "ollama"],
                        help="API provider for LLM evaluation")
    parser.add_argument("--model", type=str, default="gpt-4o-mini",
                        help="Model name for LLM evaluation")

    # Output control
    parser.add_argument("--show_case_logs", action="store_true", default=True,
                        help="Show individual case details")
    parser.add_argument("--no_case_logs", action="store_false", dest="show_case_logs",
                        help="Hide individual case details")
    parser.add_argument("--case_log_filter", type=str, default="disagree",
                        choices=["all", "disagree", "mismatch"],
                        help="Filter for case logs (disagree=score<1.0, mismatch=score=0.0)")

    return parser.parse_args()

# ==================== Main ====================

if __name__ == "__main__":
    args = parse_args()

    INPUT_FILE = args.input_file
    OUTPUT_FILE = args.output_file

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    # Configure LLM client if using model-based decider
    if args.decider in ["rule_model", "rule_model_human"]:
        from src.llm.client import set_api_provider
        set_api_provider(provider=args.api_provider, model=args.model)

    # Build config from arguments
    config = {
        "tags_to_evaluate": args.tags,
        "decider": args.decider,
        "location_max_depth": args.location_max_depth,
        "num_workers": args.num_workers,
        "show_case_logs": args.show_case_logs,
        "case_log_filter": args.case_log_filter,
        "api_provider": args.api_provider,
        "model": args.model
    }

    # Print configuration
    print(f"\n{'='*60}")
    print(f"GT Evaluation Configuration")
    print(f"{'='*60}")
    print(f"API Provider: {config['api_provider']}")
    print(f"Model: {config['model']}")
    print(f"Location max depth: {config['location_max_depth']}")
    print(f"Decider: {config['decider']}")
    print(f"Num workers: {config['num_workers']}")
    print(f"Tags filter: {config['tags_to_evaluate'] or 'All tags'}")
    print(f"{'='*60}\n")

    # Run evaluation
    evaluation_data = evaluate_annotations(INPUT_FILE, OUTPUT_FILE, config)

    # Calculate and display statistics
    statistics = calculate_statistics(evaluation_data["detailed_results"])
    print_statistics_summary(statistics)

    # Print case logs if requested
    if args.show_case_logs:
        case_logs = build_case_logs(evaluation_data["detailed_results"], filter_mode=args.case_log_filter)
        print_case_logs(case_logs, filter_mode=args.case_log_filter)
