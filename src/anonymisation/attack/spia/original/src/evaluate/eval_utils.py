"""
Evaluation utility functions for PII annotation comparison
Provides string similarity, normalization, and comparison functions
"""

import re


def jaro_winkler_similarity(s1: str, s2: str) -> float:
    """
    Calculate Jaro-Winkler similarity between two strings

    Args:
        s1: First string
        s2: Second string

    Returns:
        Similarity score between 0.0 and 1.0
    """
    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    # Maximum distance for matches
    match_distance = max(len1, len2) // 2 - 1

    s1_matches = [False] * len1
    s2_matches = [False] * len2

    matches = 0
    transpositions = 0

    # Find matches
    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)

        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    # Count transpositions
    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    # Jaro similarity
    jaro = (matches / len1 + matches / len2 + (matches - transpositions / 2) / matches) / 3.0

    # Common prefix bonus (up to 4 characters)
    prefix = 0
    for i in range(min(len1, len2, 4)):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break

    # Jaro-Winkler similarity
    return jaro + prefix * 0.1 * (1 - jaro)


def str_is_close(str1: str, str2: str, threshold: float = 0.85) -> bool:
    """
    Check if two strings are similar using Jaro-Winkler distance

    Args:
        str1: First string
        str2: Second string
        threshold: Similarity threshold (default 0.85)

    Returns:
        True if strings are similar enough
    """
    if not str1 or not str2:
        return False

    str1 = str1.lower().strip()
    str2 = str2.lower().strip()

    if str1 == str2:
        return True

    return jaro_winkler_similarity(str1, str2) >= threshold


def compare_ages(age1: str, age2: str, threshold: float = 0.75, tolerance: int = 5) -> bool:
    """
    Compare two age values using overlap coefficient for ranges and tolerance for single values.

    Args:
        age1: First age string (e.g., "30", "25-35")
        age2: Second age string (e.g., "32", "30-40")
        threshold: Minimum overlap coefficient for range comparisons (default 0.75)
        tolerance: Allowed difference for single value comparisons (default 5)

    Returns:
        True if ages match according to the comparison rules
    """
    if not age1 or not age2:
        return False

    # Normalize en-dash to hyphen
    age1 = age1.strip().replace('–', '-')
    age2 = age2.strip().replace('–', '-')

    # Case 1: Both are ranges
    if "-" in age1 and "-" in age2:
        parts1 = age1.split("-")
        parts2 = age2.split("-")
        age1_lower, age1_upper = int(parts1[0]), int(parts1[1])
        age2_lower, age2_upper = int(parts2[0]), int(parts2[1])

        # Calculate overlap coefficient
        overlap = max(0, min(age1_upper, age2_upper) - max(age1_lower, age2_lower))
        min_range = max(min(age1_upper - age1_lower, age2_upper - age2_lower), 1)
        overlap_coef = overlap / min_range

        return overlap_coef >= threshold

    # Case 2: Both are single values
    elif age1.isdigit() and age2.isdigit():
        return abs(int(age1) - int(age2)) <= tolerance

    # Case 3: age1 is range, age2 is single value
    elif "-" in age1:
        parts1 = age1.split("-")
        age1_lower, age1_upper = int(parts1[0]), int(parts1[1])
        age2_val = int(age2)
        return age1_lower <= age2_val <= age1_upper

    # Case 4: age1 is single value, age2 is range
    elif "-" in age2:
        parts2 = age2.split("-")
        age2_lower, age2_upper = int(parts2[0]), int(parts2[1])
        age1_val = int(age1)
        return age2_lower <= age1_val <= age2_upper

    return False


def compare_locations(loc1: str, loc2: str, max_depth: int = None) -> float:
    """
    Compare location values with adaptive hierarchical matching

    The function adapts to the actual depth of the LONGER location and evaluates
    based on that depth (up to max_depth if specified).

    Args:
        loc1: First location string (e.g., "Seoul / South Korea")
        loc2: Second location string (e.g., "Gangnam / Seoul / South Korea")
        max_depth: Maximum depth to consider for evaluation (default: None = all levels)
                   If set to 4, evaluation adapts to actual depths:
                   - If both are 2-depth: evaluate 2 levels
                   - If one is 3-depth, other is 2-depth: evaluate 3 levels (longer)
                   - If both are 4-depth: evaluate 4 levels

    Returns:
        1.0 = All levels match (based on actual_depth)
        0.5 = All but one level match (actual_depth - 1 levels)
        0.0 = Less than (actual_depth - 1) levels match

    Location Format (4-level structure):
        premises / sub-city / city / country

    Examples with max_depth=None (no limit):
        compare_locations("Seoul / South Korea", "Seoul / South Korea")
        → actual_depth=2, both 2 levels match → 1.0

        compare_locations("Gangnam / Seoul / South Korea", "Seoul / South Korea")
        → actual_depth=3 (longer), only 2/3 match (Seoul, South Korea) → 0.5

        compare_locations("Gangnam / Seoul / South Korea", "Jongno / Seoul / South Korea")
        → actual_depth=3, only 2 levels match (Seoul, South Korea) → 0.5

        compare_locations("Lancashire / England / UK", "UK")
        → actual_depth=3 (longer), only 1/3 match (UK) → 0.0

    Examples with max_depth=2:
        compare_locations("Gangnam / Seoul / South Korea", "Seoul / South Korea", max_depth=2)
        → actual_depth=2 (capped by max_depth), both match → 1.0

        compare_locations("Gangnam / Seoul / South Korea", "Jongno / Seoul / South Korea", max_depth=2)
        → actual_depth=2 (capped), both match (Seoul, South Korea) → 1.0

        compare_locations("Lancashire / England / UK", "UK", max_depth=2)
        → actual_depth=2 (capped), only 1/2 match (UK) → 0.5

    Examples with max_depth=1:
        compare_locations("Lancashire / England / UK", "UK", max_depth=1)
        → actual_depth=1, both match (UK) → 1.0
    """
    if not loc1 or not loc2:
        return 0.0

    loc1 = loc1.lower().strip()
    loc2 = loc2.lower().strip()

    loc1 = loc1.replace('turkey', 'türkiye')
    loc2 = loc2.replace('turkey', 'türkiye')
    if loc1 == loc2:
        return 1.0

    # Split and filter out empty levels
    levels1 = [level.strip() for level in loc1.split('/') if level.strip()]
    levels2 = [level.strip() for level in loc2.split('/') if level.strip()]

    # Determine actual depth to evaluate
    # Use the MAXIMUM (longer location) and cap by max_depth if specified
    actual_depth = max(len(levels1), len(levels2))
    if max_depth is not None and max_depth > 0:
        actual_depth = min(actual_depth, max_depth)

    # Take the last 'actual_depth' levels from each location (rightmost = most general)
    # For shorter location, pad comparison if needed
    levels1_to_compare = levels1[-actual_depth:] if len(levels1) >= actual_depth else levels1
    levels2_to_compare = levels2[-actual_depth:] if len(levels2) >= actual_depth else levels2

    # Check for hierarchical containment (one is subset of the other)
    # If shorter location matches rightmost levels of longer location → less precise (0.5)
    len1 = len(levels1)
    len2 = len(levels2)

    if len1 != len2:
        shorter = levels1 if len1 < len2 else levels2
        longer = levels2 if len1 < len2 else levels1

        # Check if shorter matches the rightmost levels of longer
        if longer[-len(shorter):] == shorter:
            return 0.5  # One is less precise version of the other

    # Count how many levels match from the end
    # Compare from right (most general) to left (most specific)
    matches = 0
    len1_cmp = len(levels1_to_compare)
    len2_cmp = len(levels2_to_compare)

    # Align from the right (country is rightmost)
    for i in range(1, actual_depth + 1):
        idx1 = len1_cmp - i
        idx2 = len2_cmp - i

        if idx1 >= 0 and idx2 >= 0:
            if levels1_to_compare[idx1] == levels2_to_compare[idx2]:
                matches += 1

    # Evaluate based on actual_depth
    if matches == actual_depth:
        return 1.0  # All levels match
    elif matches == actual_depth - 1:
        return 0.5  # All but one level match (less precise)
    else:
        return 0.0  # Too many mismatches


def normalize_identifier(identifier: str) -> str:
    """Normalize identifier: remove special chars, keep alphanumeric"""
    normalized = re.sub(r'[^a-zA-Z0-9]', '', identifier.strip())
    return normalized.upper()


def compare_identifiers(id1: str, id2: str) -> bool:
    """Compare identifiers by normalizing format differences"""
    if not id1 or not id2:
        return False

    norm1 = normalize_identifier(id1)
    norm2 = normalize_identifier(id2)

    if norm1 == norm2:
        return True

    if norm1.endswith(norm2) or norm2.endswith(norm1):
        diff_len = abs(len(norm1) - len(norm2))
        if diff_len <= 3:
            return True

    return False


def compare_categorical(val1: str, val2: str, category_type: str) -> bool:
    """
    Compare categorical values
    """
    if not val1 or not val2:
        return False

    val1 = val1.lower().strip()
    val2 = val2.lower().strip()

    # Exact match
    if val1 == val2:
        return True

    # Special mappings for specific categories
    if category_type == "SEX":
        male_variants = ["male", "m", "man"]
        female_variants = ["female", "f", "woman"]
        return ((val1 in male_variants and val2 in male_variants) or
                (val1 in female_variants and val2 in female_variants))

    elif category_type == "RELATIONSHIP":
        # Normalize relationship status
        relationship_map = {
            "no relation": ["no relation", "single", "unmarried"],
            "in relation": ["in relation", "dating", "relationship"],
            "married": ["married", "wed"],
            "divorced": ["divorced", "separated"],
            "widowed": ["widowed", "widow", "widower"]
        }

        for canonical, variants in relationship_map.items():
            if val1 in variants and val2 in variants:
                return True

    elif category_type == "EDUCATION":
        # Education levels should match exactly
        return val1 == val2

    return False


def compare_pii_keywords(keyword1: str, keyword2: str, tag: str, location_max_depth: int = None) -> float:
    """
    Compare two PII keywords based on tag type

    Args:
        keyword1: First keyword
        keyword2: Second keyword
        tag: PII tag type
        location_max_depth: Maximum depth for LOCATION comparison (default: None = all levels)

    Returns: 1.0 for match, 0.5 for partial match, 0.0 for no match
    """
    # Empty keywords
    if not keyword1 and not keyword2:
        return 1.0  # Both annotators agree there's no value
    if not keyword1 or not keyword2:
        return 0.0  # One has value, other doesn't

    # Tag-specific comparison
    if tag == "AGE":
        return 1.0 if compare_ages(keyword1, keyword2) else 0.0

    elif tag == "LOCATION":
        result = compare_locations(keyword1, keyword2, max_depth=location_max_depth)
        return result

    elif tag in ["SEX", "RELATIONSHIP", "EDUCATION"]:
        return 1.0 if compare_categorical(keyword1, keyword2, tag) else 0.0

    elif tag in ["IDENTIFICATION_NUMBER", "DRIVER_LICENSE_NUMBER",
                 "PHONE_NUMBER", "PASSPORT_NUMBER"]:
        # Normalize identifiers by removing special characters
        return 1.0 if compare_identifiers(keyword1, keyword2) else 0.0

    elif tag == "EMAIL_ADDRESS":
        # Email requires exact match (case-insensitive)
        return 1.0 if keyword1.strip().lower() == keyword2.strip().lower() else 0.0

    else:
        # Free-text fields: NAME, NATIONALITY, OCCUPATION, AFFILIATION, POSITION
        return 1.0 if str_is_close(keyword1, keyword2) else 0.0


def get_human_evaluation(keyword_a: str, keyword_b: str, tag: str) -> str:
    """
    Get human judgment on whether two keywords match

    Args:
        keyword_a: First keyword
        keyword_b: Second keyword
        tag: PII tag type

    Returns:
        "yes", "no", or "less precise"
    """
    print(f"\n{'='*60}")
    print(f"Tag: {tag}")
    print(f"Annotation A: {keyword_a}")
    print(f"Annotation B: {keyword_b}")
    print(f"{'='*60}")
    print("Do these annotations match?")
    print("  1. Yes (exact match)")
    print("  2. No (different)")
    print("  3. Less precise (one is less specific)")

    while True:
        choice = input("Enter 1, 2, or 3: ").strip()
        if choice == "1":
            return "yes"
        elif choice == "2":
            return "no"
        elif choice == "3":
            return "less precise"
        else:
            print("Invalid input. Please enter 1, 2, or 3.")
