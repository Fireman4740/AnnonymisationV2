ALIGN_SUBJECTS_ACROSS_ANNOTATIONS = """
Your task is to match and align subject IDs across two different annotation results for the same text.

# Text:
{text}

# Annotation A:
{annotation_a}

# Annotation B:
{annotation_b}

# Matching Rules

## Subject Matching Principles
- Matched Subjects: When matched as the same subject, enter "Matched" in the "Result" and separate the subject IDs from both Annotation types (A, B) with a semicolon (;)
- Unmatched Subjects: When not matched as the same subject (a subject identified in only one annotation), classify as "Unmatched" and enter the subject ID from the relevant Annotation type (A or B)
- One-to-One Correspondence: Matched subjects must have a 1:1 correspondence; one subject should not include multiple persons (IDs)

# Matching Results
Present your matching analysis for each subject according to the format below:

---
Reasoning: Your detailed reasoning with specific evidence from descriptions and PII
Result: Matched OR Unmatched
Subject: [If Matched: A_id; B_id] [If Unmatched: A_id OR B_id]

---

Important Notes:
- Ensure every subject from both annotations appears exactly once in your results.
- Do not provide responses outside the allowed output format.
"""

ALIGN_SUBJECTS_ACROSS_ANNOTATIONS_ANON = """
Your task is to match and align subject IDs across two different annotation results.
Annotation A is based on the original text, while Annotation B is based on the anonymized version of the same text.

# Original Text:
{original_text}

# Anonymized Text:
{anonymized_text}

# Annotation A (from Original Text):
{annotation_a}

# Annotation B (from Anonymized Text):
{annotation_b}

# Matching Rules

## Subject Matching Principles
- Matched Subjects: When matched as the same subject, enter "Matched" in the "Result" and separate the subject IDs from both Annotation types (A, B) with a semicolon (;)
- Unmatched Subjects: When not matched as the same subject (a subject identified in only one annotation), classify as "Unmatched" and enter the subject ID from the relevant Annotation type (A or B)
- One-to-One Correspondence: Matched subjects must have a 1:1 correspondence; one subject should not include multiple persons (IDs)

## Anonymization Considerations
- Anonymization may cause some subjects to become unidentifiable or absent in the anonymized version
- Focus on subject descriptions, roles, and contextual clues rather than exact PII values
- If a subject in Annotation A has no identifiable counterpart in Annotation B, mark it as Unmatched

# Matching Results
Present your matching analysis for each subject according to the format below:

---
Reasoning: Your detailed reasoning with specific evidence from descriptions and contextual roles
Result: Matched OR Unmatched
Subject: [If Matched: A_id; B_id] [If Unmatched: A_id OR B_id]

---

Important Notes:
- Ensure every subject from both annotations appears exactly once in your results.
- Do not provide responses outside the allowed output format.
"""