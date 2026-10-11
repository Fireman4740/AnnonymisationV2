"""
PII Protection Rate (IPR/CPR) Calculator

Calculates the proposed privacy evaluation metrics from gt_vs_llm evaluation results:
- IPR (Individual Protection Rate): Subject-wise average protection rate = (1/N) * Σ(1 - S_i/A_i)
- CPR (Collective Protection Rate): Overall PII protection rate = 1 - (ΣS_i / ΣA_i)

Where:
- N: Total number of subjects
- A_i: Number of GT PII attributes for subject i
- S_i: Sum of agreement scores for subject i (1.0=match, 0.5=less_precise, 0.0=mismatch)

Usage:
    # Single file evaluation
    python src/evaluate/privacy/calculate_ipr_cpr.py --input_file data/spia/gt_vs_llms/panorama_gt_vs_llm_evaluation.json

    # Process all files in a directory
    python src/evaluate/privacy/calculate_ipr_cpr.py --input_dir data/spia/gt_vs_llms

    # Process all files in default directories
    python src/evaluate/privacy/calculate_ipr_cpr.py
"""

import argparse
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class SubjectMetrics:
    """Metrics for a single subject"""
    subject_id: int
    num_pii: int  # A_i: Total number of GT PII attributes
    score_sum: float  # S_i: Sum of agreement scores
    protection_rate: float  # P_i = 1 - S_i/A_i


@dataclass
class PPRResult:
    """IPR/CPR calculation result"""
    ipr: float  # Individual Protection Rate: Subject-wise average (1/N) * Σ(1 - S_i/A_i)
    cpr: float  # Collective Protection Rate: Overall 1 - (ΣS_i / ΣA_i)
    total_subjects: int  # N
    total_pii: int  # ΣA_i
    total_score: float  # ΣS_i
    by_tag: Dict[str, Dict[str, float]]  # Per-tag CPR metrics
    subject_metrics: List[SubjectMetrics]  # Per-subject details


def load_evaluation_json(filepath: str) -> Dict:
    """Load evaluation JSON file"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def calculate_subject_metrics(subject: Dict, min_certainty: int = 3) -> Optional[SubjectMetrics]:
    """
    Calculate metrics for a single subject.

    Args:
        subject: Subject data containing evaluations
        min_certainty: Minimum certainty threshold for including a PII attribute

    Returns:
        SubjectMetrics or None if no valid PII attributes
    """
    evaluations = subject.get("evaluations", {})

    if not evaluations:
        return None

    num_pii = 0  # A_i
    score_sum = 0.0  # S_i

    for tag, eval_data in evaluations.items():
        certainty_a = eval_data.get("certainty_A", 0)

        # Only include attributes that meet minimum certainty threshold
        if certainty_a >= min_certainty:
            num_pii += 1
            score_sum += eval_data.get("agreement_score", 0.0)

    if num_pii == 0:
        return None

    # P_i = 1 - S_i / A_i
    protection_rate = 1.0 - (score_sum / num_pii)

    return SubjectMetrics(
        subject_id=subject.get("subject_id", 0),
        num_pii=num_pii,
        score_sum=score_sum,
        protection_rate=protection_rate
    )


def calculate_ipr_cpr(evaluation_data: Dict, min_certainty: int = 3) -> PPRResult:
    """
    Calculate IPR and CPR from evaluation data.

    Args:
        evaluation_data: Loaded evaluation JSON with detailed_results
        min_certainty: Minimum certainty threshold (default 3)

    Returns:
        PPRResult with computed metrics (IPR, CPR)
    """
    # Note: min_certainty is now a parameter only, not from config
    # All certainty levels are recorded in evaluation, filtering is done here

    detailed_results = evaluation_data.get("detailed_results", [])

    all_subject_metrics: List[SubjectMetrics] = []

    # Track per-tag metrics
    tag_num_pii: Dict[str, int] = {}
    tag_score_sum: Dict[str, float] = {}

    for doc in detailed_results:
        subjects = doc.get("subjects", [])

        for subject in subjects:
            metrics = calculate_subject_metrics(subject, min_certainty)
            if metrics:
                all_subject_metrics.append(metrics)

            # Collect per-tag statistics
            evaluations = subject.get("evaluations", {})
            for tag, eval_data in evaluations.items():
                certainty_a = eval_data.get("certainty_A", 0)
                if certainty_a >= min_certainty:
                    if tag not in tag_num_pii:
                        tag_num_pii[tag] = 0
                        tag_score_sum[tag] = 0.0
                    tag_num_pii[tag] += 1
                    tag_score_sum[tag] += eval_data.get("agreement_score", 0.0)

    # Calculate overall metrics
    total_subjects = len(all_subject_metrics)
    total_pii = sum(m.num_pii for m in all_subject_metrics)
    total_score = sum(m.score_sum for m in all_subject_metrics)

    # IPR: Individual Protection Rate = (1/N) * Σ P_i = (1/N) * Σ(1 - S_i/A_i)
    if total_subjects > 0:
        ipr = sum(m.protection_rate for m in all_subject_metrics) / total_subjects
    else:
        ipr = 0.0

    # CPR: Collective Protection Rate = 1 - (ΣS_i / ΣA_i)
    if total_pii > 0:
        cpr = 1.0 - (total_score / total_pii)
    else:
        cpr = 0.0

    # Calculate per-tag CPR
    by_tag = {}
    for tag in tag_num_pii:
        if tag_num_pii[tag] > 0:
            tag_cpr = 1.0 - (tag_score_sum[tag] / tag_num_pii[tag])
            by_tag[tag] = {
                "cpr": tag_cpr,
                "num_pii": tag_num_pii[tag],
                "score_sum": tag_score_sum[tag]
            }

    return PPRResult(
        ipr=ipr,
        cpr=cpr,
        total_subjects=total_subjects,
        total_pii=total_pii,
        total_score=total_score,
        by_tag=by_tag,
        subject_metrics=all_subject_metrics
    )


def detect_dataset_type(filepath: str) -> str:
    """Detect dataset type from file path."""
    if "/PANORAMA/" in filepath:
        return "PANORAMA"
    elif "/TAB/" in filepath:
        return "TAB"
    else:
        raise ValueError(f"Cannot detect dataset type from path: {filepath}")


def normalize_model_name(model: str) -> str:
    """Normalize model name for consistent filenames (replace special chars)."""
    return model.replace(":", "-").replace(".", "-")


def parse_evaluation_filename(filepath: str) -> Dict[str, str]:
    """
    Parse evaluation filename to extract baseline, model, and dataset size info.

    Example: panorama_gt_vs_llm_panorama_anon_adversarial_gemma3_27b_evaluation.json
    """
    filename = Path(filepath).stem

    # Remove common suffixes
    name = filename.replace("_evaluation", "")

    info = {
        "filename": filename,
        "baseline": "unknown",
        "model": "unknown",
        "dataset_size": "unknown"
    }

    # Set dataset size based on dataset type
    if "panorama" in name.lower():
        info["dataset_size"] = "151"
    elif "tab" in name.lower():
        info["dataset_size"] = "144"

    # Parse baseline
    if "adversarial" in name:
        info["baseline"] = "adversarial"
    elif "deid_gpt" in name:
        info["baseline"] = "deid_gpt"
    elif "dp_prompt" in name:
        info["baseline"] = "dp_prompt"
    elif "longformer" in name:
        info["baseline"] = "longformer"

    # Parse model (order matters - check more specific patterns first)
    if "gemma3_27b" in name or "gemma3-27b" in name:
        info["model"] = "gemma3-27b"
    elif "gpt_4_1_mini" in name or "gpt4_mini" in name or "gpt-4.1-mini" in name or "gpt-4-1-mini" in name:
        info["model"] = "gpt-4-1-mini"
    elif "gpt_4_1" in name or "gpt4" in name or "gpt-4.1" in name or "gpt-4-1" in name:
        info["model"] = "gpt-4-1"
    elif "claude_sonnet" in name or "claude-sonnet" in name:
        info["model"] = "claude-sonnet-4-5"
    elif "claude_haiku" in name or "claude-haiku" in name:
        info["model"] = "claude-haiku-4-5"
    elif "llama3_8b" in name or "llama3-8b" in name:
        info["model"] = "llama3-1-8b"
    elif "stablelm_7b" in name or "stablelm-7b" in name:
        info["model"] = "stablelm-7b"
    elif "longformer" in name and info["baseline"] == "longformer":
        info["model"] = "longformer"

    return info


def save_results(result: PPRResult, input_file: str, output_dir: Path,
                 file_info: Dict[str, str], dataset_type: str) -> str:
    """Save PPR results to JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract components for filename
    dataset_lower = dataset_type.lower()  # panorama or tab
    dataset_size = file_info.get("dataset_size", "unknown")
    baseline = file_info.get("baseline", "unknown")
    model = file_info.get("model", "unknown")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Generate standardized output filename
    # Format: ppr_{dataset}_{size}_{baseline}_{model}_{timestamp}.json
    output_filename = f"ppr_{dataset_lower}_{dataset_size}_{baseline}_{model}_{timestamp}.json"
    output_path = output_dir / output_filename

    # Build output data
    output_data = {
        "metadata": {
            "input_file": input_file,
            "dataset": dataset_type,
            "dataset_size": dataset_size,
            "baseline": baseline,
            "model": model,
            "evaluation_timestamp": timestamp
        },
        "results": {
            "ipr_subject_avg": result.ipr,
            "cpr_overall": result.cpr,
            "total_subjects": result.total_subjects,
            "total_pii": result.total_pii,
            "total_score": result.total_score,
            "by_tag": result.by_tag
        }
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    return str(output_path)


def get_evaluation_files_from_dir(input_dir: str) -> List[str]:
    """Get all evaluation files from a specific directory."""
    dir_path = Path(input_dir)
    if not dir_path.exists():
        raise ValueError(f"Directory not found: {input_dir}")

    files = [str(f) for f in dir_path.glob("*_evaluation.json")]
    if not files:
        raise ValueError(f"No *_evaluation.json files found in: {input_dir}")

    return sorted(files)


def process_single_file(input_file: str, verbose: bool = True) -> Tuple[PPRResult, str]:
    """Process a single evaluation file."""
    # Load and process
    data = load_evaluation_json(input_file)
    result = calculate_ipr_cpr(data)

    # Detect dataset and parse info
    dataset_type = detect_dataset_type(input_file)
    file_info = parse_evaluation_filename(input_file)

    # Determine output directory
    if dataset_type == "TAB":
        output_dir = Path("data/spia/evaluation/tab")
    else:
        output_dir = Path("data/spia/evaluation/panorama")

    # Save results
    output_path = save_results(result, input_file, output_dir, file_info, dataset_type)

    if verbose:
        print(f"\n{'='*60}")
        print(f"File: {Path(input_file).name}")
        print(f"Dataset: {dataset_type} | Baseline: {file_info['baseline']} | Model: {file_info['model']}")
        print(f"{'='*60}")
        print(f"IPR (Subject-avg): {result.ipr:.4f}")
        print(f"CPR (Overall):     {result.cpr:.4f}")
        print(f"Total Subjects: {result.total_subjects}")
        print(f"Total PII: {result.total_pii} | Total Score: {result.total_score:.1f}")
        print(f"\nBy Tag:")
        for tag, metrics in sorted(result.by_tag.items()):
            print(f"  {tag}: CPR={metrics['cpr']:.4f} (n={metrics['num_pii']}, score={metrics['score_sum']:.1f})")
        print(f"\nSaved to: {output_path}")

    return result, output_path


def process_directory(input_dir: str, verbose: bool = True) -> List[Dict]:
    """Process all evaluation files in a directory."""
    files = get_evaluation_files_from_dir(input_dir)

    print(f"Found {len(files)} evaluation files in {input_dir}")

    results_summary = []

    for input_file in files:
        try:
            result, output_path = process_single_file(input_file, verbose=verbose)
            file_info = parse_evaluation_filename(input_file)

            results_summary.append({
                "file": Path(input_file).name,
                "baseline": file_info["baseline"],
                "model": file_info["model"],
                "ipr": result.ipr,
                "cpr": result.cpr,
                "output": output_path
            })
        except Exception as e:
            print(f"Error processing {input_file}: {e}")

    # Print summary table
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"{'Baseline':<15} {'Model':<20} {'IPR':>8} {'CPR':>8}")
    print("-"*55)
    for r in sorted(results_summary, key=lambda x: (x["baseline"], x["model"])):
        print(f"{r['baseline']:<15} {r['model']:<20} {r['ipr']:>8.4f} {r['cpr']:>8.4f}")

    return results_summary


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Calculate IPR/CPR (Individual/Collective Protection Rate) metrics from evaluation results"
    )
    parser.add_argument(
        "--input_file",
        type=str,
        help="Path to single evaluation JSON file",
    )
    parser.add_argument(
        "--input_dir",
        type=str,
        help="Path to directory containing *_evaluation.json files (processes all files in directory)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress verbose output",
    )
    return parser.parse_args()


def process_all_default_directories(verbose: bool = True) -> Dict[str, List[Dict]]:
    """Process all evaluation files in default directories."""
    default_dirs = [
        "data/spia/gt_vs_llms/panorama",
        "data/spia/gt_vs_llms/tab"
    ]

    all_results = {}

    for input_dir in default_dirs:
        dir_path = Path(input_dir)
        if not dir_path.exists():
            print(f"Directory not found, skipping: {input_dir}")
            continue

        dataset_name = "PANORAMA" if "PANORAMA" in input_dir else "TAB"
        print(f"\n{'='*80}")
        print(f"Processing {dataset_name}")
        print(f"{'='*80}")

        try:
            results = process_directory(input_dir, verbose=verbose)
            all_results[dataset_name] = results
        except ValueError as e:
            print(f"Skipping {dataset_name}: {e}")

    return all_results


def main():
    """Main entry point."""
    args = parse_args()

    if args.input_dir:
        process_directory(args.input_dir, verbose=not args.quiet)
    elif args.input_file:
        process_single_file(args.input_file, verbose=not args.quiet)
    else:
        # Default: process all files in PANORAMA and TAB directories
        process_all_default_directories(verbose=not args.quiet)


if __name__ == "__main__":
    main()
