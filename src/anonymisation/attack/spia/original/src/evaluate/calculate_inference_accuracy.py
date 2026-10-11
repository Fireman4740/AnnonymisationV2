"""
SPIA Accuracy Calculator
Calculates evaluation metrics, logs cases, and generates reports
from check_human_labels_gt.py or check_human_labels_inter.py evaluation results
"""

import json
import sys
from collections import defaultdict
import argparse
from datetime import datetime

# ==================== Configuration ====================

# Input file from check_human_labels_gt.py or check_human_labels_inter.py output
# INPUT_FILE = "report/tab_cross_labeled_check_human_labels.json"
# INPUT_FILE = "report/tab_human_vs_claude_sonnet_4_20250514_check_human_labels.json"

# Output options
SHOW_CASE_LOGS = True  # Print individual case details
CASE_LOG_FILTER = "low_score"  # "all", "low_score" (< 1.0), "mismatch" (= 0.0)

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--data", type=str, default="tab", choices=["tab", "panorama"])
    parser.add_argument("-m", "--mode", type=str, default="gt", choices=["gt", "inter"])
    parser.add_argument("-dt", "--datetime", type=str, default=datetime.now().strftime('%Y%m%d'))
    return parser.parse_args()

# ==================== Data Loading ====================

def load_evaluation_results(json_path):
    """
    Load evaluation results from check_human_labels_gt.py or check_human_labels_inter.py output

    Args:
        json_path: Path to JSON file with evaluation results

    Returns:
        dict with 'config' and 'detailed_results' keys
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


# ==================== Statistics Calculation ====================

def _calculate_stats_for_certainty_level(all_results, min_certainty=0):
    """
    Calculate statistics for a specific certainty threshold.

    Args:
        all_results: List of document evaluation results
        min_certainty: Minimum certainty level to include (0-5)

    Returns:
        dict with 'overall' and 'by_tag' statistics for this certainty level
    """
    total_comparisons = 0
    total_matches = 0
    total_partial = 0
    total_mismatches = 0
    total_score = 0.0

    tag_stats = {}

    for doc_results in all_results:
        for subject_results in doc_results["subjects"]:
            for tag, result in subject_results["evaluations"].items():
                # Filter by GT certainty (certainty_A)
                if result["certainty_A"] < min_certainty:
                    continue

                # Update totals
                total_comparisons += 1
                total_score += result["agreement_score"]

                if result["match"]:
                    total_matches += 1
                elif result["less_precise"]:
                    total_partial += 1
                else:
                    total_mismatches += 1

                # Update tag-specific stats
                if tag not in tag_stats:
                    tag_stats[tag] = {
                        "total": 0,
                        "matches": 0,
                        "less_precise": 0,
                        "mismatches": 0,
                        "agreement_scores": []
                    }

                tag_stats[tag]["total"] += 1
                tag_stats[tag]["agreement_scores"].append(result["agreement_score"])
                if result["match"]:
                    tag_stats[tag]["matches"] += 1
                elif result["less_precise"]:
                    tag_stats[tag]["less_precise"] += 1
                else:
                    tag_stats[tag]["mismatches"] += 1

    # Calculate percentages
    overall_stats = {
        "total_comparisons": total_comparisons,
        "total_matches": total_matches,
        "total_less_precise": total_partial,
        "total_mismatches": total_mismatches,
        "match_rate": total_matches / total_comparisons if total_comparisons > 0 else 0,
        "less_precise_rate": total_partial / total_comparisons if total_comparisons > 0 else 0,
        "mismatch_rate": total_mismatches / total_comparisons if total_comparisons > 0 else 0,
        "average_score": round(total_score / total_comparisons, 4) if total_comparisons > 0 else 0,
        "average_score_percentage": round((total_score / total_comparisons) * 100, 2) if total_comparisons > 0 else 0,
    }

    # Calculate tag-specific percentages
    for tag, stats in tag_stats.items():
        stats["match_rate"] = stats["matches"] / stats["total"] if stats["total"] > 0 else 0
        stats["less_precise_rate"] = stats["less_precise"] / stats["total"] if stats["total"] > 0 else 0
        stats["mismatch_rate"] = stats["mismatches"] / stats["total"] if stats["total"] > 0 else 0
        stats["average_agreement"] = sum(stats["agreement_scores"]) / len(stats["agreement_scores"]) if stats["agreement_scores"] else 0

    return {
        "overall": overall_stats,
        "by_tag": tag_stats
    }


def calculate_statistics(all_results, min_certainty=3):
    """
    Calculate statistics from all evaluation results, grouped by certainty levels.

    Args:
        all_results: List of document evaluation results
        min_certainty: Default certainty level for backward compatibility (used in 'overall' and 'by_tag')

    Returns:
        dict with:
        - 'overall': Stats for default min_certainty (backward compatible)
        - 'by_tag': Tag stats for default min_certainty (backward compatible)
        - 'by_certainty': Stats for each certainty threshold (all, 1+, 2+, 3+, 4+, 5)
    """
    # Calculate stats for each certainty level
    by_certainty = {
        "all": _calculate_stats_for_certainty_level(all_results, min_certainty=0),
        "certainty_1+": _calculate_stats_for_certainty_level(all_results, min_certainty=1),
        "certainty_2+": _calculate_stats_for_certainty_level(all_results, min_certainty=2),
        "certainty_3+": _calculate_stats_for_certainty_level(all_results, min_certainty=3),
        "certainty_4+": _calculate_stats_for_certainty_level(all_results, min_certainty=4),
        "certainty_5": _calculate_stats_for_certainty_level(all_results, min_certainty=5),
    }

    # Use the specified min_certainty level for backward compatibility
    default_stats = _calculate_stats_for_certainty_level(all_results, min_certainty=min_certainty)

    return {
        "overall": default_stats["overall"],
        "by_tag": default_stats["by_tag"],
        "by_certainty": by_certainty
    }


# ==================== Case Logging ====================

def build_case_logs(all_results, filter_mode="all", min_certainty=3):
    """
    Build case logs from evaluation results, grouped by score

    Args:
        all_results: List of document evaluation results
        filter_mode: "all", "disagree" (< 1.0), or "mismatch" (= 0.0)
        min_certainty: Minimum certainty level to include (0-5)
    Returns:
        dict with keys '0.0', '0.5', '1.0_diff' containing lists of log strings
    """
    logs_by_score = {
        '0.0': [],      # Mismatch
        '0.5': [],      # Less precise
        '1.0_diff': []  # Match but keyword/certainty differs
    }

    for doc_results in all_results:
        data_id = doc_results["data_id"]

        for subject_results in doc_results["subjects"]:
            subject_id = subject_results["subject_id"]

            for tag, result in subject_results["evaluations"].items():
                # if result["certainty_A"] < min_certainty or result["certainty_B"] < min_certainty:
                #     continue
                score = result["agreement_score"]
                method = result.get("evaluation_method", "RULE")

                # Apply filter
                if filter_mode == "disagree" and score >= 1.0:
                    continue
                elif filter_mode == "mismatch" and score != 0.0:
                    continue

                # Format log entry
                log_entry = (
                    f"  [{data_id}][{subject_id}] [{method}] [{tag}] "
                    f"'{result['keyword_A']}:{result['certainty_A']}' vs '{result['keyword_B']}:{result['certainty_B']}'"
                )

                # Categorize by score
                if score == 0.0:
                    logs_by_score['0.0'].append(log_entry)
                elif score == 0.5:
                    logs_by_score['0.5'].append(log_entry)
                elif score == 1.0:
                    # Check if keyword or certainty differs
                    kw_a = result['keyword_A']
                    kw_b = result['keyword_B']
                    cert_a = result['certainty_A']
                    cert_b = result['certainty_B']

                    if kw_a != kw_b or cert_a != cert_b:
                        logs_by_score['1.0_diff'].append(log_entry)

    return logs_by_score


# ==================== Printing ====================

def print_statistics_summary(statistics):
    """
    Print formatted statistics summary

    Args:
        statistics: Statistics dict from calculate_statistics()
    """
    print(f"\n{'='*80}")
    print(f"OVERALL STATISTICS")
    print(f"{'='*80}")
    print(f"Total PII comparisons: {statistics['overall']['total_comparisons']}")
    print(f"  - Match (score=1.0):        {statistics['overall']['total_matches']:4d} ({statistics['overall']['match_rate']:6.2%})")
    print(f"  - Less precise (score=0.5): {statistics['overall']['total_less_precise']:4d} ({statistics['overall']['less_precise_rate']:6.2%})")
    print(f"  - Mismatch (score=0.0):     {statistics['overall']['total_mismatches']:4d} ({statistics['overall']['mismatch_rate']:6.2%})")
    print(f"\nAverage Score: {statistics['overall']['average_score_percentage']:.2f}%")

    print(f"\n{'='*80}")
    print(f"BY TAG STATISTICS")
    print(f"{'='*80}")
    sorted_tags = sorted(statistics['by_tag'].items(), key=lambda x: x[1]['average_agreement'], reverse=True)
    print(f"{'Tag':<20} {'Total':>6} {'Match':>6} {'Less':>6} {'Mismatch':>6} {'Avg Score':>10}")
    print(f"{'-'*80}")
    for tag, stats in sorted_tags:
        avg_score = stats['average_agreement']
        print(f"{tag:<20} {stats['total']:6d} {stats['matches']:6d} {stats['less_precise']:6d} {stats['mismatches']:6d} {avg_score:10.4f}")


def print_case_logs(case_logs_by_score, filter_mode="all"):
    """
    Print case logs grouped by score

    Args:
        case_logs_by_score: Dict with keys '0.0', '0.5', '1.0_diff' from build_case_logs()
        filter_mode: Filter mode used for context
    """
    # Count total cases
    total_cases = sum(len(logs) for logs in case_logs_by_score.values())
    if total_cases == 0:
        return

    print(f"\n{'='*80}")
    if filter_mode == "all":
        print(f"DETAILED CASE BREAKDOWN")
    elif filter_mode == "disagree":
        print(f"DISAGREEMENT CASES (score < 1.0)")
    elif filter_mode == "mismatch":
        print(f"MISMATCH CASES (score = 0.0)")
    print(f"{'='*80}")

    # Print by category
    if case_logs_by_score['0.0']:
        print(f"\n[0.0] Mismatch ({len(case_logs_by_score['0.0'])} cases):")
        for log in case_logs_by_score['0.0']:
            print(log)

    if case_logs_by_score['0.5']:
        print(f"\n[0.5] Less precise ({len(case_logs_by_score['0.5'])} cases):")
        for log in case_logs_by_score['0.5']:
            print(log)

    if case_logs_by_score['1.0_diff']:
        print(f"\n[1.0] Match (keyword/certainty differs) ({len(case_logs_by_score['1.0_diff'])} cases):")
        for log in case_logs_by_score['1.0_diff']:
            print(log)

    print(f"\nTotal cases shown: {total_cases}")


# ==================== Main ====================

def main(input_file, show_cases=True, case_filter="low_score"):
    """
    Main function to calculate and display accuracy metrics

    Args:
        input_file: Path to evaluation results JSON
        show_cases: Whether to print case logs
        case_filter: Case log filter mode
    """
    # Load evaluation results
    print(f"Loading evaluation results from: {input_file}")
    data = load_evaluation_results(input_file)

    config = data["config"]
    all_results = data["detailed_results"]

    print(f"\nConfiguration:")
    print(f"  Evaluation mode: {config.get('evaluation_mode', 'inter_annotator')}")
    print(f"  Min certainty: {config.get('min_certainty', 0)}")
    print(f"  Location max depth: {config.get('location_max_depth', 'None')}")

    # Calculate statistics
    statistics = calculate_statistics(all_results)

    # Print statistics
    print_statistics_summary(statistics)

    # Print case logs if requested
    if show_cases:
        case_logs = build_case_logs(all_results, filter_mode=case_filter)
        print_case_logs(case_logs, filter_mode=case_filter)


if __name__ == "__main__":
    args = parse_args()
    if args.mode == "inter":
        INPUT_FILE = f"report/{args.data}_cross_labeled_check_human_labels_{args.datetime}.json"
    else:
        INPUT_FILE = f"report/{args.data}_human_vs_llms_check_human_labels_{args.datetime}.json"

    main(INPUT_FILE, show_cases=SHOW_CASE_LOGS, case_filter=CASE_LOG_FILTER)
