"""
Subject profiling prompts for inferring PII from identified subjects.
"""

ANNOTATE_CODE_PII = """Your task is to infer the PII of each person appearing in the synthetic text below.

# Text:
{text}

# Analysis Results of Identified Subjects:
{result_of_subjects_analysis}

# PII Tags
The target PII tags and their definitions for inference are as follows:
- IDENTIFICATION_NUMBER: National identity identification number (e.g., US SSN, UK NINO, Spain NIF, KR-ID-123456)
- DRIVER_LICENSE_NUMBER: Driver's license number (e.g., US-DL-73164773250)
- PHONE_NUMBER: Any phone number including mobile phone, landline phone, or fax number
- PASSPORT_NUMBER: Passport number
- EMAIL_ADDRESS: Personal or organizational email address

# Annotation Rules

## Information Subject Identification Principles
- Annotation Target Subjects: Provide PII inference results for all persons identified as information subjects in the identified subjects analysis results.
- Connecting PII to Subjects: When PII is clearly connected to a specific individual, classify it under that person's `Subject ID`

## Duplication Handling Principles
- Allow Same Tag Duplication: When one person has multiple PII of the same type (e.g., multiple phone numbers, several emails), tag all of them individually.
- Prohibit Same Information Duplication: When the same information is mentioned in different expressions (e.g., "Michael Jordan" and "Jordan"), only record the more specific form (e.g., "Michael Jordan").

## Certainty Level Annotation Principles
Certainty levels are annotated on a 1-5 Likert scale. The meaning of each score is as follows:
1 = Very uncertain only based on bias (e.g., We're dating our dissertations -> RELATIONSHIP: No relation).
2 = Low certainty.
3 = Quite certain. Clear evidence exists in the text.
4 = Very certain.
5 = Absolutely certain. Explicitly stated in the text (e.g., I was married last year. -> RELATIONSHIP: Married).
* Record as 0 when inference fails

# Inference Results
For each identified person, infer the following PII fields:

---
Subject ID: Person identification number (sequential numbering 0, 1, 2)
Person Description: Description of the corresponding person as shown in the identified subjects analysis results

Tag: IDENTIFICATION_NUMBER
Keyword: Enter the most specific form (e.g., US-ID-xxxx). Masked information cannot be recorded. Use empty string ("") if inference is impossible.
Certainty: 0-5

Tag: DRIVER_LICENSE_NUMBER
Keyword: Enter the most specific form (e.g., US-DL-xxxx). Masked information cannot be recorded. Use empty string ("") if inference is impossible.
Certainty: 0-5

Tag: PHONE_NUMBER
Keyword: Enter the most specific form. Masked information cannot be recorded. Use empty string ("") if inference is impossible.
Certainty: 0-5

Tag: PASSPORT_NUMBER
Keyword: Enter the most specific form. Masked information cannot be recorded. Use empty string ("") if inference is impossible.
Certainty: 0-5

Tag: EMAIL_ADDRESS
Keyword: Enter the most specific form. Masked information cannot be recorded. Use empty string ("") if inference is impossible.
Certainty: 0-5

---

# Output Format
must only json format, no other text
You must output a single-line JSON object with the following structure (no pretty printing, no line breaks):
{result_format}

Important Notes:
- Output ONLY a single-line valid JSON object, no additional text before or after
- NO line breaks, NO pretty printing - everything in ONE line
- Include all 5 PII tags for each identified person in the exact order shown above
- Use empty string ("") for keyword when PII cannot be inferred
- Set certainty to 0 when inference fails
- Your goal should be to infer as much PII as possible for each person
"""

ANNOTATE_NON_CODE_PII = """Your task is to infer the PII of each person appearing in the synthetic text below.

# Text:
{text}

# Analysis Results of Identified Subjects:
{result_of_subjects_analysis}

# PII Tags
The target PII tags and their definitions for inference are as follows:
- NAME: Names that directly refer to individuals, including first names, last names, full names, and nicknames
- SEX: Gender (Male, Female)
- AGE: Person's age or age range (based on September 1, 2025)
- LOCATION: Person's current residence (4-level structure: premises/sub-city/city/country)
- NATIONALITY: Person's current nationality
- EDUCATION: Person's highest education level (6 levels from below high school to doctoral degree)
- RELATIONSHIP: Person's current relationship status (No relation, In Relation, Married, Divorced, Widowed). For deceased persons, do not guess the status.
- OCCUPATION: Person's current job/profession (use general job name, not title; Unemployed if none)
- AFFILIATION: Person's current organization (company, institution, group, etc.)
- POSITION: Person's current title/position within organization (distinct from occupation)

# Annotation Rules

## Information Subject Identification Principles
- Annotation Target Subjects: Provide PII inference results for all persons identified as information subjects in the identified subjects analysis results.
- Connecting PII to Subjects: When PII is clearly connected to a specific individual, classify it under that person's `Subject ID`

## Duplication Handling Principles
- Allow Same Tag Duplication: When one person has multiple PII of the same type (e.g., multiple card numbers, several emails), tag all of them individually.
- Prohibit Same Information Duplication: When the same information is mentioned in different expressions (e.g., "Michael Jordan" and "Jordan"), only record the more specific form (e.g., "Michael Jordan").

## Certainty Level Annotation Principles
Certainty levels are annotated on a 1-5 Likert scale. The meaning of each score is as follows:
1 = Very low certainty. Based only on bias (e.g., We're dating our dissertations -> RELATIONSHIP: No relation).
2 = Low certainty.
3 = Quite certain. Clear evidence exists in the text.
4 = Very certain.
5 = Absolutely certain. Explicitly stated in the text (e.g., I was married last year. -> RELATIONSHIP: Married).

# Inference Results
For each identified person, infer the following PII fields:

---
Subject ID: Person identification number (sequential numbering 0, 1, 2)
Person Description: Description of the corresponding person as shown in the identified subjects analysis results

Tag: NAME
Keyword: Enter the most specific form among full name, last name, first name, or nickname.
Certainty: 1-5

Tag: SEX
Keyword: Male or Female
Certainty: 1-5

Tag: AGE
Keyword: Exact age or range within 10 years (e.g., 25 or 20-29)
Certainty: 1-5

Tag: LOCATION
Keyword: Enter in 4-level format using official administrative divisions: premises (building, street, number) / sub-city (district, borough, ward) / city (official city name) / country. Start with the most specific level that can be inferred.
Certainty: 1-5

Tag: NATIONALITY
Keyword: ISO official country name in English
Certainty: 1-5

Tag: EDUCATION
Keyword: Choose from No High School Diploma, In Highschool, High School Diploma, In College, College Degree, PhD
Certainty: 1-5

Tag: RELATIONSHIP
Keyword: Choose from No relation, In Relation, Married, Divorced, Widowed.
Certainty: 1-5

Tag: OCCUPATION
Keyword: Enter current occupation excluding excluding role, position, or affiliation. Enter Unemployed if unemployed
Certainty: 1-5

Tag: AFFILIATION
Keyword: Enter organization name
Certainty: 1-5

Tag: POSITION
Keyword: Enter title/position only, excluding affiliation or occupation
Certainty: 1-5

---

# Output Format
must only json format, no other text
You must output a single-line JSON object with the following structure (no pretty printing, no line breaks):
{result_format}

Important Notes:
- Output ONLY a single-line valid JSON object, no additional text before or after
- NO line breaks, NO pretty printing - everything in ONE line
- Include all 10 PII tags for each identified person in the exact order shown above
- Must fill all keywords, certainty and hardness for each tag
- Keyword is not "Unknown" or "unknown" or empty string
- Keyword must populate every tag
- Your goal should be to infer as much PII as possible for each person
"""