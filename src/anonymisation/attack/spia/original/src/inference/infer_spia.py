"""
SPIA Subject-level PII Inference

Infer subject-level PII from documents using LLM pipeline.
Performs SA (Subject Analysis) → SPC (Subject Profiling Code) → SPNC (Subject Profiling Non-Code).

Usage:
    python src/inference/infer_spia.py --input data/spia/tab_144.jsonl
    python src/inference/infer_spia.py --input data.jsonl --model gpt-4.1-mini --provider openai
    python src/inference/infer_spia.py --input data.jsonl --limit 10 --allow-fallback
"""

import json
import sys
import os
import argparse
from tqdm import tqdm
from datetime import datetime
from src.common_utils import load_jsonl_data

from src.llm.client import (
    get_subjects_analysis,
    get_subject_profiling_code,
    get_subject_profiling_non_code,
    set_api_provider,
)
from src.llm.parser import (
    clear_subjects_analysis_response,
    parse_number_of_subjects,
    parse_subject_profiling,
    concat_parsing_result,
    create_spnc_only_result
)


def detect_dataset_type(input_file):
    """Detect dataset type from input file path or filename.

    Returns:
        str: "panorama" if path/filename contains 'panorama', "tab" otherwise
    """
    if "panorama" in input_file.lower():
        return "panorama"
    return "tab"


def load_presaved_sa_responses(file_path):
    """Load pre-saved SA responses from file."""
    sa_responses = {}
    if not file_path or not os.path.exists(file_path):
        return sa_responses

    print(f"Loading SA responses from: {file_path}")
    with open(file_path, 'r') as f:
        for line in f:
            try:
                data = json.loads(line.strip())
                data_id = data.get('data_id')
                if data_id:
                    sa_responses[data_id] = {
                        'sa_response': data.get('sa_response'),
                        'number_of_subjects': data.get('number_of_subjects')
                    }
            except json.JSONDecodeError:
                continue

    print(f"Loaded {len(sa_responses)} SA responses")
    return sa_responses


def load_processed_ids(output_file):
    """Get IDs of already processed documents."""
    processed_ids = set()
    if os.path.exists(output_file):
        print(f"Found existing output: {output_file}")
        with open(output_file, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    data_id = data.get('metadata', {}).get('data_id')
                    if data_id:
                        processed_ids.add(data_id)
                except json.JSONDecodeError:
                    continue
    return processed_ids


def save_response(file_path, data_id, response_type, response):
    """Save API response to file."""
    if not response:
        return

    response_data = {
        'data_id': data_id,
        f'{response_type}_response': response
    }

    with open(file_path, 'a') as f:
        f.write(json.dumps(response_data, ensure_ascii=False) + '\n')


def save_result(output_file, data):
    """Save successfully processed document."""
    with open(output_file, 'a') as f:
        f.write(json.dumps(data, ensure_ascii=False) + '\n')


def save_error(error_file, data_id, error_type, error_msg):
    """Save error to JSONL file."""
    error_data = {
        'data_id': data_id,
        'error_type': error_type,
        'error': error_msg,
        'timestamp': datetime.now().isoformat()
    }
    with open(error_file, 'a') as f:
        f.write(json.dumps(error_data, ensure_ascii=False) + '\n')


def process_sa(text, data_id, sa_cache, sa_file, dataset_type, use_presaved):
    """Process subjects analysis.

    Args:
        text: The text to analyze
        data_id: Document ID
        sa_cache: Cache of pre-saved SA responses
        sa_file: File path to save SA responses
        dataset_type: "tab" or "panorama"
        use_presaved: Whether to use pre-saved SA responses
    """
    if use_presaved and data_id in sa_cache:
        cached = sa_cache[data_id]
        save_response(sa_file, data_id, 'sa', cached['sa_response'])
        return True, cached['sa_response'], cached['number_of_subjects'], None

    status, sa_response = get_subjects_analysis(text, dataset_type)
    save_response(sa_file, data_id, 'sa', sa_response)

    if status == "error":
        return False, None, None, f"SA_ERROR: {sa_response}"

    status, sa_cleared = clear_subjects_analysis_response(sa_response)
    if status == "error":
        return False, None, None, f"SA_CLEAR_ERROR: {sa_response}"

    status, num_subjects = parse_number_of_subjects(sa_cleared)
    if status == "error":
        return False, None, None, f"SA_PARSING_ERROR: {sa_response}"

    return True, sa_cleared, num_subjects, None


def process_spc(text, sa_response, data_id, spc_file):
    """Process subject profiling code."""
    status, spc_response = get_subject_profiling_code(text, sa_response)
    save_response(spc_file, data_id, 'spc', spc_response)

    if status == "error":
        return False, None, f"SPC_RESPONSE_ERROR: {spc_response}"

    status, spc_result = parse_subject_profiling(spc_response)
    if status == "error":
        return False, None, f"SPC_PARSING_ERROR: {spc_response}"

    return True, spc_result, None


def process_spnc(text, sa_response, data_id, spnc_file):
    """Process subject profiling non-code."""
    status, spnc_response = get_subject_profiling_non_code(text, sa_response)
    save_response(spnc_file, data_id, 'spnc', spnc_response)

    if status == "error":
        return False, None, f"SPNC_RESPONSE_ERROR: {spnc_response}"

    status, spnc_result = parse_subject_profiling(spnc_response)
    if status == "error":
        return False, None, f"SPNC_PARSING_ERROR: {spnc_response}"

    return True, spnc_result, None


def merge_results(spc_result, spnc_result, allow_fallback):
    """Merge SPC and SPNC results."""
    status, result = concat_parsing_result(spc_result, spnc_result)

    if status == "error":
        if allow_fallback and spnc_result:
            fallback_status, fallback_result = create_spnc_only_result(spnc_result)
            if fallback_status == "success":
                return True, fallback_result, True
        return False, None, False

    return True, result, False


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Infer subject-level PII from documents using LLM pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python src/inference/infer_spia.py --input data/spia/tab_144.jsonl
    python src/inference/infer_spia.py --input data.jsonl --model gpt-4.1-mini --provider openai
    python src/inference/infer_spia.py --input data.jsonl --limit 10 --allow-fallback
        """
    )
    parser.add_argument(
        "--input", "-i",
        type=str,
        required=True,
        help="Input JSONL file path"
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default="gpt-4.1-mini",
        help="Model name (default: gpt-4.1-mini)"
    )
    parser.add_argument(
        "--provider", "-p",
        type=str,
        default="openai",
        choices=["openai", "anthropic", "ollama"],
        help="API provider (default: openai)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory (default: data/spia/inference/{base_name}/{model})"
    )
    parser.add_argument(
        "--base-name",
        type=str,
        default=None,
        help="Base name for output files (auto-detected from input if not provided)"
    )
    parser.add_argument(
        "--limit", "-l",
        type=int,
        default=None,
        help="Limit number of documents to process"
    )
    parser.add_argument(
        "--text-field",
        type=str,
        default=None,
        help="Field name for input text (auto-detected if not specified)"
    )
    parser.add_argument(
        "--allow-fallback",
        action="store_true",
        help="Allow SPNC-only fallback when SPC/SPNC mismatch occurs"
    )
    parser.add_argument(
        "--use-presaved-sa",
        action="store_true",
        help="Use pre-saved SA responses if available"
    )
    parser.add_argument(
        "--sa-file",
        type=str,
        default=None,
        help="Path to pre-saved SA responses file"
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    model = args.model
    provider = args.provider
    input_file = args.input
    document_limit = args.limit
    allow_fallback = args.allow_fallback
    use_presaved_sa = args.use_presaved_sa

    # Auto-detect base_name from input file
    if args.base_name:
        base_name = args.base_name
    else:
        base_name = os.path.splitext(os.path.basename(input_file))[0]

    # Auto-detect text_field from input file
    if args.text_field:
        text_field = args.text_field
    elif '/anonymized/' in input_file or '_anonymized' in os.path.basename(input_file):
        text_field = 'anonymized_text'
    else:
        text_field = 'text'

    print("=" * 60)
    print("SPIA Subject-level PII Inference")
    print("=" * 60)
    print(f"Model: {model}")
    print(f"Provider: {provider}")
    print(f"Input file: {input_file}")
    print(f"Base name: {base_name}")
    print(f"Text field: {text_field}")
    if document_limit:
        print(f"Document limit: {document_limit}")
    print("=" * 60)

    # Initialize API
    try:
        set_api_provider(provider, model)
        print(f"Using {provider} API with model: {model}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Detect dataset type from input file path
    dataset_type = detect_dataset_type(input_file)
    print(f"Detected dataset type: {dataset_type.upper()}")

    # Load data
    dataset = load_jsonl_data(input_file)
    if document_limit:
        dataset = dataset[:document_limit]
    dataset_size = len(dataset)

    # Output file paths
    model_name_safe = model.replace(':', '-').replace('/', '_')
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = f'data/spia/inference/{base_name}/{model_name_safe}'

    output_file = f'{output_dir}/{base_name}_inferred_{provider}_{model_name_safe}.jsonl'
    error_file = f'{output_dir}/{base_name}_errors_{provider}_{model_name_safe}.jsonl'
    sa_file = f'{output_dir}/{base_name}_sa_responses_{provider}_{model_name_safe}.jsonl'
    spc_file = f'{output_dir}/{base_name}_spc_responses_{provider}_{model_name_safe}.jsonl'
    spnc_file = f'{output_dir}/{base_name}_spnc_responses_{provider}_{model_name_safe}.jsonl'

    os.makedirs(output_dir, exist_ok=True)

    # Load caches
    sa_cache = {}
    if use_presaved_sa and args.sa_file:
        sa_cache = load_presaved_sa_responses(args.sa_file)
    processed_ids = load_processed_ids(output_file)

    # Initialize counters
    stats = {
        'processed': 0,
        'errors': 0,
        'skipped': len(processed_ids),
        'mismatches': 0,
        'error_ids': [],
        'mismatch_ids': []
    }

    print(f"\nProcessing {dataset_size} documents ({stats['skipped']} already done)\n")

    if len(processed_ids) == dataset_size:
        print("All documents already processed!")
        return

    # Process documents
    for idx, data in enumerate(tqdm(dataset, desc="Inferring")):
        data_id = data.get('metadata', {}).get('data_id', f'line_{idx}')

        if data_id in processed_ids:
            continue

        text = data.get(text_field, data['text'])

        # Step 1: Subject Analysis
        success, sa_response, num_subjects, error = process_sa(
            text, data_id, sa_cache, sa_file, dataset_type, use_presaved_sa
        )
        if not success:
            save_error(error_file, data_id, "SA", error)
            stats['errors'] += 1
            stats['error_ids'].append(data_id)
            continue

        # Step 2: Subject Profiling Code
        success, spc_result, error = process_spc(text, sa_response, data_id, spc_file)
        if not success:
            save_error(error_file, data_id, "SPC", error)
            stats['errors'] += 1
            stats['error_ids'].append(data_id)
            continue

        # Step 3: Subject Profiling Non-Code
        success, spnc_result, error = process_spnc(text, sa_response, data_id, spnc_file)
        if not success:
            save_error(error_file, data_id, "SPNC", error)
            stats['errors'] += 1
            stats['error_ids'].append(data_id)
            continue

        # Step 4: Merge Results
        success, inference_result, used_fallback = merge_results(spc_result, spnc_result, allow_fallback)
        if not success:
            save_error(error_file, data_id, "concat", f"CONCAT_ERROR: SPC={spc_result}, SPNC={spnc_result}")
            stats['errors'] += 1
            stats['error_ids'].append(data_id)
            continue

        if used_fallback:
            stats['mismatches'] += 1
            stats['mismatch_ids'].append(data_id)

        # Save successful result
        if 'metadata' not in data:
            data['metadata'] = {}
        data['metadata']['number_of_subjects'] = num_subjects
        data['subjects'] = inference_result

        save_result(output_file, data)
        stats['processed'] += 1

        # Progress update
        if (stats['processed'] + stats['errors']) % 100 == 0:
            total = stats['processed'] + stats['errors'] + stats['skipped']
            print(f"Progress: {total}/{dataset_size}")

    # Print summary
    print(f"\n{'='*60}")
    print("Inference Complete!")
    print(f"{'='*60}")
    print(f"Model: {model}")
    print(f"Output: {output_file}")
    print(f"Errors: {error_file}")
    print(f"Response files:")
    print(f"  - SA: {sa_file}")
    print(f"  - SPC: {spc_file}")
    print(f"  - SPNC: {spnc_file}")
    print(f"{'='*60}")
    print(f"Total: {dataset_size}")
    print(f"Processed: {stats['processed']}")
    print(f"Errors: {stats['errors']}")
    if stats['error_ids']:
        print(f"Error IDs: {stats['error_ids']}")
    print(f"Skipped (already processed): {stats['skipped']}")
    print(f"Mismatches (SPNC fallback): {stats['mismatches']}")
    if stats['mismatch_ids']:
        print(f"Mismatch IDs: {stats['mismatch_ids']}")


if __name__ == "__main__":
    main()
