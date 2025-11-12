import csv
import sys
import json
import time
import os
import re
from typing import List, Optional, Tuple
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# ========== VALIDATION FUNCTIONS ==========

def has_trailing_punctuation(text: str) -> bool:
    """Check if text ends with punctuation."""
    return bool(re.search(r'[.!?;:]$', text.strip()))


def remove_trailing_punctuation(text: str) -> str:
    """Remove trailing punctuation from text."""
    return re.sub(r'[.!?;:]+$', '', text.strip())


def normalize_date_format(text: str) -> str:
    """
    Normalize date formats by removing Spanish date prefixes like 'En ' ONLY when followed by years.

    Examples:
        "En 1921" -> "1921"
        "En el año 1810" -> "1810"
        "En la ciudad de Querétaro" -> "En la ciudad de Querétaro" (unchanged)
        "1952" -> "1952" (unchanged)
    """
    # Remove "En el año " prefix only when followed by a 4-digit year (case insensitive, handles ñ encoding issues)
    text = re.sub(r'^En\s+el\s+a[ñn]o\s+(\d{4})', r'\1', text, flags=re.IGNORECASE)

    # Remove "En " prefix only when followed by a 4-digit year (case insensitive)
    text = re.sub(r'^En\s+(\d{4})', r'\1', text, flags=re.IGNORECASE)

    return text.strip()


def normalize_dates_in_answers(correct_answer: str, distractors: list) -> tuple:
    """
    Normalize date formats in correct answer and distractors.

    Returns:
        tuple: (normalized_correct_answer, normalized_distractors, was_corrected)
    """
    original_correct = correct_answer
    normalized_correct = normalize_date_format(correct_answer)
    normalized_distractors = [normalize_date_format(d) for d in distractors]

    was_corrected = normalized_correct != original_correct

    return normalized_correct, normalized_distractors, was_corrected


def is_functionally_identical(answer1: str, answer2: str) -> bool:
    """
    Check if two answers are functionally identical (same meaning despite minor differences).

    This handles cases like:
    - "Benito Juarez" vs "Benito A. Juarez"
    - "Mexico City" vs "Ciudad de Mexico"
    - Minor punctuation/spacing differences
    """
    if not answer1 or not answer2:
        return False

    # Exact match
    if answer1.strip() == answer2.strip():
        return True

    # Normalize for comparison: remove extra spaces, punctuation, case differences
    def normalize_for_comparison(text):
        # Convert to lowercase
        text = text.lower().strip()
        # Remove common punctuation
        text = re.sub(r'[.,;:¿?¡!"\'\-\(\)]', '', text)
        # Replace multiple spaces with single space
        text = re.sub(r'\s+', ' ', text)
        # Remove common middle initials pattern (single letter followed by optional period)
        text = re.sub(r'\s+[a-z]\.?\s+', ' ', text)
        # Remove standalone middle initials at word boundaries
        text = re.sub(r'\b[a-z]\.?\b', '', text)
        # Clean up extra spaces again
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    norm1 = normalize_for_comparison(answer1)
    norm2 = normalize_for_comparison(answer2)

    # Check if they're identical after normalization
    if norm1 == norm2:
        return True

    # Check if one is contained within the other (handles cases like "Benito Juarez" in "Benito A. Juarez")
    if norm1 in norm2 or norm2 in norm1:
        # Make sure it's a substantial match, not just a short word
        shorter = norm1 if len(norm1) < len(norm2) else norm2
        if len(shorter) >= 8:  # Only consider substantial matches
            return True

    # Special check: split into words and see if one is a subset of the other
    # This handles "José María Morelos" vs "José M. Morelos"
    words1 = set(norm1.split())
    words2 = set(norm2.split())

    if len(words1) >= 2 and len(words2) >= 2:
        # Check if the longer set contains all words from the shorter set
        if words1.issubset(words2) or words2.issubset(words1):
            return True

    return False


def filter_duplicate_distractors(correct_answer: str, distractors: list) -> tuple:
    """
    Filter out distractors that are identical or functionally identical to the correct answer.

    Returns:
        tuple: (filtered_distractors, duplicates_found_count)
    """
    filtered_distractors = []
    duplicates_found = 0

    for distractor in distractors:
        if not distractor or not distractor.strip():
            filtered_distractors.append(distractor)  # Keep empty distractors
        elif is_functionally_identical(correct_answer, distractor):
            filtered_distractors.append("")  # Replace duplicate with empty string
            duplicates_found += 1
        else:
            filtered_distractors.append(distractor)

    return filtered_distractors, duplicates_found


def normalize_punctuation(correct_answer: str, distractors: list) -> tuple:
    """
    Normalize punctuation between correct answer and distractors.

    If correct answer has punctuation but distractors don't, remove punctuation
    from correct answer to maintain consistency.

    Returns:
        tuple: (normalized_correct_answer, normalized_distractors, was_corrected)
    """
    # Check if correct answer has punctuation but distractors don't
    correct_has_punct = has_trailing_punctuation(correct_answer)
    distractors_have_punct = any(has_trailing_punctuation(d) for d in distractors if d.strip())

    if correct_has_punct and not distractors_have_punct:
        # Remove punctuation from correct answer for consistency
        normalized_correct = remove_trailing_punctuation(correct_answer)
        return normalized_correct, distractors, True

    return correct_answer, distractors, False


def normalize_capitalization(correct_answer: str, distractors: list) -> tuple:
    """
    Normalize capitalization between correct answer and distractors.

    Ensures that distractors match the capitalization pattern of the correct answer.

    Returns:
        tuple: (normalized_distractors, was_corrected)
    """
    if not correct_answer or not correct_answer.strip():
        return distractors, False

    correct_starts_upper = correct_answer[0].isupper()
    normalized_distractors = []
    was_corrected = False

    for distractor in distractors:
        if not distractor or not distractor.strip():
            normalized_distractors.append(distractor)
            continue

        distractor_starts_upper = distractor[0].isupper()

        # If capitalization doesn't match, fix it
        if correct_starts_upper and not distractor_starts_upper:
            # Capitalize the distractor
            normalized_distractors.append(distractor[0].upper() + distractor[1:])
            was_corrected = True
        elif not correct_starts_upper and distractor_starts_upper:
            # Lowercase the distractor
            normalized_distractors.append(distractor[0].lower() + distractor[1:])
            was_corrected = True
        else:
            normalized_distractors.append(distractor)

    return normalized_distractors, was_corrected


def has_spanish_prefix(text: str) -> bool:
    """Check if text has a common Spanish geographic/descriptive prefix."""
    common_prefixes = [
        r'^El\s+estado\s+de\s+',
        r'^La\s+región\s+de\s+',
        r'^El\s+norte\s+de\s+',
        r'^El\s+sur\s+de\s+',
        r'^El\s+centro\s+de\s+',
        r'^El\s+este\s+de\s+',
        r'^El\s+oeste\s+de\s+',
        r'^La\s+península\s+de\s+',
        r'^La\s+ciudad\s+de\s+',
        r'^Ciudad\s+de\s+',
        r'^La\s+zona\s+de\s+',
        r'^El\s+municipio\s+de\s+',
        r'^El\s+territorio\s+de\s+',
        r'^La\s+provincia\s+de\s+',
    ]

    for pattern in common_prefixes:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def strip_spanish_prefix(text: str) -> str:
    """Remove common Spanish geographic/descriptive prefixes."""
    common_prefixes = [
        r'^El\s+estado\s+de\s+',
        r'^La\s+región\s+de\s+',
        r'^El\s+norte\s+de\s+',
        r'^El\s+sur\s+de\s+',
        r'^El\s+centro\s+de\s+',
        r'^El\s+este\s+de\s+',
        r'^El\s+oeste\s+de\s+',
        r'^La\s+península\s+de\s+',
        r'^La\s+ciudad\s+de\s+',
        r'^Ciudad\s+de\s+',
        r'^La\s+zona\s+de\s+',
        r'^El\s+municipio\s+de\s+',
        r'^El\s+territorio\s+de\s+',
        r'^La\s+provincia\s+de\s+',
    ]

    for pattern in common_prefixes:
        stripped = re.sub(pattern, '', text, flags=re.IGNORECASE)
        if stripped != text:
            return stripped

    return text


def normalize_format_prefixes(correct_answer: str, distractors: list) -> tuple:
    """
    Normalize format prefixes between correct answer and distractors.

    If the correct answer doesn't have a Spanish prefix (like "El estado de")
    but distractors do, strip the prefixes from distractors.

    Returns:
        tuple: (normalized_distractors, was_corrected)
    """
    if not correct_answer or not correct_answer.strip():
        return distractors, False

    # Check if correct answer has a prefix
    correct_has_prefix = has_spanish_prefix(correct_answer)

    # If correct answer has no prefix, strip prefixes from distractors
    if not correct_has_prefix:
        normalized_distractors = []
        was_corrected = False

        for distractor in distractors:
            if not distractor or not distractor.strip():
                normalized_distractors.append(distractor)
                continue

            if has_spanish_prefix(distractor):
                stripped = strip_spanish_prefix(distractor)
                normalized_distractors.append(stripped)
                was_corrected = True
            else:
                normalized_distractors.append(distractor)

        return normalized_distractors, was_corrected

    return distractors, False


def is_purely_numeric(text: str) -> bool:
    """Check if text is purely numeric (possibly with minimal formatting)."""
    # Remove common numeric separators
    cleaned = re.sub(r'[,\s]', '', text.strip())
    return cleaned.isdigit()


def is_year(text: str) -> bool:
    """Check if text appears to be a year."""
    text = text.strip()
    # Match 4-digit years (1000-2999)
    return bool(re.match(r'^[12]\d{3}$', text))


def validate_distractor_quality(correct_answer: str, distractor: str) -> tuple:
    """
    Validate a distractor's quality.

    Returns:
        tuple: (is_valid, reason_if_invalid)
    """
    if not distractor or not distractor.strip():
        return True, ""  # Empty is OK, will be filtered later

    distractor = distractor.strip()

    # 1. Reject overly short answers (unless correct answer is also short)
    if len(distractor) <= 2 and len(correct_answer) > 3:
        return False, "Too short"

    # 2. Reject placeholder patterns
    placeholder_patterns = [
        r'^opci[oó]n\s*\d+$',  # "Opcion 1", "Opción 2"
        r'^option\s*\d+$',      # "Option 1"
        r'^distractor\s*\d+$',  # "Distractor 1"
        r'^wrong\s+answer',     # "Wrong answer"
        r'^respuesta\s+(no\s+)?disponible',  # "Respuesta no disponible"
    ]
    for pattern in placeholder_patterns:
        if re.search(pattern, distractor, re.IGNORECASE):
            return False, "Placeholder text"

    # 3. Type consistency - numeric vs text
    correct_is_numeric = is_purely_numeric(correct_answer)
    distractor_is_numeric = is_purely_numeric(distractor)

    if correct_is_numeric != distractor_is_numeric:
        # Exception: years are OK to mix with text dates
        if not (is_year(correct_answer) or is_year(distractor)):
            return False, "Type mismatch (numeric vs text)"

    # 4. Format matching for years
    if is_year(correct_answer) and not is_year(distractor):
        return False, "Format mismatch (year expected)"

    # 5. Reject single digit/character when correct answer is substantial
    if len(distractor) == 1 and len(correct_answer) > 3:
        return False, "Single character answer"

    # 6. Reject if contains suspicious artifacts
    suspicious_patterns = [
        r'```',           # Code block markers
        r'\[.*?\]',       # JSON-like brackets
        r'\{.*?\}',       # JSON braces
        r'^\d+[\.:]\s*',  # List numbering like "1. " or "1: "
    ]
    for pattern in suspicious_patterns:
        if re.search(pattern, distractor):
            return False, "Contains artifacts"

    return True, ""


def check_distractor_similarity(distractors: list) -> tuple:
    """
    Check for near-duplicate distractors.

    Returns:
        tuple: (filtered_distractors, duplicates_removed_count)
    """
    seen = []
    filtered = []
    duplicates_count = 0

    for distractor in distractors:
        if not distractor or not distractor.strip():
            filtered.append(distractor)
            continue

        # Check if too similar to any existing distractor
        is_duplicate = False
        for existing in seen:
            if is_functionally_identical(existing, distractor):
                is_duplicate = True
                break

        if is_duplicate:
            filtered.append("")  # Replace with empty
            duplicates_count += 1
        else:
            filtered.append(distractor)
            seen.append(distractor)

    return filtered, duplicates_count


def validate_and_clean_distractors(correct_answer: str, distractors: List[str]) -> Tuple[str, List[str], dict]:
    """
    Comprehensive validation and cleaning of distractors.

    Returns:
        tuple: (normalized_correct_answer, cleaned_distractors, stats_dict)
    """
    stats = {
        'duplicates_removed': 0,
        'invalid_removed': 0,
        'similar_removed': 0,
        'date_normalized': False,
        'punctuation_normalized': False,
        'capitalization_normalized': False,
        'format_prefixes_stripped': False
    }

    # Step 1: Filter duplicates (matching correct answer)
    distractors, dup_count = filter_duplicate_distractors(correct_answer, distractors)
    stats['duplicates_removed'] = dup_count

    # Step 2: Validate quality
    valid_distractors = []
    invalid_count = 0
    for distractor in distractors:
        is_valid, reason = validate_distractor_quality(correct_answer, distractor)
        if is_valid:
            valid_distractors.append(distractor)
        else:
            valid_distractors.append("")  # Replace invalid with empty
            invalid_count += 1
    stats['invalid_removed'] = invalid_count
    distractors = valid_distractors

    # Step 3: Check for near-duplicate distractors
    distractors, similar_count = check_distractor_similarity(distractors)
    stats['similar_removed'] = similar_count

    # Step 4: Normalize dates
    correct_answer, distractors, date_normalized = normalize_dates_in_answers(correct_answer, distractors)
    stats['date_normalized'] = date_normalized

    # Step 5: Normalize punctuation
    correct_answer, distractors, punct_normalized = normalize_punctuation(correct_answer, distractors)
    stats['punctuation_normalized'] = punct_normalized

    # Step 6: Normalize format prefixes (MUST come before capitalization)
    distractors, format_normalized = normalize_format_prefixes(correct_answer, distractors)
    stats['format_prefixes_stripped'] = format_normalized

    # Step 7: Normalize capitalization (MUST come after prefix stripping)
    distractors, cap_normalized = normalize_capitalization(correct_answer, distractors)
    stats['capitalization_normalized'] = cap_normalized

    return correct_answer, distractors, stats


# ========== END VALIDATION FUNCTIONS ==========


# ========== PROMPT GENERATION ==========

def create_distractor_prompt(question: str, correct_answer: str, subject: str = "Mexican history and culture") -> str:
    """
    Create a simple, flexible prompt for generating distractors.

    Args:
        question: The question text
        correct_answer: The correct answer
        subject: Subject matter context

    Returns:
        str: Prompt for the LLM
    """

    return f"""Create 8 plausible but INCORRECT answers for this {subject} question.

Question: {question}
Correct Answer: {correct_answer}

CRITICAL REQUIREMENTS:
1. Match the EXACT format, style, and length of the correct answer
   - If answer is "Veracruz", give similar names: "Oaxaca", "Puebla" (NOT "El estado de Oaxaca")
   - If answer is "1810", give years: "1821", "1857" (NOT "En 1821")
   - If answer is "Miguel Hidalgo", give names: "Benito Juárez" (NOT "El cura Hidalgo")

2. Each wrong answer must be:
   - Plausible but clearly incorrect
   - Distinct from each other
   - From the same domain (years with years, names with names, places with places)

3. Use proper Mexican Spanish when appropriate

4. NEVER use placeholder text like "Opción 1" or "Option 1"

Return ONLY valid JSON in this exact format:
{{"1": ["wrong 1", "wrong 2", "wrong 3", "wrong 4", "wrong 5", "wrong 6", "wrong 7", "wrong 8"]}}"""


# ========== END PROMPT GENERATION ==========


class LocalLLMDistractorGenerator:
    """Local LLM-powered distractor generation using Ollama or similar."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.2"):
        """
        Initialize the local LLM distractor generator.

        Args:
            base_url: URL of the local LLM server (Ollama default)
            model: Model name to use (e.g., llama3.2, mistral, codellama)
        """
        self.base_url = base_url
        self.model = model
        self.generate_url = f"{self.base_url}/api/generate"

    def test_connection(self) -> bool:
        """Test if the local LLM server is running."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except:
            return False

    def generate_distractors_single(self, question: str, correct_answer: str, subject: str = "Mexican history and culture") -> List[str]:
        """
        Generate distractors for a single question.

        Args:
            question: The question text
            correct_answer: The correct answer
            subject: Subject matter for context

        Returns:
            List of 8 distractor answers
        """

        if not self.test_connection():
            return self._fallback_distractors()

        # Get prompt
        prompt = create_distractor_prompt(question, correct_answer, subject)

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.8,  # Slightly higher for more creativity
                "top_p": 0.9,
                "num_predict": 800
            }
        }

        try:
            response = requests.post(self.generate_url, json=payload, timeout=60)
            response.raise_for_status()

            result = response.json()
            content = result.get('response', '').strip()

            # Parse JSON response
            try:
                # Remove any markdown code blocks if present
                if content.startswith('```json'):
                    content = content.replace('```json', '').replace('```', '').strip()
                elif content.startswith('```'):
                    content = content.replace('```', '').strip()

                # Try to extract and parse JSON
                parsed = self._extract_and_parse_json(content, 1)

                if parsed and "1" in parsed and isinstance(parsed["1"], list):
                    distractors = parsed["1"]
                    if len(distractors) >= 8:
                        return [str(d).strip() for d in distractors[:8]]
                    else:
                        # Pad with fallback if needed
                        while len(distractors) < 8:
                            distractors.append(f"Opcion {len(distractors) + 1}")
                        return [str(d).strip() for d in distractors[:8]]
                else:
                    print(f"WARNING: Could not parse distractors from response")
                    return self._fallback_distractors()

            except json.JSONDecodeError as e:
                print(f"WARNING: Could not parse JSON: {e}")
                return self._fallback_distractors()

        except requests.exceptions.RequestException as e:
            print(f"WARNING: Request failed: {e}")
            return self._fallback_distractors()
        except Exception as e:
            print(f"WARNING: Unexpected error: {e}")
            return self._fallback_distractors()

    def generate_distractors_batch(self, questions_batch: List[tuple], subject: str = "Mexican history and culture") -> List[List[str]]:
        """
        Generate distractors for multiple questions.

        Args:
            questions_batch: List of (question, correct_answer) tuples
            subject: Subject matter for context

        Returns:
            List of lists, each containing 8 distractor answers
        """

        if not self.test_connection():
            print(f"WARNING: Cannot connect to local LLM server at {self.base_url}")
            print("Make sure Ollama is installed and running:")
            print("  1. Install Ollama from https://ollama.ai/")
            print(f"  2. Run: ollama pull {self.model}")
            print("  3. Start Ollama server")
            return [self._fallback_distractors() for _ in questions_batch]

        results = []
        for i, (question, correct_answer) in enumerate(questions_batch):
            # Generate distractors
            distractors = self.generate_distractors_single(question, correct_answer, subject)
            results.append(distractors)

        return results

    def generate_distractors_batch_with_validation_and_retry(self, questions_batch: List[tuple], subject: str = "Mexican history and culture") -> List[dict]:
        """
        Generate distractors for multiple questions with validation and one retry attempt.

        Args:
            questions_batch: List of (question, correct_answer) tuples
            subject: Subject matter for context

        Returns:
            List of dicts with keys: 'question', 'correct_answer', 'distractors', 'validation_stats'
        """

        # First attempt
        print("\n=== PHASE 1: Initial Generation ===")
        batch_distractors = self.generate_distractors_batch(questions_batch, subject)

        # Validate all generated distractors
        results = []
        questions_to_retry = []
        retry_indices = []

        for i, (question_tuple, distractors) in enumerate(zip(questions_batch, batch_distractors)):
            question, correct_answer = question_tuple

            # Validate and clean distractors (may also normalize correct answer)
            normalized_correct_answer, cleaned_distractors, stats = validate_and_clean_distractors(correct_answer, distractors)

            # Count how many valid distractors we have (non-empty)
            valid_count = sum(1 for d in cleaned_distractors if d.strip())

            # If we have fewer than 5 valid distractors, mark for retry
            if valid_count < 5:
                questions_to_retry.append((question, correct_answer))
                retry_indices.append(i)
                print(f"  Question {i+1}: Only {valid_count}/8 valid distractors - marked for retry")
            else:
                print(f"  Question {i+1}: {valid_count}/8 valid distractors - OK")

            results.append({
                'question': question,
                'correct_answer': normalized_correct_answer,
                'distractors': cleaned_distractors,
                'validation_stats': stats,
                'valid_count': valid_count
            })

        # Retry failed questions
        if questions_to_retry:
            print(f"\n=== PHASE 2: Retry {len(questions_to_retry)} Questions ===")
            retry_distractors = self.generate_distractors_batch(questions_to_retry, subject)

            # Update results with retry attempts
            for i, retry_index in enumerate(retry_indices):
                question, correct_answer = questions_to_retry[i]
                new_distractors = retry_distractors[i] if i < len(retry_distractors) else self._fallback_distractors()

                # Validate and clean retry distractors (may also normalize correct answer)
                normalized_correct_answer, cleaned_distractors, stats = validate_and_clean_distractors(correct_answer, new_distractors)
                valid_count = sum(1 for d in cleaned_distractors if d.strip())

                # Only replace if retry gave us better results
                if valid_count > results[retry_index]['valid_count']:
                    results[retry_index]['correct_answer'] = normalized_correct_answer
                    results[retry_index]['distractors'] = cleaned_distractors
                    results[retry_index]['validation_stats'] = stats
                    results[retry_index]['valid_count'] = valid_count
                    print(f"  RETRY SUCCESS: Question {retry_index + 1} improved to {valid_count}/8 valid distractors")
                else:
                    print(f"  RETRY: Question {retry_index + 1} - no improvement, keeping original ({results[retry_index]['valid_count']}/8)")

        return results

    def _extract_and_parse_json(self, content: str, expected_questions: int) -> dict:
        """
        Robustly extract and parse JSON from LLM response.

        Args:
            content: Raw response content
            expected_questions: Number of questions expected

        Returns:
            Parsed batch distractors dict or None if parsing fails
        """

        # Method 1: Try to find complete JSON object
        try:
            obj_start = content.find('{')
            if obj_start != -1:
                # Find the matching closing brace
                brace_count = 0
                obj_end = obj_start

                for i, char in enumerate(content[obj_start:], obj_start):
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            obj_end = i + 1
                            break

                if obj_end > obj_start:
                    json_content = content[obj_start:obj_end]
                    response_data = json.loads(json_content)

                    # Convert to expected format
                    if isinstance(response_data, dict):
                        # Check if it's the expected batch format
                        if all(str(i) in response_data for i in range(1, expected_questions + 1)):
                            return response_data

                        # Check if it's a single question response with distractor1, distractor2, etc.
                        if all(isinstance(v, str) for v in response_data.values()):
                            distractors = [response_data.get(f"distractor{i+1}", f"Opcion {i+1}") for i in range(8)]
                            return {"1": distractors}

                        # Check if it has numeric keys that might be the batch format
                        if "1" in response_data and isinstance(response_data["1"], list):
                            return response_data
        except json.JSONDecodeError:
            pass
        except Exception:
            pass

        # Method 2: Try to find and fix array format
        try:
            array_start = content.find('[')
            array_end = content.rfind(']') + 1

            if array_start != -1 and array_end > array_start:
                json_content = content[array_start:array_end]
                response_data = json.loads(json_content)

                if isinstance(response_data, list) and len(response_data) >= 8:
                    return {"1": response_data[:8]}
        except json.JSONDecodeError:
            pass
        except Exception:
            pass

        # Method 3: Extract individual distractors from text
        try:
            distractors = []
            lines = content.split('\n')

            for line in lines:
                line = line.strip()
                # Look for quoted strings that might be distractors
                if '"' in line and line.count('"') >= 2:
                    start = line.find('"')
                    end = line.find('"', start + 1)
                    if start != -1 and end != -1:
                        distractor = line[start+1:end].strip()
                        if distractor and distractor not in distractors:
                            distractors.append(distractor)

                # Look for patterns like "Ciudad de X" or other Mexican place names
                elif any(word in line.lower() for word in ['ciudad', 'guadalajara', 'monterrey', 'puebla', 'león', 'oaxaca', 'veracruz']):
                    # Extract the location name
                    words = line.split()
                    for i, word in enumerate(words):
                        if word.lower() in ['ciudad', 'guadalajara', 'monterrey', 'puebla', 'león', 'oaxaca', 'veracruz']:
                            if word.lower() == 'ciudad' and i + 1 < len(words):
                                distractor = f"Ciudad de {words[i+1]}"
                            else:
                                distractor = word.title()

                            if distractor not in distractors:
                                distractors.append(distractor)
                            break

                if len(distractors) >= 8:
                    break

            # Pad with generic distractors if needed
            while len(distractors) < 8:
                distractors.append(f"Opcion {len(distractors) + 1}")

            if len(distractors) >= 8:
                return {"1": distractors[:8]}
        except Exception:
            pass

        return None

    def _fallback_distractors(self) -> List[str]:
        """Generate basic fallback distractors when local LLM fails."""
        return [f"Opcion {i+1}" for i in range(8)]


def create_distractors_with_local_llm(input_file: str, model: str = "llama3.2", subject: str = "Mexican history and culture", batch_size: int = 1, base_url: str = "http://localhost:11434"):
    """
    Create a distractors CSV file using local LLM with batch processing.

    Args:
        input_file: Path to input CSV (Question,Answer format)
        model: Local LLM model to use
        subject: Subject matter for context
        batch_size: Number of questions to process in each API call
        base_url: URL of the local LLM server

    Returns:
        Path to the created distractors CSV file
    """

    # Generate output filename
    base_name = os.path.splitext(input_file)[0]
    output_file = f"{base_name}_distractors.csv"

    print("Local LLM Distractor Generator")
    print("=" * 50)
    print(f"Input: {input_file}")
    print(f"Output: {output_file}")
    print(f"Model: {model}")
    print(f"Server: {base_url}")
    print(f"Subject: {subject}")
    print(f"Batch size: {batch_size} questions per request")
    print("=" * 50)

    generator = LocalLLMDistractorGenerator(base_url=base_url, model=model)

    # Test connection first
    if not generator.test_connection():
        print("\nERROR: Cannot connect to local LLM server")
        print("\nTo use local LLM distractor generation:")
        print("1. Install Ollama from https://ollama.ai/")
        print(f"2. Download a model: ollama pull {model}")
        print("3. Start Ollama (usually starts automatically)")
        print("4. Verify it's running: curl http://localhost:11434/api/tags")
        print("\nAlternatively, use the fallback generator:")
        print("  python create_distractors.py your_file.csv")
        return None

    questions_processed = 0
    llm_successes = 0
    fallback_count = 0
    batch_count = 0

    try:
        # First pass: read all questions
        all_questions = []
        has_notes_column = False
        with open(input_file, 'r', encoding='utf-8') as infile:
            reader = csv.reader(infile)

            # Skip header if present
            header = next(reader, None)
            if not header or len(header) < 2:
                print("ERROR: Input CSV must have at least 2 columns (Question, Answer)")
                return None

            # Check if header has notes column (3rd column)
            has_notes_column = len(header) >= 3
            if has_notes_column:
                print("Detected notes column in input CSV - will preserve in output")

            for row in reader:
                if len(row) >= 2:
                    question = row[0].strip()
                    correct_answer = row[1].strip()
                    notes = row[2].strip() if len(row) >= 3 else None
                    if question and correct_answer:
                        all_questions.append((question, correct_answer, notes))

        print(f"Found {len(all_questions)} questions to process")

        # Second pass: process in batches and write results
        with open(output_file, 'w', newline='', encoding='utf-8') as outfile:
            writer = csv.writer(outfile)

            # Write header (include notes column if present in input)
            header_row = [
                "Question", "Correct_Answer", "Distractor1", "Distractor2",
                "Distractor3", "Distractor4", "Distractor5", "Distractor6",
                "Distractor7", "Distractor8"
            ]
            if has_notes_column:
                header_row.append("Notes")
            writer.writerow(header_row)
            outfile.flush()  # Flush header immediately

            # Process questions in batches
            for i in range(0, len(all_questions), batch_size):
                batch = all_questions[i:i + batch_size]
                batch_count += 1

                print(f"\n{'='*60}")
                print(f"Processing questions {i + 1}-{min(i + batch_size, len(all_questions))} of {len(all_questions)}")
                print(f"Batch {batch_count} ({len(batch)} questions)")
                print(f"{'='*60}")
                for j, item in enumerate(batch):
                    q = item[0]
                    print(f"  {i + j + 1}. {q[:50]}...")

                # Generate distractors for the entire batch (with validation and retry)
                # Extract just question and answer for distractor generation
                batch_qa = [(item[0], item[1]) for item in batch]
                print(f"\nSending to local LLM ({model})... (this may take 30-60 seconds)")
                batch_results = generator.generate_distractors_batch_with_validation_and_retry(batch_qa, subject)

                # Write results and collect statistics
                for j, (item, result) in enumerate(zip(batch, batch_results)):
                    notes = item[2] if len(item) >= 3 else None
                    question = result['question']
                    correct_answer = result['correct_answer']
                    distractors = result['distractors']
                    valid_count = result['valid_count']

                    # Count successes vs fallbacks
                    if valid_count >= 5:
                        llm_successes += 1
                        print(f"  ✓ Question {i + j + 1}: {valid_count}/8 valid distractors")
                    else:
                        fallback_count += 1
                        print(f"  ⚠ Question {i + j + 1}: Only {valid_count}/8 valid distractors (some blanks)")

                    # Write the row (include notes if present)
                    row = [question, correct_answer] + distractors
                    if has_notes_column:
                        row.append(notes if notes else "")
                    writer.writerow(row)
                    questions_processed += 1

                # Flush after each batch to ensure data is written to disk
                outfile.flush()

                # Small delay between batches to not overwhelm local server
                if i + batch_size < len(all_questions):
                    print(f"Processed {questions_processed} questions so far. Pausing 1 second...")
                    time.sleep(1)

                # Progress update with percentage
                progress_percent = (questions_processed / len(all_questions)) * 100
                print(f"\nBatch {batch_count} complete!")
                print(f"Progress: {questions_processed}/{len(all_questions)} questions ({progress_percent:.1f}%)")

                if questions_processed < len(all_questions):
                    remaining = len(all_questions) - questions_processed
                    print(f"Remaining: {remaining} questions")

        print(f"\n{'='*60}")
        print(f"DISTRACTOR GENERATION COMPLETE!")
        print(f"{'='*60}")
        print(f"SUCCESS: {questions_processed} questions processed")
        print(f"LOCAL_LLM: {llm_successes} locally-generated distractors")
        print(f"FALLBACK: {fallback_count} fallback distractors")
        print(f"Distractors CSV saved as: {output_file}")

        if llm_successes > 0:
            print(f"Local LLM success rate: {llm_successes/questions_processed*100:.1f}%")

        return output_file

    except FileNotFoundError:
        print(f"ERROR: Could not find input file '{input_file}'")
        return None
    except Exception as e:
        print(f"ERROR processing CSV: {e}")
        return None


def main():
    if len(sys.argv) < 2:
        print("Local LLM Distractor Generator")
        print("=" * 50)
        print("Usage: python create_distractors.py input.csv [options]")
        print("")
        print("Required:")
        print("  input.csv     Input CSV file (Question,Answer[,Notes] format)")
        print("")
        print("Optional:")
        print("  --model MODEL       Local model name (default: llama3.2)")
        print("  --subject SUBJECT   Subject matter (default: Mexican history and culture)")
        print("  --batch-size N      Questions per request (default: 1, max: 3)")
        print("  --server URL        Local LLM server URL (default: http://localhost:11434)")
        print("")
        print("Examples:")
        print("  python create_distractors.py questions.csv")
        print("  python create_distractors.py questions.csv --model mistral:7b-instruct")
        print("  python create_distractors.py questions.csv --batch-size 2")
        print("")
        print("Input CSV format:")
        print("  Question,Answer        (basic format)")
        print("  Question,Answer,Notes  (with optional notes)")
        print("")
        print("Output:")
        print("  Creates 'input_distractors.csv' with 8 AI-generated distractors per question")
        print("  Preserves Notes column if present in input")
        print("")
        print("Process:")
        print("  1. Generate distractors using local LLM with format-matching prompts")
        print("  2. Validate distractors for:")
        print("     - Duplicates matching correct answer")
        print("     - Quality issues (too short, placeholders, artifacts)")
        print("     - Near-duplicates between distractors")
        print("     - Date format consistency")
        print("     - Punctuation consistency")
        print("     - Format prefix consistency (strips 'El estado de', etc.)")
        print("     - Capitalization consistency")
        print("  3. Retry any questions with insufficient valid distractors")
        print("  4. Write output with blank entries for distractors that remain invalid")
        print("")
        print("Setup (First time only):")
        print("  1. Install Ollama: https://ollama.ai/")
        print("  2. Download a model: ollama pull llama3.2")
        print("  3. Start Ollama (usually automatic)")
        print("")
        print("Available models (after installing Ollama):")
        print("  - llama3.2 (recommended, ~2GB)")
        print("  - mistral:7b-instruct (~4GB)")
        print("  - codellama (~4GB)")
        print("  - phi3 (~2GB)")
        print("")
        print("Benefits:")
        print("  - Completely FREE")
        print("  - Runs offline")
        print("  - No API keys needed")
        print("  - No rate limits")
        print("  - Privacy-friendly")
        sys.exit(1)

    input_file = sys.argv[1]

    # Parse optional arguments
    model = "llama3.2"
    subject = "Mexican history and culture"
    batch_size = 1
    base_url = "http://localhost:11434"

    for i in range(2, len(sys.argv)):
        if sys.argv[i] == "--model" and i + 1 < len(sys.argv):
            model = sys.argv[i + 1]
        elif sys.argv[i] == "--subject" and i + 1 < len(sys.argv):
            subject = sys.argv[i + 1]
        elif sys.argv[i] == "--batch-size" and i + 1 < len(sys.argv):
            try:
                batch_size = max(1, min(3, int(sys.argv[i + 1])))  # Clamp between 1-3
            except ValueError:
                print("WARNING: Invalid batch size, using default of 1")
                batch_size = 1
        elif sys.argv[i] == "--server" and i + 1 < len(sys.argv):
            base_url = sys.argv[i + 1]

    # Check if input file exists
    if not os.path.exists(input_file):
        print(f"ERROR: Input file '{input_file}' not found")
        sys.exit(1)

    # Create distractors CSV using local LLM
    output_file = create_distractors_with_local_llm(input_file, model, subject, batch_size, base_url)

    if output_file:
        print(f"\nSuccess! Created: {output_file}")
        print("Next step: Use 'python import_distractors.py' to import into database")
    else:
        print("\nFailed to create distractors CSV")
        print("Fallback option: python create_distractors.py (uses static distractors)")
        sys.exit(1)


if __name__ == "__main__":
    main()