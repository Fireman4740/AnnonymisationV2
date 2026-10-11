"""
Align subjects based on ground truth for LLM evaluation
"""

import json
import sys
import os
import threading
import queue
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from datetime import datetime
import argparse

from src.common_utils import load_jsonl_data
from src.llm.client import get_alignment_analysis, set_api_provider
from src.llm.parser import parse_subject_alignment_response, validate_subject_matched_pairs


# ============================================================
# DEFAULT CONFIGURATION (overridable via CLI)
# ============================================================
# These are fallback defaults - actual values come from argparse


def parse_args():
    parser = argparse.ArgumentParser(description="Align subjects between GT and LLM annotations")
    parser.add_argument("--input_file", type=str, required=True,
                        help="Input file from align_human_llm_annotations.py")
    parser.add_argument("--output_file", type=str, required=True,
                        help="Output file path for subject-aligned data")

    # Subject alignment configuration
    parser.add_argument("--api_provider", type=str, default="ollama",
                        choices=["openai", "anthropic", "ollama"],
                        help="LLM API provider for subject matching (default: ollama)")
    parser.add_argument("--model", type=str, default="qwen3:32b",
                        help="Model name for alignment analysis (default: qwen3:32b)")
    parser.add_argument("--processing_mode", type=str, default="concurrent",
                        choices=["concurrent", "sequential"],
                        help="Processing mode (default: concurrent)")
    parser.add_argument("--num_workers", type=int, default=20,
                        help="Number of parallel workers (default: 20)")
    parser.add_argument("--document_limit", type=int, default=None,
                        help="Limit number of documents to process (default: None, process all)")

    return parser.parse_args()

# ============================================================
# Helper Functions
# ============================================================
def load_processed_ids(output_file, unprocessed_ids):
    """Get IDs of already processed documents"""
    processed_ids = set()
    if os.path.exists(output_file):
        with open(output_file, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    data_id = data.get('metadata', {}).get('data_id')
                    if data_id and data_id not in unprocessed_ids:
                        processed_ids.add(data_id)
                except json.JSONDecodeError:
                    continue
    return processed_ids

def extract_unprocessed_docs(output_file):
    """Get IDs of unprocessed documents"""
    if not os.path.exists(output_file):
        return []
    with open(output_file, 'r') as f:
        try:
            # only first line
            line = f.readline()
            data = json.loads(line.strip())
            alignment_summary = data.get('metadata', {}).get('alignment_summary')
            if alignment_summary:
                return alignment_summary.get('error_data_ids', [])
            else:
                return []
        except json.JSONDecodeError:
            print(f"Error decoding JSON: {e}")
            return []
        except Exception as e:
            print(f"Error extracting unprocessed docs: {e}")
            return []

def extract_stats_from_existing_results(output_file):
    """
    Extract alignment statistics from already processed documents
    
    Returns:
        tuple: (matched_count, unmatched_gt_count, unmatched_llm_count,
                unmatched_gt_pii_count, unmatched_llm_pii_count, total_subjects,
                gt_only_cases, processed_count)
    """
    stats = {
        'matched_count': 0,
        'unmatched_gt_count': 0,
        'unmatched_llm_count': 0,
        'unmatched_gt_pii_count': 0,
        'unmatched_llm_pii_count': 0,
        'total_subjects': 0,
        'gt_only_cases': [],
        'processed_count': 0
    }
    
    if not os.path.exists(output_file):
        return (0, 0, 0, 0, 0, 0, [], 0)
    
    with open(output_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                data = json.loads(line.strip())
                if data.get('status', '') == 'error':
                    continue
                subjects = data.get('subjects', [])
                if not subjects:
                    continue
                
                data_id = data.get('metadata', {}).get('data_id', 'unknown')
                stats['processed_count'] += 1
                
                doc_has_gt_only = False
                
                for subject in subjects:
                    piis_a = subject.get('PIIs', {}).get('annotation_A', [])
                    piis_b = subject.get('PIIs', {}).get('annotation_B', [])

                    # Count GT PIIs (non-empty keywords)
                    gt_pii_count = sum(1 for pii in piis_a if pii.get('keyword', '').strip())

                    # Use 'matched' field if available (new format), fallback to keyword check (legacy)
                    is_matched = subject.get('matched')
                    if is_matched is None:
                        # Legacy: check if annotation_B has any real PIIs (non-empty keywords)
                        is_matched = any(pii.get('keyword', '').strip() for pii in piis_b)

                    if is_matched:
                        # Matched subject
                        stats['matched_count'] += 1
                        llm_pii_count = sum(1 for pii in piis_b if pii.get('keyword', '').strip())
                        stats['total_subjects'] += 2  # GT + LLM
                    else:
                        # GT-only subject (all LLM PIIs are dummy)
                        stats['unmatched_gt_count'] += 1
                        stats['unmatched_gt_pii_count'] += gt_pii_count
                        stats['total_subjects'] += 1  # Only GT
                        doc_has_gt_only = True

                if doc_has_gt_only:
                    # Count GT-only subjects in this document
                    gt_only_subjects = []
                    for subject in subjects:
                        is_matched = subject.get('matched')
                        if is_matched is None:
                            piis_b = subject.get('PIIs', {}).get('annotation_B', [])
                            is_matched = any(pii.get('keyword', '').strip() for pii in piis_b)
                        if not is_matched:
                            gt_only_subjects.append(subject.get('id', len(gt_only_subjects)))

                    if gt_only_subjects:
                        stats['gt_only_cases'].append({
                            'data_id': data_id,
                            'unmatched_gt_ids': gt_only_subjects,
                            'unmatched_gt_count': len(gt_only_subjects)
                        })
                        
            except json.JSONDecodeError:
                continue
            except Exception as e:
                print(f"Error extracting stats from document: {e}")
                continue
    
    return (stats['matched_count'], stats['unmatched_gt_count'], stats['unmatched_llm_count'],
            stats['unmatched_gt_pii_count'], stats['unmatched_llm_pii_count'],
            stats['total_subjects'], stats['gt_only_cases'], stats['processed_count'])


def save_processed_data(output_file, data):
    """Save successfully processed document"""
    with open(output_file, 'a') as f:
        f.write(json.dumps(data, ensure_ascii=False) + '\n')


def print_error(data_id, error_type, error_msg):
    """Print error immediately"""
    print(f"\n[ERROR] {data_id} - {error_type}: {error_msg}")


def save_llm_response(output_file, data_id, status, response):
    """Save all LLM responses for debugging"""
    response_log_file = output_file.replace('.jsonl', '_llm_responses.jsonl')
    with open(response_log_file, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'data_id': data_id, 'status': status, 'response': response}, ensure_ascii=False) + '\n')


# ============================================================
# Processing Functions
# ============================================================
def process_alignment(text, annotation_gt, annotation_llm, data_id, anonymized_text=None):
    """
    Process alignment for a single document

    Args:
        text: Original text
        annotation_gt: Ground truth annotation (from original text)
        annotation_llm: LLM annotation (from original or anonymized text)
        data_id: Document ID for logging
        anonymized_text: Anonymized text. If provided, uses anon prompt template.

    Returns:
        tuple: (status, matched_pairs, response, error, match_stats)
    """
    status, response = get_alignment_analysis(
        text, annotation_gt, annotation_llm,
        anonymized_text=anonymized_text
    )

    if status == "error":
        print_error(data_id, "ALIGNMENT_ERROR", response)
        return False, None, response, f"ALIGNMENT_ERROR: {response}", None

    status, matched_pairs = parse_subject_alignment_response(response)
    if status == "error":
        print_error(data_id, "PARSING_ERROR", matched_pairs)
        return False, None, response, f"PARSING_ERROR: {matched_pairs}", None

    status, validated_pairs = validate_subject_matched_pairs(matched_pairs, annotation_gt, annotation_llm)
    if status == "error":
        print_error(data_id, "VALIDATION_ERROR", validated_pairs)
        return False, None, response, f"VALIDATION_ERROR: {validated_pairs}", None

    total_subjects_gt = len(annotation_gt)
    total_subjects_llm = len(annotation_llm)
    matched_count = len(validated_pairs)

    matched_gt_indices = {pair[0] for pair in validated_pairs}
    matched_llm_indices = {pair[1] for pair in validated_pairs}

    unmatched_gt_ids = [annotation_gt[i].get('id', i) for i in range(total_subjects_gt) if i not in matched_gt_indices]
    unmatched_llm_ids = [annotation_llm[i].get('id', i) for i in range(total_subjects_llm) if i not in matched_llm_indices]

    # Count valid PIIs (keyword not empty) in unmatched subjects
    unmatched_gt_pii_count = sum(
        len([pii for pii in annotation_gt[i].get('PIIs', []) if pii.get('keyword', '').strip()])
        for i in range(total_subjects_gt) if i not in matched_gt_indices
    )
    unmatched_llm_pii_count = sum(
        len([pii for pii in annotation_llm[i].get('PIIs', []) if pii.get('keyword', '').strip()])
        for i in range(total_subjects_llm) if i not in matched_llm_indices
    )

    match_stats = {
        'total_subjects_gt': total_subjects_gt,
        'total_subjects_llm': total_subjects_llm,
        'matched_count': matched_count,
        'unmatched_gt_count': len(unmatched_gt_ids),
        'unmatched_llm_count': len(unmatched_llm_ids),
        'unmatched_gt_pii_count': unmatched_gt_pii_count,
        'unmatched_llm_pii_count': unmatched_llm_pii_count,
        'matched_pairs': validated_pairs,
        'unmatched_gt_ids': unmatched_gt_ids,
        'unmatched_llm_ids': unmatched_llm_ids
    }

    return True, validated_pairs, response, None, match_stats


def transform_to_gt_aligned_format(annotation_gt, annotation_llm, matched_pairs):
    """
    Transform matched subjects into GT-aligned format for evaluation

    Args:
        annotation_gt: List of subjects from ground truth
        annotation_llm: List of subjects from LLM annotation
        matched_pairs: List of (GT_id, LLM_id) tuples

    Returns:
        List of aligned subjects with GT PIIs in annotation_A and LLM PIIs in annotation_B
        For GT-only subjects, annotation_B contains dummy PIIs with empty keyword, hardness=0, certainty=0
    """
    aligned_subjects = []

    gt_indices = set(range(len(annotation_gt)))
    matched_gt_indices = {pair[0] for pair in matched_pairs}
    # gt_only_indices = gt_indices - matched_gt_indices
    gt_only_indices = []
    for gt_id in gt_indices:
        if gt_id not in matched_gt_indices:
            gt_only_indices.append(gt_id)
    
    for gt_id, llm_id in matched_pairs:
        subject_gt = annotation_gt[gt_id]
        subject_llm = annotation_llm[llm_id]

        aligned_subject = {
            'id': len(aligned_subjects),
            'matched': True,  # Subject was matched by LLM
            'description': subject_gt.get('description', ''),
            'PIIs': {
                'annotation_A': subject_gt.get('PIIs', []),
                'annotation_B': subject_llm.get('PIIs', [])
            }
        }
        aligned_subjects.append(aligned_subject)

    # 2. Add GT-only subjects with dummy LLM PIIs
    for gt_idx in sorted(gt_only_indices):
        subject_gt = annotation_gt[gt_idx]
        gt_piis = subject_gt.get('PIIs', [])

        dummy_piis = [
            {
                'keyword': '',
                'tag': pii.get('tag', ''),
                'hardness': 0,
                'certainty': 0
            }
            for pii in gt_piis
        ]

        aligned_subject = {
            'id': len(aligned_subjects),
            'matched': False,  # Subject was not matched by LLM (GT-only)
            'description': subject_gt.get('description', ''),
            'PIIs': {
                'annotation_A': gt_piis,
                'annotation_B': dummy_piis
            }
        }
        aligned_subjects.append(aligned_subject)

    return aligned_subjects


# ============================================================
# Concurrent Processing
# ============================================================
result_queue = queue.Queue()
stats_lock = threading.Lock()
concurrent_stats = {
    'processed': 0,
    'errors': 0,
    'matched_count': 0,
    'total_subjects': 0,
    'unmatched_gt_count': 0,
    'unmatched_llm_count': 0,
    'unmatched_gt_pii_count': 0,
    'unmatched_llm_pii_count': 0,
    'gt_only_cases': [],
    'error_data_ids': []
}


def process_document_concurrent(data_with_idx):
    """Process single document through alignment pipeline in concurrent mode"""
    data, idx = data_with_idx
    data_id = data.get('metadata', {}).get('data_id', f'line_{idx}')

    try:
        text = data['text']
        anonymized_text = data.get('anonymized_text')  # For anon mode
        annotation_gt = data.get('annotation_A', [])
        annotation_llm = data.get('annotation_B', [])

        if not annotation_gt or not annotation_llm:
            error_msg = f"Missing annotations: A={len(annotation_gt)}, B={len(annotation_llm)}"
            print_error(data_id, "missing_annotations", error_msg)
            return {
                'data_id': data_id,
                'data': data,
                'status': 'error',
                'error_type': 'missing_annotations',
                'error': error_msg,
                'response': None
            }

        success, matched_pairs, response, error, match_stats = process_alignment(
            text, annotation_gt, annotation_llm, data_id, anonymized_text=anonymized_text
        )

        if not success:
            return {
                'data_id': data_id,
                'data': data,
                'status': 'error',
                'error_type': 'alignment',
                'error': error,
                'response': response,
                'match_stats': None
            }

        aligned_subjects = transform_to_gt_aligned_format(annotation_gt, annotation_llm, matched_pairs)

        result_data = {
            'metadata': data.get('metadata', {}),
            'text': text,
        }

        # Include anonymized_text if present (for anon mode)
        if anonymized_text:
            result_data['anonymized_text'] = anonymized_text

        result_data['subjects'] = aligned_subjects

        return {
            'data_id': data_id,
            'data': result_data,
            'status': 'success',
            'matched_count': len(matched_pairs),
            'response': response,
            'match_stats': match_stats
        }

    except Exception as e:
        return {
            'data_id': data_id,
            'data': data,
            'status': 'error',
            'error_type': 'exception',
            'error': str(e),
            'exception': True,
            'response': None
        }


def file_writer_worker(output_file, skipped_count, dataset_size):
    """Dedicated file writer thread for concurrent processing"""
    while True:
        try:
            result = result_queue.get(timeout=10)
            if result is None:
                break

            data_id = result['data_id']
            data = result['data']
            status = result['status']

            # Save all LLM responses
            if result.get('response'):
                save_llm_response(output_file, data_id, status, result.get('response'))

            if status == 'error':
                with stats_lock:
                    concurrent_stats['errors'] += 1
                    concurrent_stats['error_data_ids'].append(data_id)
            else:
                save_processed_data(output_file, data)
                match_stats = result.get('match_stats')

                with stats_lock:
                    concurrent_stats['processed'] += 1
                    concurrent_stats['matched_count'] += result.get('matched_count', 0)

                    if match_stats:
                        total_subj = match_stats['total_subjects_gt'] + match_stats['total_subjects_llm']
                        concurrent_stats['total_subjects'] += total_subj
                        concurrent_stats['unmatched_gt_count'] += match_stats['unmatched_gt_count']
                        concurrent_stats['unmatched_llm_count'] += match_stats['unmatched_llm_count']
                        concurrent_stats['unmatched_gt_pii_count'] += match_stats.get('unmatched_gt_pii_count', 0)
                        concurrent_stats['unmatched_llm_pii_count'] += match_stats.get('unmatched_llm_pii_count', 0)

                        if match_stats['unmatched_gt_count'] > 0:
                            concurrent_stats['gt_only_cases'].append({
                                'data_id': data_id,
                                'unmatched_gt_ids': match_stats['unmatched_gt_ids'],
                                'unmatched_gt_count': match_stats['unmatched_gt_count']
                            })

            with stats_lock:
                total_done = concurrent_stats['processed'] + concurrent_stats['errors']
                if total_done % 10 == 0:
                    current_total = total_done + skipped_count
                    avg_matched = (concurrent_stats['matched_count'] / concurrent_stats['processed']
                                   if concurrent_stats['processed'] > 0 else 0)
                    print(f"\nProgress: {current_total}/{dataset_size} "
                          f"(Success: {concurrent_stats['processed']}, Error: {concurrent_stats['errors']}, "
                          f"Avg Matched: {avg_matched:.1f}, Skipped: {skipped_count})")

            result_queue.task_done()

        except queue.Empty:
            continue
        except Exception as e:
            print(f"File writer error: {e}")
            continue


def process_concurrent(unprocessed_docs, output_file, skipped_count, dataset_size, num_workers):
    """Process documents concurrently"""
    writer_thread = threading.Thread(
        target=file_writer_worker,
        args=(output_file, skipped_count, dataset_size)
    )
    writer_thread.daemon = True
    writer_thread.start()

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        future_to_doc = {
            executor.submit(process_document_concurrent, doc_data): doc_data
            for doc_data in unprocessed_docs
        }

        for future in tqdm(as_completed(future_to_doc),
                          total=len(unprocessed_docs),
                          desc="Processing documents"):
            try:
                result = future.result()
                result_queue.put(result)
            except Exception as e:
                doc_data = future_to_doc[future]
                data_id = doc_data[0].get('metadata', {}).get('data_id', f'line_{doc_data[1]}')
                print(f"Error processing document {data_id}: {e}")

    result_queue.join()
    result_queue.put(None)
    writer_thread.join(timeout=5)

    return (concurrent_stats['processed'], concurrent_stats['errors'],
            concurrent_stats['matched_count'], concurrent_stats['unmatched_gt_count'],
            concurrent_stats['unmatched_llm_count'], concurrent_stats['unmatched_gt_pii_count'],
            concurrent_stats['unmatched_llm_pii_count'], concurrent_stats['total_subjects'],
            concurrent_stats['gt_only_cases'], concurrent_stats['error_data_ids'])


# ============================================================
# Sequential Processing
# ============================================================
def process_sequential(dataset, output_file, processed_ids):
    """Process documents sequentially"""
    stats = {
        'processed': 0,
        'errors': 0,
        'skipped': len(processed_ids),
        'matched_count': 0,
        'unmatched_gt_count': 0,
        'unmatched_llm_count': 0,
        'unmatched_gt_pii_count': 0,
        'unmatched_llm_pii_count': 0,
        'total_subjects': 0,
        'gt_only_cases': [],
        'error_data_ids': []
    }

    for idx, data in enumerate(tqdm(dataset, desc="Processing")):
        data_id = data.get('metadata', {}).get('data_id', f'line_{idx}')

        if data_id in processed_ids:
            continue

        text = data['text']
        anonymized_text = data.get('anonymized_text')  # For anon mode
        annotation_gt = data.get('annotation_A', [])
        annotation_llm = data.get('annotation_B', [])

        if not annotation_gt or not annotation_llm:
            error_msg = f"Missing annotations: A={len(annotation_gt)}, B={len(annotation_llm)}"
            print_error(data_id, "missing_annotations", error_msg)
            stats['errors'] += 1
            stats['error_data_ids'].append(data_id)
            continue

        success, matched_pairs, response, error, match_stats = process_alignment(
            text, annotation_gt, annotation_llm, data_id, anonymized_text=anonymized_text
        )

        if not success:
            stats['errors'] += 1
            stats['error_data_ids'].append(data_id)
            continue

        aligned_subjects = transform_to_gt_aligned_format(annotation_gt, annotation_llm, matched_pairs)

        result_data = {
            'metadata': data.get('metadata', {}),
            'text': text,
        }

        # Include anonymized_text if present (for anon mode)
        if anonymized_text:
            result_data['anonymized_text'] = anonymized_text

        result_data['subjects'] = aligned_subjects

        save_processed_data(output_file, result_data)
        stats['processed'] += 1
        stats['matched_count'] += len(matched_pairs)

        if match_stats:
            total_subj = match_stats['total_subjects_gt'] + match_stats['total_subjects_llm']
            stats['total_subjects'] += total_subj
            stats['unmatched_gt_count'] += match_stats['unmatched_gt_count']
            stats['unmatched_llm_count'] += match_stats['unmatched_llm_count']
            stats['unmatched_gt_pii_count'] += match_stats.get('unmatched_gt_pii_count', 0)
            stats['unmatched_llm_pii_count'] += match_stats.get('unmatched_llm_pii_count', 0)

            if match_stats['unmatched_gt_count'] > 0:
                stats['gt_only_cases'].append({
                    'data_id': data_id,
                    'unmatched_gt_ids': match_stats['unmatched_gt_ids'],
                    'unmatched_gt_count': match_stats['unmatched_gt_count']
                })

        if (stats['processed'] + stats['errors']) % 10 == 0:
            total = stats['processed'] + stats['errors'] + stats['skipped']
            avg_matched = stats['matched_count'] / stats['processed'] if stats['processed'] > 0 else 0
            print(f"\nProgress: {total}/{len(dataset)}, Avg Matched: {avg_matched:.1f}")

    return (stats['processed'], stats['errors'], stats['matched_count'],
            stats['unmatched_gt_count'], stats['unmatched_llm_count'],
            stats['unmatched_gt_pii_count'], stats['unmatched_llm_pii_count'],
            stats['total_subjects'], stats['gt_only_cases'], stats['error_data_ids'])

def gt_only_subject(dataset, data_id):
    for data in dataset:
        if data.get('metadata', {}).get('data_id', '') == data_id:
            subjects = []
            for subject in data.get('annotation_A', []):
                subjects.append({
                    'id': subject.get('id', 0),
                    'description': subject.get('description', ''),
                    'PIIs': {
                        'annotation_A': subject.get('PIIs', []),
                        'annotation_B': [
                            {
                            "tag": "NAME",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "IDENTIFICATION_NUMBER",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "DRIVER_LICENSE_NUMBER",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "PHONE_NUMBER",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "PASSPORT_NUMBER",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "EMAIL_ADDRESS",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "SEX",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "AGE",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "LOCATION",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "NATIONALITY",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "EDUCATION",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "RELATIONSHIP",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "OCCUPATION",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "AFFILIATION",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "POSITION",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            },
                            {
                            "tag": "RELIGION",
                            "keyword": "",
                            "certainty": 0,
                            "hardness": 0
                            }
                        ]
                    }
                })
            return {
                'status': 'error',
                'metadata': data.get('metadata', {}),
                'text': data.get('text', ''),
                'subjects': subjects
            }
    return None

# ============================================================
# Main Pipeline
# ============================================================
def main(iteration = 0):

    # ============================================================
    # Concurrent Processing
    # ============================================================
    global result_queue, stats_lock, concurrent_stats, PROMPT_TYPE
    result_queue = queue.Queue()
    stats_lock = threading.Lock()
    concurrent_stats = {
        'processed': 0,
        'errors': 0,
        'matched_count': 0,
        'total_subjects': 0,
        'unmatched_gt_count': 0,
        'unmatched_llm_count': 0,
        'unmatched_gt_pii_count': 0,
        'unmatched_llm_pii_count': 0,
        'gt_only_cases': [],
        'error_data_ids': []
    }

    args = parse_args()
    INPUT_FILE = args.input_file
    output_file = args.output_file

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    # Use arguments for configuration
    API_PROVIDER = args.api_provider
    MODEL = args.model
    PROCESSING_MODE = args.processing_mode
    NUM_WORKERS = args.num_workers
    DOCUMENT_LIMIT = args.document_limit

    try:
        set_api_provider(API_PROVIDER, MODEL)
        print(f"Using {API_PROVIDER} API with model: {MODEL}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    dataset = load_jsonl_data(INPUT_FILE)
    if DOCUMENT_LIMIT:
        dataset = dataset[:DOCUMENT_LIMIT]
    dataset_size = len(dataset)
    
    if os.path.exists(output_file):
        unprocessed_ids = extract_unprocessed_docs(output_file)
        processed_ids = load_processed_ids(output_file, unprocessed_ids)
    else:
        processed_ids = []
        unprocessed_ids = [data.get('metadata', {}).get('data_id') for data in dataset]

    print(f"Processing {dataset_size} documents ({len(processed_ids)} already done)")
    print(f"Processing mode: {PROCESSING_MODE.upper()}")

    # Extract statistics from existing results
    (existing_matched, existing_unmatched_gt, existing_unmatched_llm,
     existing_unmatched_gt_pii, existing_unmatched_llm_pii, existing_total_subjects,
     existing_gt_only_cases, existing_processed_count) = extract_stats_from_existing_results(output_file)

    if existing_processed_count > 0:
        print(f"Found {existing_processed_count} existing processed documents with statistics")

    total_processed = 0
    total_errors = 0
    total_matched = 0
    total_unmatched_gt = 0
    total_unmatched_llm = 0
    total_unmatched_gt_pii = 0
    total_unmatched_llm_pii = 0
    total_subjects = 0
    gt_only_cases = []
    error_data_ids = []
    processing_time = 0
    if dataset_size == len(processed_ids):
        print("All documents already processed!")
    else:
        start_time = time.time()

        if PROCESSING_MODE == 'sequential':
            (total_processed, total_errors, total_matched,
            total_unmatched_gt, total_unmatched_llm, total_unmatched_gt_pii, total_unmatched_llm_pii,
            total_subjects, gt_only_cases, error_data_ids) = process_sequential(
                dataset, output_file, processed_ids
            )
        else:
            unprocessed_docs = [
                (data, idx) for idx, data in enumerate(dataset)
                if data.get('metadata', {}).get('data_id', f'line_{idx}') in unprocessed_ids
            ]

            (total_processed, total_errors, total_matched,
            total_unmatched_gt, total_unmatched_llm, total_unmatched_gt_pii, total_unmatched_llm_pii,
            total_subjects, gt_only_cases, error_data_ids) = process_concurrent(
                unprocessed_docs, output_file,
                len(processed_ids), dataset_size, NUM_WORKERS
            )

        end_time = time.time()
        processing_time = end_time - start_time

    # Combine new statistics with existing statistics
    combined_matched = total_matched + existing_matched
    combined_unmatched_gt = total_unmatched_gt + existing_unmatched_gt
    combined_unmatched_llm = total_unmatched_llm + existing_unmatched_llm
    combined_unmatched_gt_pii = total_unmatched_gt_pii + existing_unmatched_gt_pii
    combined_unmatched_llm_pii = total_unmatched_llm_pii + existing_unmatched_llm_pii
    combined_total_subjects = total_subjects + existing_total_subjects
    combined_gt_only_cases = gt_only_cases + existing_gt_only_cases
    combined_processed_count = total_processed + existing_processed_count

    total_unique_subjects = combined_matched + combined_unmatched_gt + combined_unmatched_llm
    total_gt_subjects = combined_matched + combined_unmatched_gt
    match_ratio = combined_matched / total_gt_subjects if total_gt_subjects > 0 else 0
    gt_miss_ratio = combined_unmatched_gt / total_gt_subjects if total_gt_subjects > 0 else 0

    # Add alignment statistics to first document's metadata
    alignment_summary = {
        "total_documents": dataset_size,
        "newly_processed": total_processed + total_errors,
        "success": total_processed,
        "errors": total_errors,
        "error_data_ids": error_data_ids,
        "already_processed": len(processed_ids),
        "total_subjects_gt_llm": combined_total_subjects,
        "total_unique_subjects": total_unique_subjects,
        "total_gt_subjects": total_gt_subjects,
        "matched_subjects": combined_matched,
        "gt_only_subjects": combined_unmatched_gt,
        "gt_only_piis": combined_unmatched_gt_pii,
        "llm_only_subjects": combined_unmatched_llm,
        "llm_only_piis": combined_unmatched_llm_pii,
        "match_ratio": round(match_ratio, 4),
        "gt_miss_ratio": round(gt_miss_ratio, 4),
        "average_matched_per_doc": round(combined_matched/combined_processed_count, 2) if combined_processed_count > 0 else 0,
        "documents_with_gt_only_subjects": len(combined_gt_only_cases),
        "processing_time_seconds": round(processing_time, 2),
        "average_time_per_doc": round(processing_time/(total_processed + total_errors), 2) if (total_processed + total_errors) > 0 else 0
    }

    # Add metadata to aligned file
    if os.path.exists(output_file):
        aligned_docs = []

        with open(output_file, 'r', encoding='utf-8') as f:
            file_lines = f.readlines()

        # Read all aligned documents, skip error documents
        for line in file_lines:
            data = json.loads(line)
            data_id = data.get('metadata', {}).get('data_id', '')
            if data_id in error_data_ids:
                continue
            elif data.get('status', '') == 'error':
                continue
            else:
                aligned_docs.append(data)

        # Add gt_only_subject for error documents
        # Only count error stats on final iteration (iteration >= 2 or no more retries)
        is_final_iteration = not (total_errors > 0 and iteration + 1 < 3)
        for error_data_id in error_data_ids:
            error_doc = gt_only_subject(dataset, error_data_id)
            if error_doc:
                aligned_docs.append(error_doc)
                # Count error document's GT subjects as unmatched (only on final iteration)
                if is_final_iteration:
                    error_subjects = error_doc.get('subjects', [])
                    error_gt_count = len(error_subjects)
                    error_gt_pii_count = sum(
                        len([p for p in s.get('PIIs', {}).get('annotation_A', []) if p.get('keyword', '').strip()])
                        for s in error_subjects
                    )
                    combined_unmatched_gt += error_gt_count
                    combined_unmatched_gt_pii += error_gt_pii_count
                    combined_gt_only_cases.append({
                        'data_id': error_data_id,
                        'unmatched_gt_ids': list(range(error_gt_count)),
                        'unmatched_gt_count': error_gt_count
                    })

        # Recalculate stats if final iteration had errors
        if is_final_iteration and error_data_ids:
            total_gt_subjects = combined_matched + combined_unmatched_gt
            match_ratio = combined_matched / total_gt_subjects if total_gt_subjects > 0 else 0
            gt_miss_ratio = combined_unmatched_gt / total_gt_subjects if total_gt_subjects > 0 else 0
            alignment_summary["total_gt_subjects"] = total_gt_subjects
            alignment_summary["gt_only_subjects"] = combined_unmatched_gt
            alignment_summary["gt_only_piis"] = combined_unmatched_gt_pii
            alignment_summary["match_ratio"] = round(match_ratio, 4)
            alignment_summary["gt_miss_ratio"] = round(gt_miss_ratio, 4)
            alignment_summary["documents_with_gt_only_subjects"] = len(combined_gt_only_cases)

        # Add alignment_summary to first document's metadata
        if aligned_docs:
            aligned_docs[0]["metadata"]["alignment_summary"] = alignment_summary

            # Rewrite file with updated metadata
            with open(output_file, 'w', encoding='utf-8') as f:
                for doc in aligned_docs:
                    f.write(json.dumps(doc, ensure_ascii=False) + '\n')

    print(f"\n{'='*50}")
    print(f"GT-based Alignment Complete!")
    print(f"{'='*50}")
    print(f"Mode: {PROCESSING_MODE.upper()}")
    if PROCESSING_MODE == 'concurrent':
        print(f"Workers: {NUM_WORKERS}")
    print(f"Model: {MODEL}")
    print(f"Output: {output_file}")
    print(f"{'='*50}")
    print(f"Total documents: {dataset_size}")
    print(f"Newly processed: {total_processed + total_errors}")
    print(f"Success: {total_processed}")
    print(f"Errors: {total_errors}")
    if error_data_ids:
        print(f"Error data IDs: {error_data_ids}")
    print(f"Already processed: {len(processed_ids)}")
    print(f"{'='*50}")
    print(f"COMBINED STATISTICS (existing + newly processed):")
    print(f"Total GT subjects: {total_gt_subjects}")
    print(f"Matched subjects: {combined_matched}")
    print(f"GT-only subjects (LLM missed): {combined_unmatched_gt} (PIIs: {combined_unmatched_gt_pii})")
    print(f"LLM-only subjects (ignored): {combined_unmatched_llm} (PIIs: {combined_unmatched_llm_pii})")
    print(f"Match ratio (GT-based): {match_ratio:.2%}")
    print(f"GT miss ratio (GT-based): {gt_miss_ratio:.2%}")
    if combined_processed_count > 0:
        print(f"Average matched per document: {combined_matched/combined_processed_count:.2f}")
    print(f"Documents with GT-only subjects: {len(combined_gt_only_cases)}")
    print(f"{'='*50}")
    if existing_processed_count > 0:
        print(f"NEWLY PROCESSED STATISTICS:")
        print(f"Newly processed subjects (GT + LLM): {total_subjects}")
        print(f"Newly matched subjects: {total_matched}")
        print(f"Newly GT-only subjects: {total_unmatched_gt} (PIIs: {total_unmatched_gt_pii})")
        print(f"Newly LLM-only subjects: {total_unmatched_llm} (PIIs: {total_unmatched_llm_pii})")
        print(f"{'='*50}")
    print(f"Processing time: {processing_time:.2f} seconds")
    if total_processed + total_errors > 0:
        print(f"Average time per doc: {processing_time/(total_processed + total_errors):.2f} seconds")

    if total_errors > 0 and iteration + 1 < 3:
        print(f"\nRunning again for the {iteration+1}th time")
        main(iteration + 1)
    else:
        print(f"Processing complete after {iteration} iterations")

if __name__ == "__main__":
    main()