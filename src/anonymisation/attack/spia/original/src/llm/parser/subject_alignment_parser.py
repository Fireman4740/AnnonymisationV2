"""
Parser for subject alignment responses
"""
import re


def parse_subject_alignment_response(response):
    """
    Parse alignment response to extract matched subject pairs

    Args:
        response (str): LLM alignment response with sections separated by "---"

    Returns:
        tuple: (status, result)
            - status: "success" or "error"
            - result: List of matched pairs [(A_id, B_id), ...] or error message

    Example response format:
        ---
        Reasoning: Both describe the same person...
        Result: Matched
        Subject: A_0; B_0
        ---
        Reasoning: Only in annotation A...
        Result: Unmatched
        Subject: A_3
        ---

    Note: Subject IDs can be any string (e.g., "A_0", "A_h3e9r", "B_abc123")
    """
    try:
        matched_pairs = []

        # Split by "---" delimiter
        sections = response.split("---")

        for section in sections:
            section = section.strip()
            if not section:
                continue

            # Extract Result line
            result_match = re.search(r'Result:\s*(Matched|Unmatched)', section, re.IGNORECASE)
            if not result_match:
                continue

            result = result_match.group(1).strip().lower()

            # Only process Matched results
            if result != "matched":
                continue

            # Extract Subject line AFTER Result line (to avoid matching "Subject" in Reasoning)
            after_result = section[result_match.end():]
            subject_match = re.search(r'Subject:\s*([^\n]+)', after_result, re.IGNORECASE)
            if not subject_match:
                continue

            subject_text = subject_match.group(1).strip()

            # Parse subject IDs (format: "A_xxx; B_yyy" where xxx and yyy can be any string)
            # Allow for optional spaces around semicolon
            # Subject IDs can be alphanumeric strings (e.g., "0", "h3e9r", "abc123")
            # Handle various formats: "A_0; B_1", "A0; B1", "0; 1", "A-0; B-0", etc.
            pair_match = re.match(r'[Aa]?[-:_]?([a-zA-Z0-9_]+)\s*;\s*[Bb]?[-:_]?([a-zA-Z0-9_]+)', subject_text)
            if pair_match:
                a_id = pair_match.group(1)
                b_id = pair_match.group(2)
                matched_pairs.append((a_id, b_id))

        if not matched_pairs:
            return "error", "No matched subject pairs found in response"
        # duplicate removal
        matched_pairs = list(set(matched_pairs))
        return "success", matched_pairs

    except Exception as e:
        return "error", f"Alignment parsing error: {str(e)}"


def validate_subject_matched_pairs(matched_pairs, annotation_a, annotation_b):
    """
    Validate that matched pairs reference valid subject IDs

    Args:
        matched_pairs: List of (A_id, B_id) tuples (IDs can be strings or integers)
        annotation_a: List of subjects from annotation A
        annotation_b: List of subjects from annotation B

    Returns:
        tuple: (status, result)
            - status: "success" or "error"
            - result: Valid matched pairs or error message
    """
    try:
        valid_pairs = []
        seen_gt_ids = set()  # GT-based First In First Out (FIFO) deduplication

        # Create ID to index mapping for both annotations
        a_id_to_idx = {str(subj.get('id', idx)): idx for idx, subj in enumerate(annotation_a)}
        b_id_to_idx = {str(subj.get('id', idx)): idx for idx, subj in enumerate(annotation_b)}

        for a_id, b_id in matched_pairs:
            # Convert IDs to strings for lookup
            a_id_str = str(a_id)
            b_id_str = str(b_id)
            
            # remain only number
            a_id_str = re.sub(r'[^0-9]', '', a_id_str)
            b_id_str = re.sub(r'[^0-9]', '', b_id_str)

            # GT-based FIFO deduplication: skip already matched GT
            if a_id_str in seen_gt_ids:
                continue

            # Skip Subject IDs that don't exist in annotation
            if a_id_str not in a_id_to_idx:
                continue
            if b_id_str not in b_id_to_idx:
                continue

            # Add only valid matches to seen set
            seen_gt_ids.add(a_id_str)

            # Store the actual array indices
            a_idx = a_id_to_idx[a_id_str]
            b_idx = b_id_to_idx[b_id_str]

            valid_pairs.append((a_idx, b_idx))

        # Error only when no valid matches exist
        if not valid_pairs:
            return "error", "No valid matched pairs after filtering"

        return "success", valid_pairs

    except Exception as e:
        return "error", f"Validation error: {str(e)}"
