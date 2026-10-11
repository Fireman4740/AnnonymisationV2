"""
Parser for subject profiling (SPC/SPNC) responses
"""
import re
import json
import ast


def normalize_non_inferable_keyword(keyword: str, certainty: int, hardness: int) -> tuple:
    """
    Normalize non-inferable keywords to empty string with certainty=0, hardness=0.

    When LLM cannot infer a PII value, it sometimes returns phrases like:
    - "Not inferable", "Not inferable from text"
    - "Unknown", "Unknown location", "Unknown nationality"
    - "Not specified", "Not provided", "Not disclosed"
    - "None", "N/A", "redacted", "[redacted]"

    These should be normalized to (keyword="", certainty=0, hardness=0).

    Args:
        keyword: The keyword value from LLM response
        certainty: The certainty score (0-5)
        hardness: The hardness score

    Returns:
        tuple: (normalized_keyword, normalized_certainty, normalized_hardness)
    """
    if not keyword:
        return "", 0, 0

    kw_lower = keyword.lower().strip()

    # Exact match patterns - these clearly indicate inference failure
    exact_patterns = {
        "not inferable", "not inferable from text", "not inferable from redacted text",
        "not inferable from redacted data", "none", "n/a", "na",
        "unknown", "not disclosed", "not disclosed in text",
        "not specified", "not specified in text", "not provided",
        "not provided in text", "not determinable", "not determinable from text",
        "not stated", "not stated in text", "not identifiable", "not given", "none provided",
        "no information", "undisclosed", "information not available",
        "redacted", "[redacted]", "redacted in source",
        "not available", "not available due to removal", "not available in text",
        "not mentioned", "not mentioned in text",
        "none identified", "none apparent", "none known", "none mentioned",
        "none specified", "none identifiable",
    }

    if kw_lower in exact_patterns:
        return "", 0, 0

    # Contains patterns - keyword contains these phrases
    contains_patterns = [
        "not inferable", "redacted", "masked", "anonymized",
        "not disclosed", "not specified", "not provided",
        "not determinable", "not identifiable", "not available",
        "not mentioned", "not stated",
    ]
    if any(p in kw_lower for p in contains_patterns):
        return "", 0, 0

    # Starts with "unknown " (e.g., "Unknown location", "Unknown nationality")
    if kw_lower.startswith("unknown "):
        return "", 0, 0

    # Ends with "unknown" (e.g., "Location unknown", "Occupation unknown")
    if kw_lower.endswith(" unknown"):
        return "", 0, 0

    # Contains "unknown from" (e.g., "Nationality unknown from passport")
    if " unknown from" in kw_lower:
        return "", 0, 0

    # Ends with "not specified" (e.g., "Country not specified", "Location not specified")
    if kw_lower.endswith("not specified"):
        return "", 0, 0

    # Pattern: "X / unspecified country", "X / Unknown" or similar
    if "unspecified" in kw_lower or "undisclosed" in kw_lower:
        return "", 0, 0

    # Pattern: "X / Unknown / Unknown" (partial unknown locations)
    if "/ unknown" in kw_lower:
        return "", 0, 0

    # Pattern: "Name Unknown" (e.g., "Child Name Unknown", "Partner Name Unknown")
    if "name unknown" in kw_lower:
        return "", 0, 0

    # Pattern: starts with "none " (e.g., "None identified", "None apparent")
    if kw_lower.startswith("none "):
        return "", 0, 0

    # Return original values if not a non-inferable pattern
    return keyword, certainty, hardness

def fix_json_string(json_str):
    """Fix common errors in JSON strings"""

    # 1. Remove JSON comments (// ... format) - line by line
    lines = json_str.split('\n')
    lines = [line for line in lines if not line.strip().startswith('//')]
    json_str = '\n'.join(lines)
    json_str = re.sub(r',\s*//[^\n]*', '', json_str)


    json_str = re.sub(r"```json", "", json_str)
    json_str = re.sub(r"```", "", json_str)

    # 2. Replace Chinese commas with English commas
    json_str = json_str.replace('，', ',')

    # 3. Fix incorrect quote patterns
    # Fix 'keyword": to "keyword":
    json_str = re.sub(r"'(\w+)\":", r'"\1":', json_str)

    # Fix 'keyword': to "keyword":
    json_str = re.sub(r"'(\w+)':", r'"\1":', json_str)

    # Fix "keyword': to "keyword":
    json_str = re.sub(r"\"(\w+)':", r'"\1":', json_str)

    # Fix keyword": (no opening quote) to "keyword":
    json_str = re.sub(r'([,{]\s*)(\w+)":', r'\1"\2":', json_str)

    # 4. Remove whitespace from field names (e.g., " pii " -> "pii")
    json_str = re.sub(r'"\s+(\w+)\s+":', r'"\1":', json_str)

    # 5. Remove leading dots from field names (e.g., ".medical_id" -> "medical_id")
    json_str = re.sub(r'"\.(\w+)":', r'"\1":', json_str)

    # 6. Convert single-quoted dictionaries to double quotes
    # Change {'key': to {"key":
    json_str = re.sub(r"\{'", r'{"', json_str)
    json_str = re.sub(r"'\}", r'"}', json_str)
    json_str = re.sub(r"'\s*:", r'":', json_str)
    json_str = re.sub(r":\s*'", r':"', json_str)
    json_str = re.sub(r",\s*'", r',"', json_str)
    json_str = re.sub(r"'\s*,", r'",', json_str)

    # 7. Add missing commas (between }{ without comma)
    json_str = re.sub(r'\}\s*\{', '},{', json_str)

    # 8. Fix bracket issues
    # Change ]}' to ]}
    json_str = re.sub(r"\]}'", r']}', json_str)
    # Change ({ to {
    json_str = re.sub(r'\(\{', '{', json_str)
    # Change }) to }
    json_str = re.sub(r'\}\)', '}', json_str)

    # 9. Remove trailing commas at end of arrays/objects
    json_str = re.sub(r',\s*\]', ']', json_str)
    json_str = re.sub(r',\s*\}', '}', json_str)

    # 10. Try to add missing closing brackets
    open_brackets = json_str.count('[')
    close_brackets = json_str.count(']')
    if open_brackets > close_brackets:
        json_str += ']' * (open_brackets - close_brackets)

    open_braces = json_str.count('{')
    close_braces = json_str.count('}')
    if open_braces > close_braces:
        json_str += '}' * (open_braces - close_braces)

    return json_str

def clean_json_response(response):
    """
    Clean LLM response to extract valid JSON with proper double quotes.

    Core principles:
    1. Extract only complete JSON array/object structures
    2. Convert ALL single quotes (') to double quotes (")
    3. Handle mixed quote formats and malformed JSON
    4. Remove non-JSON text and invalid fields

    Args:
        response: Raw LLM response text

    Returns:
        Cleaned JSON string ready for parsing
    """
    if not response or not isinstance(response, str):
        return ""

    response = fix_json_string(response)

    response = response.replace('\n    ', '')
    response = response.replace('\n ', '')
    response = response.replace('\n', '')
    response = response.replace('  ', ' ')
    response = response.replace('  ', ' ')
    response = response.replace('**', '')
    response = response.replace(' ... ', ' ')
    response = response.replace('[...', '[')
    response = response.replace('...]', ']')
    response = response.replace('...', '')
    response = response.replace('\"', '"')
    response = response.replace('\\\'s', "'s")
    response = response.replace('"s', "'s")
    response = response.replace('`', '')
    response = response.replace('\\', '')
    # Fix malformed object separators before {"id"
    # Pattern: }]}] variants (multiple nested closes)
    response = response.replace('}]}], [{"id"', '}]}, {"id"')
    response = response.replace('}]}], {"id"', '}]}, {"id"')
    response = response.replace('}]}],[{"id"', '}]}, {"id"')
    response = response.replace('}]}][{"id"', '}]}, {"id"')
    response = response.replace('}]}]{"id"', '}]}, {"id"')
    response = response.replace('}]}]}, {"id"', '}]}, {"id"')
    
    # Pattern: }]] variants (array close issues)
    response = response.replace('}]], [{"id"', '}]}, {"id"')
    response = response.replace('}]], {"id"', '}]}, {"id"')
    response = response.replace('}]],[{"id"', '}]}, {"id"')
    response = response.replace('}]][{"id"', '}]}, {"id"')
    response = response.replace('}]],{"id"', '}]}, {"id"')
    
    # Pattern: }}] variants (object close issues)
    response = response.replace('}}], [{"id"', '}]}, {"id"')
    response = response.replace('}}], {"id"', '}]}, {"id"')
    response = response.replace('}}],[{"id"', '}]}, {"id"')
    response = response.replace('}}][{"id"', '}]}, {"id"')
    response = response.replace('}}]),{"id"', '}]}, {"id"')
    response = response.replace('}}],{"id"', '}]}, {"id"')
    
    # Pattern: }} variants (double object closes)
    response = response.replace('}}, [{"id"', '}]}, {"id"')
    response = response.replace('}}, {"id"', '}]}, {"id"')
    response = response.replace('}},[{"id"', '}]}, {"id"')
    response = response.replace('}}[{"id"', '}]}, {"id"')
    response = response.replace('}},{"id"', '}]}, {"id"')
    
    # Pattern: }] variants (single object close)
    response = response.replace('}], [{"id"', '}]}, {"id"')
    response = response.replace('}], {"id"', '}]}, {"id"')
    response = response.replace('}],[{"id"', '}]}, {"id"')
    response = response.replace('}][{"id"', '}]}, {"id"')
    response = response.replace('}],{"id"', '}]}, {"id"')
    
    # Pattern: Special cases (wrong brackets, double braces)
    response = response.replace('}]},{["id"', '}]}, {"id"')
    response = response.replace('}]},{{"id"', '}]}, {"id"')
    response = response.replace('}],{["id"', '}]}, {"id"')
    response = response.replace('}],{{"id"', '}]}, {"id"')
    
    response = response.replace('"hardness}', '"hardness"')
    response = response.replace('}:', '}"')
    response = response.replace(", {}", '')
    response = response.replace("{}", '')
    response = response.replace('{tag:"', '{"tag":"')
    response = response.replace('"tag:"', '"tag":"')
    response = response.replace('"keyword:"', '"keyword":"')
    response = response.replace('"},', '},')
    
    for i in range(0, len(response)):
        if response[i] not in ['[', ']', '{', '}', ' ', '\n', ',', '\t']:
            response = '[{' + response[i:]
            break
    for i in range(len(response)-1, -1, -1):
        if response[i] not in ['[',']', '{', '}', ' ', '\n', ',', '\t']:
            response = response[:i+1] + '}]}]'
            break

    # Step 1: Try parsing as-is (already valid JSON)
    try:
        json.loads(response)
        return response
    except Exception:
        pass

    # Step 2: Remove markdown code blocks
    response = re.sub(r'^```(?:json)?\s*', '', response, flags=re.MULTILINE)
    response = re.sub(r'```\s*$', '', response, flags=re.MULTILINE)

    return response


def parse_subject_profiling(SP_response, retry_with_llm=True):
    # Save original response for Python dict parsing fallback
    original_response = SP_response
    
    b1 = SP_response.find("[")
    b2 = SP_response.find("{")
    b3 = SP_response.rfind("]")
    b4 = SP_response.rfind("}")
    if b1 != -1 and b2 != -1:
        if b1 < b2:
            SP_response = SP_response[b1:b3+1]
            original_response = original_response[b1:b3+1]
        else:
            SP_response = SP_response[b2:b4+1]
            original_response = original_response[b2:b4+1]
    
    cleaned_response = clean_json_response(SP_response)
    """
    Parse subject profiling response in either JSON or text format.

    JSON Format: [{"id": 0, "description": "...", "PIIs": [{"tag": "NAME", "keyword": "...", "certainty": 3, "reasoning": "..."}]}]
    Text Format: --- delimited sections with Subject ID, Tag, Guess, Certainty fields

    Args:
        SP_response: Response string to parse
        retry_with_llm: If True, retry parsing with LLM fix on first failure

    Returns:
        tuple: (status, result) where status is "success" or "error"
    """
    try:
        # Try JSON parsing first
        try:
            # Handle potential JSON array string
            try:
                parsed_json = json.loads(cleaned_response)
            except Exception as e:
                if "Extra data" in str(e):
                    if cleaned_response[0] != "[":
                        cleaned_response = "[" + cleaned_response + "]"
                    if cleaned_response[-1] != "]":
                        cleaned_response = cleaned_response + "]"
                parsed_json = json.loads(cleaned_response)
            subjects = []
            subject_info = {}
            if isinstance(parsed_json, list):
                for subject in parsed_json:
                    # Normalize ID: ensure integer
                    subject_id = subject.get("id", 0)
                    if isinstance(subject_id, str):
                        if subject_id.isdigit():
                            subject_id = int(subject_id)
                        else:
                            subject_id = 0
                    elif not isinstance(subject_id, int):
                        subject_id = 0
                    
                    subject_info["id"] = subject_id
                    subject_info["description"] = subject.get("description", "")
                    pii_data = subject.get("PIIs", [])
                    
                    # Ensure PIIs is a list (handle both list and dict formats)
                    if not isinstance(pii_data, list):
                        pii_data = []
                    
                    subjects.append({
                        "id": subject_info["id"],
                        "description": subject_info["description"],
                        "PIIs": pii_data
                    })
                return "success", subjects
            else:
                # Normalize ID: ensure integer
                subject_id = parsed_json.get("id", 0)
                if isinstance(subject_id, str):
                    if subject_id.isdigit():
                        subject_id = int(subject_id)
                    else:
                        subject_id = 0
                elif not isinstance(subject_id, int):
                    subject_id = 0
                
                subject_info["id"] = subject_id
                subject_info["description"] = parsed_json.get("description", "")
                pii_data = parsed_json.get("PIIs", [])
                
                # Ensure PIIs is a list (handle both list and dict formats)
                if not isinstance(pii_data, list):
                    pii_data = []
                
                subjects.append({
                    "id": subject_info["id"],
                    "description": subject_info["description"],
                    "PIIs": pii_data
                })
                return "success", subjects

        except (json.JSONDecodeError, ValueError) as e:
            # print(f"Error parsing JSON: {e}")
            
            # Try parsing as Python literal (handles single quotes)
            # Use original response before clean_json_response transformation
            try:
                # Check if original response looks like Python dict/list (has single quotes)
                if "'" in original_response:
                    # Try ast.literal_eval for Python dict/list format
                    parsed_python = ast.literal_eval(original_response)
                    
                    # Convert to proper format
                    if isinstance(parsed_python, list):
                        subjects = []
                        for subject in parsed_python:
                            if not isinstance(subject, dict):
                                continue
                            
                            # Normalize ID: ensure integer
                            subject_id = subject.get("id", 0)
                            if isinstance(subject_id, str):
                                if subject_id.isdigit():
                                    subject_id = int(subject_id)
                                else:
                                    subject_id = 0
                            elif not isinstance(subject_id, int):
                                subject_id = 0
                            
                            description = subject.get("description", "")
                            pii_data = subject.get("PIIs", [])
                            
                            # Ensure PIIs is a list
                            if not isinstance(pii_data, list):
                                pii_data = []
                            
                            subjects.append({
                                "id": subject_id,
                                "description": description,
                                "PIIs": pii_data
                            })
                        if subjects:
                            return "success", subjects
                    elif isinstance(parsed_python, dict):
                        # Single subject
                        # Normalize ID: ensure integer
                        subject_id = parsed_python.get("id", 0)
                        if isinstance(subject_id, str):
                            if subject_id.isdigit():
                                subject_id = int(subject_id)
                            else:
                                subject_id = 0
                        elif not isinstance(subject_id, int):
                            subject_id = 0
                        
                        description = parsed_python.get("description", "")
                        pii_data = parsed_python.get("PIIs", [])
                        
                        if not isinstance(pii_data, list):
                            pii_data = []
                        
                        return "success", [{
                            "id": subject_id,
                            "description": description,
                            "PIIs": pii_data
                        }]
            except (ValueError, SyntaxError) as ast_error:
                # ast.literal_eval also failed, continue to other methods
                pass
                
            # If JSON parsing fails and retry is enabled, try fixing with LLM
            if retry_with_llm:
                try:
                    from src.llm.client import fix_json_with_llm

                    error_msg = str(e)
                    status, fixed_response = fix_json_with_llm(SP_response, error_msg)

                    if status == "success":
                        # Try parsing the fixed response (without retry to avoid infinite loop)
                        return parse_subject_profiling(fixed_response, retry_with_llm=False)
                except Exception as llm_fix_error:
                    # If LLM fix fails, continue to text format parsing
                    pass

            # If JSON parsing fails, try text format parsing
            pass
        
        # Try alternative format: **Person 0:** or **0. Name**
        import re
        person_pattern = r'\*\*(?:Person\s+)?(\d+)[\.:]\s*([^\*]+)\*\*'
        matches = list(re.finditer(person_pattern, SP_response, re.IGNORECASE))
        
        if matches:
            subjects = []
            for match in matches:
                subject_id = int(match.group(1))
                start_pos = match.end()
                
                # Find next person header
                next_match_pos = None
                for next_match in matches:
                    if next_match.start() > start_pos:
                        next_match_pos = next_match.start()
                        break
                
                section_text = SP_response[start_pos:next_match_pos] if next_match_pos else SP_response[start_pos:]
                lines = section_text.strip().split('\n')
                description = ""
                pii_data = {}
                
                # Find description
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith('*') or line.startswith('Tag:'):
                        break
                    if 'Subject ID' in line or 'Person Description' in line:
                        description = line.split(':', 1)[1].strip() if ':' in line else line
                        break
                    if len(line) > 10 and not description:
                        description = line
                
                # Parse PII tags
                current_tag = None
                for line in lines:
                    line = line.strip()
                    
                    if line.startswith('Tag:') or (line.startswith('**') and line.endswith('**')):
                        if line.startswith('Tag:'):
                            current_tag = line.replace('Tag:', '').strip()
                        else:
                            current_tag = line.strip('*').strip()
                        
                        if current_tag:
                            pii_data[current_tag] = {"keyword": "", "certainty": 0, "hardness": 0}
                    
                    elif ('Guess:' in line or 'Certainty:' in line) and current_tag:
                        if 'Guess:' in line:
                            guess = line.split('Guess:', 1)[1].strip()
                            pii_data[current_tag]["keyword"] = guess
                        elif 'Certainty:' in line:
                            try:
                                cert_str = line.split('Certainty:', 1)[1].strip()
                                certainty = int(cert_str.split()[0])
                                pii_data[current_tag]["certainty"] = certainty
                                pii_data[current_tag]["hardness"] = 1 if certainty > 0 else 0
                                if certainty == 0:
                                    pii_data[current_tag]["keyword"] = ""
                            except:
                                pass
                
                if description:
                    subjects.append({
                        "id": subject_id,
                        "description": description,
                        "PIIs": pii_data
                    })
            
            if subjects:
                return "success", subjects
        
        # Text format parsing (original implementation)
        subjects = []
        sections = SP_response.split("---")

        for section in sections:
            section = section.strip()
            if not section:
                continue
            
            lines = [line.strip() for line in section.split("\n")]

            subject_info = {}
            pii_data = {}
            current_tag = None

            for line in lines:          
                try:
                    line = line.replace(", ...", '')
                    line = line.replace("\\\'s", "'s")
                    # line = clean_json_response(line)
                    response_json = json.loads(line)
                    if isinstance(response_json, list):
                        for subject in response_json:
                            subject_info["id"] = subject.get("id", 0)
                            subject_info["description"] = subject.get("description", "")
                            pii_data = subject.get("PIIs", {})
                            subjects.append({
                                "id": subject_info["id"],
                                "description": subject_info["description"],
                                "PIIs": pii_data
                            })
                        return "success", subjects
                    else:
                        subject_info["id"] = response_json.get("id", 0)
                        subject_info["description"] = response_json.get("description", "")
                        pii_data = response_json.get("PIIs", {})
                        subjects.append({
                            "id": subject_info["id"],
                            "description": subject_info["description"],
                            "PIIs": pii_data
                        })
                        return "success", subjects
                except Exception as e:
                    # print(f"Error parsing line: {e}")
                    pass
                if line.startswith("Subject ID:"):
                    id_part = line.replace("Subject ID:", "").strip()
                    try:
                        subject_info["id"] = int(id_part)
                    except:
                        subject_info["id"] = 0
                elif line.startswith("id"):
                    id_part = line.replace("id:", "").strip()
                    try:
                        subject_info["id"] = int(id_part)
                    except:
                        subject_info["id"] = 0
                            
                elif line.startswith("Person Description:"):
                    subject_info["description"] = line.replace("Person Description:", "").strip()

                elif line.startswith("Tag:"):
                    current_tag = line.replace("Tag:", "").strip()
                    pii_data[current_tag] = {"keyword": "", "certainty": 0, "hardness": 0}

                elif line.startswith("Guess:") and current_tag:
                    guess_text = line.replace("Guess:", "").strip()
                    pii_data[current_tag]["keyword"] = guess_text

                elif line.startswith("Certainty:") and current_tag:
                    try:
                        certainty = int(line.replace("Certainty:", "").strip())
                        pii_data[current_tag]["certainty"] = certainty
                        if certainty == 0:
                            pii_data[current_tag]["keyword"] = ""
                            pii_data[current_tag]["hardness"] = 0
                        else:
                            pii_data[current_tag]["hardness"] = 1
                    except:
                        pii_data[current_tag]["certainty"] = 0

            if subject_info.get("id") is not None and subject_info.get("description"):
                subjects.append({
                    "id": subject_info["id"],
                    "description": subject_info["description"],
                    "PIIs": pii_data
                })

        if not subjects:
            return "error", f"No subjects found in response. Response content: {SP_response}"

        return "success", subjects
        
    except Exception as e:
        return "error", f"Parsing error: {str(e)}"


def concat_parsing_result(SPC_parsing_result, SPNC_parsing_result):
    """Merge SPC and SPNC results"""
    try:
        # Normalize all IDs to integers to handle mixed type issues
        for subject in SPC_parsing_result:
            sid = subject.get('id')
            if isinstance(sid, str):
                if sid.isdigit():
                    subject['id'] = int(sid)
                else:
                    subject['id'] = 0
        for subject in SPNC_parsing_result:
            sid = subject.get('id')
            if isinstance(sid, str):
                if sid.isdigit():
                    subject['id'] = int(sid)
                else:
                    subject['id'] = 0
        
        required_tags = [
            "NAME", "IDENTIFICATION_NUMBER", "DRIVER_LICENSE_NUMBER",
            "PHONE_NUMBER", "PASSPORT_NUMBER", "EMAIL_ADDRESS", "SEX", "AGE",
            "LOCATION", "NATIONALITY", "EDUCATION", "RELATIONSHIP",
            "OCCUPATION", "AFFILIATION", "POSITION"
        ]

        # Helper function to compute similarity between descriptions
        def description_similarity(desc1, desc2):
            """Compute simple word overlap similarity between two descriptions"""
            if not desc1 or not desc2:
                return 0.0

            # Normalize and tokenize
            words1 = set(desc1.lower().split())
            words2 = set(desc2.lower().split())

            # Compute Jaccard similarity
            intersection = words1 & words2
            union = words1 | words2

            return len(intersection) / len(union) if union else 0.0

        spc_dict = {subj["id"]: subj for subj in SPC_parsing_result}
        spnc_dict = {subj["id"]: subj for subj in SPNC_parsing_result}

        spc_known_ids = set(spc_dict.keys())
        spnc_known_ids = set(spnc_dict.keys())

        # If IDs don't match, try to match by description similarity
        if spc_known_ids != spnc_known_ids:
            spc_only = spc_known_ids - spnc_known_ids
            spnc_only = spnc_known_ids - spc_known_ids

            # Try to match subjects by description similarity
            matched_pairs = []
            unmatched_spc = list(spc_only)
            unmatched_spnc = list(spnc_only)

            for spc_id in unmatched_spc[:]:
                best_match = None
                best_score = 0.5  # Minimum similarity threshold

                spc_desc = spc_dict[spc_id].get("description", "")

                for spnc_id in unmatched_spnc:
                    spnc_desc = spnc_dict[spnc_id].get("description", "")
                    score = description_similarity(spc_desc, spnc_desc)

                    if score > best_score:
                        best_score = score
                        best_match = spnc_id

                if best_match:
                    matched_pairs.append((spc_id, best_match))
                    unmatched_spc.remove(spc_id)
                    unmatched_spnc.remove(best_match)

            # Create a mapping for matched pairs
            id_mapping = {}
            for spc_id, spnc_id in matched_pairs:
                # Use SPC ID as canonical
                id_mapping[spnc_id] = spc_id

            # Apply mapping to SPNC dict
            new_spnc_dict = {}
            for spnc_id, spnc_subj in spnc_dict.items():
                if spnc_id in id_mapping:
                    new_spnc_dict[id_mapping[spnc_id]] = spnc_subj
                else:
                    new_spnc_dict[spnc_id] = spnc_subj
            spnc_dict = new_spnc_dict

            # If still mismatched after description matching, use more lenient approach
            # Simply merge all subjects from both sides
            spc_known_ids = set(spc_dict.keys())
            spnc_known_ids = set(spnc_dict.keys())

        # Helper function to extract PII from subject (handles both list and dict formats)
        def get_pii_by_tag(subject, tag, tag_index=None):
            """Extract PII data for a given tag, handling both list and dict formats
            
            Args:
                subject: Subject dictionary with PIIs
                tag: Tag name to search for
                tag_index: Optional index in required_tags list (for matching lists without tag field)
            """
            piis = subject.get("PIIs", {})
            
            # Handle empty PIIs
            if not piis:
                return {"keyword": "", "value": "", "certainty": 0, "hardness": 0}
            
            # Handle list format: [{"tag": "NAME", "keyword": "...", "certainty": 5}, ...]
            if isinstance(piis, list):
                # First, try to find by tag field
                for pii_item in piis:
                    if not isinstance(pii_item, dict):
                        continue
                    # Check if tag matches
                    pii_tag = pii_item.get("tag", "")
                    if pii_tag == tag:
                        # Handle both 'keyword' and 'value' fields
                        keyword = pii_item.get("keyword", "") or pii_item.get("value", "")
                        certainty = pii_item.get("certainty", 0)
                        hardness = pii_item.get("hardness", 0)
                        return {
                            "keyword": keyword,
                            "value": keyword,  # Keep for compatibility
                            "certainty": certainty,
                            "hardness": hardness
                        }
                
                # If tag not found and tag_index is provided, try positional matching
                # (for cases where tag field is missing but list is in required_tags order)
                if tag_index is not None and tag_index < len(piis):
                    pii_item = piis[tag_index]
                    if isinstance(pii_item, dict):
                        # Only use positional match if tag field is missing
                        if "tag" not in pii_item:
                            keyword = pii_item.get("keyword", "") or pii_item.get("value", "")
                            certainty = pii_item.get("certainty", 0)
                            hardness = pii_item.get("hardness", 0)
                            return {
                                "keyword": keyword,
                                "value": keyword,
                                "certainty": certainty,
                                "hardness": hardness
                            }
                
                # Tag not found in list
                return {"keyword": "", "value": "", "certainty": 0, "hardness": 0}
            
            # Handle dict format: {"NAME": {"keyword": "...", "certainty": 5}, ...}
            elif isinstance(piis, dict):
                pii_data = piis.get(tag, {})
                if isinstance(pii_data, dict):
                    keyword = pii_data.get("keyword", "") or pii_data.get("value", "")
                    certainty = pii_data.get("certainty", 0)
                    hardness = pii_data.get("hardness", 0)
                    return {
                        "keyword": keyword,
                        "value": keyword,  # Keep for compatibility
                        "certainty": certainty,
                        "hardness": hardness
                    }
                else:
                    return {"keyword": "", "value": "", "certainty": 0, "hardness": 0}
            
            # Unknown format
            return {"keyword": "", "value": "", "certainty": 0, "hardness": 0}

        merged_subjects = []
        all_subject_ids = set(spc_dict.keys()) | set(spnc_dict.keys())

        for subject_id in sorted(all_subject_ids):
            spc_subject = spc_dict.get(subject_id, {})
            spnc_subject = spnc_dict.get(subject_id, {})

            description = spnc_subject.get("description") or spc_subject.get("description", "")

            merged_piis = []
            for tag_index, tag in enumerate(required_tags):
                spc_pii = get_pii_by_tag(spc_subject, tag, tag_index)
                spnc_pii = get_pii_by_tag(spnc_subject, tag, tag_index)

                # Prefer SPNC over SPC (SPNC has more detailed information)
                if spnc_pii["certainty"] > 0:
                    keyword = (spnc_pii["keyword"] or spnc_pii["value"]).strip()
                    certainty = spnc_pii["certainty"]
                    hardness = spnc_pii["hardness"] if spnc_pii["hardness"] > 0 else 1
                elif spc_pii["certainty"] > 0:
                    keyword = (spc_pii["keyword"] or spc_pii["value"]).strip()
                    certainty = spc_pii["certainty"]
                    hardness = spc_pii["hardness"] if spc_pii["hardness"] > 0 else 1
                else:
                    keyword = ""
                    certainty = 0
                    hardness = 0

                # Normalize non-inferable keywords (e.g., "Not inferable", "Unknown", "None")
                keyword, certainty, hardness = normalize_non_inferable_keyword(keyword, certainty, hardness)

                merged_piis.append({
                    "tag": tag,
                    "keyword": keyword,
                    "certainty": certainty,
                    "hardness": hardness
                })

            merged_subjects.append({
                "id": subject_id,
                "description": description,
                "PIIs": merged_piis
            })

        # Re-index subjects sequentially starting from 0
        final_subjects = []
        for i, subject in enumerate(merged_subjects):
            final_subjects.append({
                "id": i,
                "description": subject["description"],
                "PIIs": subject["PIIs"]
            })

        return "success", final_subjects
    except Exception as e:
        return "error", f"Concat error: {str(e)}"


def create_spnc_only_result(SPNC_parsing_result):
    try:
        required_tags = [
            "NAME", "IDENTIFICATION_NUMBER", "DRIVER_LICENSE_NUMBER",
            "PHONE_NUMBER", "PASSPORT_NUMBER", "EMAIL_ADDRESS", "SEX", "AGE",
            "LOCATION", "NATIONALITY", "EDUCATION", "RELATIONSHIP",
            "OCCUPATION", "AFFILIATION", "POSITION"
        ]

        spc_tags = [
            "IDENTIFICATION_NUMBER", "DRIVER_LICENSE_NUMBER",
            "PHONE_NUMBER", "PASSPORT_NUMBER", "EMAIL_ADDRESS"
        ]

        # Helper function to extract PII from subject (handles both list and dict formats)
        def get_pii_by_tag(subject, tag, tag_index=None):
            """Extract PII data for a given tag, handling both list and dict formats
            
            Args:
                subject: Subject dictionary with PIIs
                tag: Tag name to search for
                tag_index: Optional index in required_tags list (for matching lists without tag field)
            """
            piis = subject.get("PIIs", {})
            
            # Handle empty PIIs
            if not piis:
                return {"keyword": "", "value": "", "certainty": 0, "hardness": 0}
            
            # Handle list format: [{"tag": "NAME", "keyword": "...", "certainty": 5}, ...]
            if isinstance(piis, list):
                # First, try to find by tag field
                for pii_item in piis:
                    if not isinstance(pii_item, dict):
                        continue
                    # Check if tag matches
                    pii_tag = pii_item.get("tag", "")
                    if pii_tag == tag:
                        # Handle both 'keyword' and 'value' fields
                        keyword = pii_item.get("keyword", "") or pii_item.get("value", "")
                        certainty = pii_item.get("certainty", 0)
                        hardness = pii_item.get("hardness", 0)
                        return {
                            "keyword": keyword,
                            "value": keyword,  # Keep for compatibility
                            "certainty": certainty,
                            "hardness": hardness
                        }
                
                # If tag not found and tag_index is provided, try positional matching
                # (for cases where tag field is missing but list is in required_tags order)
                if tag_index is not None and tag_index < len(piis):
                    pii_item = piis[tag_index]
                    if isinstance(pii_item, dict):
                        # Only use positional match if tag field is missing
                        if "tag" not in pii_item:
                            keyword = pii_item.get("keyword", "") or pii_item.get("value", "")
                            certainty = pii_item.get("certainty", 0)
                            hardness = pii_item.get("hardness", 0)
                            return {
                                "keyword": keyword,
                                "value": keyword,
                                "certainty": certainty,
                                "hardness": hardness
                            }
                
                # Tag not found in list
                return {"keyword": "", "value": "", "certainty": 0, "hardness": 0}
            
            # Handle dict format: {"NAME": {"keyword": "...", "certainty": 5}, ...}
            elif isinstance(piis, dict):
                pii_data = piis.get(tag, {})
                if isinstance(pii_data, dict):
                    keyword = pii_data.get("keyword", "") or pii_data.get("value", "")
                    certainty = pii_data.get("certainty", 0)
                    hardness = pii_data.get("hardness", 0)
                    return {
                        "keyword": keyword,
                        "value": keyword,  # Keep for compatibility
                        "certainty": certainty,
                        "hardness": hardness
                    }
                else:
                    return {"keyword": "", "value": "", "certainty": 0, "hardness": 0}
            
            # Unknown format
            return {"keyword": "", "value": "", "certainty": 0, "hardness": 0}

        final_subjects = []

        for i, spnc_subject in enumerate(SPNC_parsing_result):
            assigned_id = i

            merged_piis = []
            for tag_index, tag in enumerate(required_tags):
                spnc_pii = get_pii_by_tag(spnc_subject, tag, tag_index)

                if spnc_pii["certainty"] > 0:
                    keyword = (spnc_pii["keyword"] or spnc_pii["value"]).strip()
                    certainty = spnc_pii["certainty"]
                    hardness = spnc_pii["hardness"] if spnc_pii["hardness"] > 0 else 1
                elif tag in spc_tags:
                    keyword = ""
                    certainty = 0
                    hardness = 0
                else:
                    keyword = ""
                    certainty = 0
                    hardness = 0

                # Normalize non-inferable keywords (e.g., "Not inferable", "Unknown", "None")
                keyword, certainty, hardness = normalize_non_inferable_keyword(keyword, certainty, hardness)

                merged_piis.append({
                    "tag": tag,
                    "keyword": keyword,
                    "certainty": certainty,
                    "hardness": hardness
                })

            final_subjects.append({
                "id": assigned_id,
                "description": spnc_subject["description"],
                "PIIs": merged_piis
            })

        return "success", final_subjects
    except Exception as e:
        return "error", f"create SPNC-only result error: {str(e)}"
