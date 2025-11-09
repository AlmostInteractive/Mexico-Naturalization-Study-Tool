import csv
import sys
import json
import time
import os
from typing import List, Optional
import requests
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


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

    def generate_distractors_batch(self, questions_batch: List[tuple], subject: str = "Mexican history and culture") -> List[List[str]]:
        """
        Generate distractors for multiple questions using local LLM.

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

        # Build batch prompt
        batch_text = ""
        for i, (question, correct_answer) in enumerate(questions_batch, 1):
            batch_text += f"\nQuestion {i}: {question}\nCorrect Answer {i}: {correct_answer}\n"

        prompt = f"""Create 8 wrong answers for this {subject} question.

{batch_text.strip()}

Requirements:
1. Each wrong answer must be plausible but incorrect, distinct from the correct answer
2. Match the FORMAT of the correct answer (if it's a year, give years; if it's a name, give names)
3. Use proper Mexican Spanish names and places when appropriate
4. Make them diverse from each other
5. Never use placeholder text like "Option 1" or "Opcion 1"

Return ONLY valid JSON in this exact format:
{{
  "1": ["wrong answer 1", "wrong answer 2", "wrong answer 3", "wrong answer 4", "wrong answer 5", "wrong answer 6", "wrong answer 7", "wrong answer 8"]
}}"""

        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.7,
                "top_p": 0.9,
                "num_predict": 2000
            }
        }

        try:
            response = requests.post(self.generate_url, json=payload, timeout=120)
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

                # Try to extract and fix JSON from the response
                batch_distractors = self._extract_and_parse_json(content, len(questions_batch))

                if not batch_distractors:
                    print(f"WARNING: Could not parse JSON from response")
                    print(f"Response content: {content[:300]}")
                    return [self._fallback_distractors() for _ in questions_batch]

                if isinstance(batch_distractors, dict):
                    results = []
                    for i in range(1, len(questions_batch) + 1):
                        if str(i) in batch_distractors:
                            distractors = batch_distractors[str(i)]
                            if isinstance(distractors, list) and len(distractors) >= 8:
                                results.append([str(d).strip() for d in distractors[:8]])
                            else:
                                print(f"WARNING: Question {i} got {len(distractors)} distractors instead of 8")
                                # Pad with fallback
                                while len(distractors) < 8:
                                    distractors.append(f"Opcion {len(distractors) + 1}")
                                results.append([str(d).strip() for d in distractors[:8]])
                        else:
                            print(f"WARNING: Question {i} missing from batch response")
                            results.append(self._fallback_distractors())
                    return results
                else:
                    print(f"WARNING: Batch response not in expected format")
                    return [self._fallback_distractors() for _ in questions_batch]

            except json.JSONDecodeError as e:
                print(f"WARNING: Could not parse local LLM response as JSON: {e}")
                print(f"Response was: {content[:200]}...")
                return [self._fallback_distractors() for _ in questions_batch]

        except requests.exceptions.RequestException as e:
            print(f"WARNING: Local LLM request failed: {e}")
            return [self._fallback_distractors() for _ in questions_batch]
        except Exception as e:
            print(f"WARNING: Unexpected error in local LLM generation: {e}")
            return [self._fallback_distractors() for _ in questions_batch]

    def generate_distractors_batch_with_retry(self, questions_batch: List[tuple], subject: str = "Mexican history and culture") -> List[List[str]]:
        """
        Generate distractors for multiple questions with one retry attempt.

        Args:
            questions_batch: List of (question, correct_answer) tuples
            subject: Subject matter for context

        Returns:
            List of lists, each containing 8 distractor answers
        """

        # First attempt
        print("Attempt 1...")
        batch_distractors = self.generate_distractors_batch(questions_batch, subject)

        # Check if any questions failed (have fallback distractors)
        failed_indices = []
        for i, distractors in enumerate(batch_distractors):
            if "Opcion" in str(distractors):
                failed_indices.append(i)

        # If some questions failed, retry them
        if failed_indices:
            print(f"Retrying {len(failed_indices)} failed questions...")
            failed_questions = [questions_batch[i] for i in failed_indices]

            print("Attempt 2...")
            retry_distractors = self.generate_distractors_batch(failed_questions, subject)

            # Replace failed results with retry results
            for i, retry_index in enumerate(failed_indices):
                if i < len(retry_distractors) and "Opcion" not in str(retry_distractors[i]):
                    batch_distractors[retry_index] = retry_distractors[i]
                    print(f"  RETRY SUCCESS: Question {retry_index + 1}")
                else:
                    print(f"  RETRY FAILED: Question {retry_index + 1} - keeping fallback")

        return batch_distractors

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

                # Generate distractors for the entire batch (with retry)
                # Extract just question and answer for distractor generation
                batch_qa = [(item[0], item[1]) for item in batch]
                print(f"\nSending to local LLM ({model})... (this may take 30-60 seconds)")
                batch_distractors = generator.generate_distractors_batch_with_retry(batch_qa, subject)

                # Write results
                for j, (item, distractors) in enumerate(zip(batch, batch_distractors)):
                    question = item[0]
                    correct_answer = item[1]
                    notes = item[2] if len(item) >= 3 else None

                    # Check if we used LLM or fallback
                    if "Opcion" not in str(distractors):
                        llm_successes += 1
                        print(f"  SUCCESS: Question {i + j + 1} - Local LLM-generated distractors")
                    else:
                        fallback_count += 1
                        print(f"  WARNING: Question {i + j + 1} - Used fallback distractors")

                    # Write the row (include notes if present)
                    row = [question, correct_answer] + distractors
                    if has_notes_column:
                        row.append(notes if notes else "")
                    writer.writerow(row)
                    questions_processed += 1

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