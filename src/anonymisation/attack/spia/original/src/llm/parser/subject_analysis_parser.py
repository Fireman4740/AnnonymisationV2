"""
Parser for subject analysis (SA) responses
"""
import re


def clear_subjects_analysis_response(response):
    """
    Extract text from "Individual Character Analysis:" line
    to "The Number of Subjects: ???" line from LLM response

    Args:
        response (str): LLM response text

    Returns:
        str: Extracted analysis section text, or empty string if not found
    """
    
    response = response.replace('**', '')
    response = response.replace('\n', ' ')
    # Try multiple pattern variations for flexibility
    patterns = [
        # Original strict pattern
        r'Individual Character Analysis.*?(?:The\s+)?Number of Subjects:\s*\d+',
        # More flexible: allow variations in "Individual" section header
        r'Individual\s+(?:Character\s+)?Analysis.*?(?:The\s+)?Number of Subjects:\s*\d+',
        # Even more flexible: look for analysis section and subject count
        r'(?:Individual|Character).*?Analysis.*?(?:The\s+)?Number of Subjects:\s*\d+',
        # Handle "Total Number of Unique Individuals Counted: ... = X" format
        r'Individual\s+(?:Character\s+)?Analysis.*?Total\s+Number\s+of\s+Unique\s+Individuals\s+Counted:.*?=\s*\d+',
        # Fallback: just find subject count with some context before it
        r'(?:- .*?\n){1,}.*?(?:The\s+)?Number of Subjects:\s*\d+',
        # Fallback for Total Number pattern
        r'(?:- .*?\n){1,}.*?Total\s+Number\s+of\s+Unique\s+Individuals\s+Counted:.*?=\s*\d+',
        r'Individuals Identified:.*?The Number of Subjects:\s*\d+',
        r'Number of Subjects:\s*\d+.*?Individuals Identified:.*?',
    ]

    for pattern in patterns:
        match = re.search(pattern, response, re.DOTALL | re.IGNORECASE)
        if match:
            return "success", response[match.start():]

    # Last resort: if we can find "Number of Subjects" or "Total Number" at all, return everything before it
    number_patterns = [
        r'The\s+Number of Subjects:\s*(\d+)',
        r'The Number of Subjects:\s*(\d+)',
        r'(?:The\s+)?Number\s+of\s+Subjects:\s*(\d+)',
        # Handle "Total Number of Unique Individuals Counted: ... = X"
        r'Total\s+Number\s+of\s+Unique\s+Individuals\s+Counted:.*?=\s*(\d+)',
    ]

    for num_pattern in number_patterns:
        # Find the number and return reasonable context
        match = re.search(num_pattern, response, re.DOTALL | re.IGNORECASE)
        if match:
            return "success", response[match.start():]

    return "error", response


def parse_number_of_subjects(response):
    # Try to find "Number of Subjects:" with various patterns
    patterns = [
        r'The\s+Number of Subjects:\s*(\d+)',
        r'The Number of Subjects:\s*(\d+)',
        r'(?:The\s+)?Number\s+of\s+Subjects:\s*(\d+)',
        # Handle "Total Number of Unique Individuals Counted: ... = X"
        r'Total\s+Number\s+of\s+Unique\s+Individuals\s+Counted:.*?=\s*(\d+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, response, re.IGNORECASE | re.DOTALL)
        if match:
            number_of_subjects = int(match.group(1))
            return "success", number_of_subjects

    # Fallback: try to split and search
    for split_phrase in ["The Number of Subjects:", "Number of Subjects:", "Total Number of Unique Individuals Counted:"]:
        if split_phrase.lower() in response.lower():
            # Find the position and extract number after it
            pos = response.lower().find(split_phrase.lower())
            number_text = response[pos + len(split_phrase):].strip()

            # For "Total Number..." pattern, look for "= number"
            if "total number of unique" in split_phrase.lower():
                equals_match = re.search(r'=\s*(\d+)', number_text)
                if equals_match:
                    number_of_subjects = int(equals_match.group(1))
                    return "success", number_of_subjects

            number_match = re.search(r'\d+', number_text)
            if number_match:
                number_of_subjects = int(number_match.group())
                return "success", number_of_subjects

    return "error", response
