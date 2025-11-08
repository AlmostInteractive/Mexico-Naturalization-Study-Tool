import sqlite3
import csv
import sys
import os
import re


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


def initialize_database():
    """Initialize the database with required tables if they don't exist."""
    conn = sqlite3.connect('quiz.db')
    cursor = conn.cursor()

    # Create questions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            chunk_number INTEGER NOT NULL,
            distractor1 TEXT,
            distractor2 TEXT,
            distractor3 TEXT,
            distractor4 TEXT,
            distractor5 TEXT,
            distractor6 TEXT,
            distractor7 TEXT,
            distractor8 TEXT
        )
    ''')

    # Create question_stats table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS question_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            times_answered INTEGER DEFAULT 0,
            times_correct INTEGER DEFAULT 0,
            success_rate REAL DEFAULT 0.0,
            weight REAL DEFAULT 25.0,
            FOREIGN KEY (question_id) REFERENCES questions (id)
        )
    ''')

    # Create user_progress table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            max_unlocked_chunk INTEGER DEFAULT 1,
            questions_in_current_set INTEGER DEFAULT 10
        )
    ''')

    # Create question_attempts table for rolling window calculation
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS question_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER NOT NULL,
            is_correct BOOLEAN NOT NULL,
            attempt_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (question_id) REFERENCES questions (id)
        )
    ''')

    conn.commit()
    conn.close()


def get_next_chunk_number():
    """Get the next available chunk number."""
    conn = sqlite3.connect('quiz.db')
    cursor = conn.cursor()

    cursor.execute('SELECT MAX(chunk_number) FROM questions')
    result = cursor.fetchone()
    max_chunk = result[0] if result[0] else 0

    conn.close()
    return max_chunk + 1


def import_distractors_csv(csv_file: str):
    """
    Import a distractors CSV file into the database.

    Args:
        csv_file: Path to distractors CSV (Question,Correct_Answer,Distractor1,...,Distractor8)
    """

    print("Database Import Tool")
    print("=" * 50)
    print(f"Input: {csv_file}")
    print(f"Database: quiz.db")
    print("=" * 50)

    # Check if file exists
    if not os.path.exists(csv_file):
        print(f"ERROR: Input file '{csv_file}' not found")
        return False

    # Initialize database
    print("Initializing database...")
    initialize_database()

    conn = sqlite3.connect('quiz.db')
    cursor = conn.cursor()

    # Get starting chunk number
    starting_chunk = get_next_chunk_number()
    print(f"Starting import at chunk {starting_chunk}")

    questions_imported = 0
    current_chunk = starting_chunk

    try:
        with open(csv_file, 'r', encoding='utf-8') as file:
            reader = csv.reader(file)

            # Check header
            header = next(reader, None)
            if not header or len(header) < 10:
                print("ERROR: CSV must have 10 columns (Question, Correct_Answer, 8 Distractors)")
                print(f"Found {len(header) if header else 0} columns")
                conn.close()
                return False

            print("Importing questions...")
            punctuation_corrections = 0
            date_corrections = 0
            duplicate_distractors_found = 0
            invalid_distractors_found = 0
            similar_distractors_found = 0

            for row in reader:
                if len(row) >= 10:
                    question_text = row[0].strip()
                    correct_answer = row[1].strip()
                    distractors = [row[i].strip() for i in range(2, 10)]

                    if question_text and correct_answer:
                        # Filter out duplicate distractors first
                        distractors, duplicates_count = filter_duplicate_distractors(correct_answer, distractors)
                        if duplicates_count > 0:
                            duplicate_distractors_found += duplicates_count
                            print(f"Question: {question_text[:50]}...")
                            print(f"  Removed {duplicates_count} duplicate distractor(s) for answer: '{correct_answer}'")

                        # Validate distractor quality
                        valid_distractors = []
                        invalid_count = 0
                        for i, distractor in enumerate(distractors):
                            is_valid, reason = validate_distractor_quality(correct_answer, distractor)
                            if is_valid:
                                valid_distractors.append(distractor)
                            else:
                                valid_distractors.append("")  # Replace invalid with empty
                                invalid_count += 1
                                if invalid_count == 1:  # Print question header only once
                                    print(f"Question: {question_text[:50]}...")
                                print(f"  Removed invalid distractor #{i+1}: '{distractor}' ({reason})")

                        if invalid_count > 0:
                            invalid_distractors_found += invalid_count
                        distractors = valid_distractors

                        # Check for near-duplicate distractors
                        distractors, similar_count = check_distractor_similarity(distractors)
                        if similar_count > 0:
                            similar_distractors_found += similar_count
                            print(f"Question: {question_text[:50]}...")
                            print(f"  Removed {similar_count} similar distractor(s)")

                        # Normalize date formats for consistency
                        correct_answer, distractors, date_was_corrected = normalize_dates_in_answers(correct_answer, distractors)
                        if date_was_corrected:
                            date_corrections += 1

                        # Normalize punctuation for consistency
                        correct_answer, distractors, punct_was_corrected = normalize_punctuation(correct_answer, distractors)
                        if punct_was_corrected:
                            punctuation_corrections += 1
                        # Calculate chunk (10 questions per chunk)
                        chunk_number = starting_chunk + (questions_imported // 10)

                        # Insert question
                        cursor.execute('''
                            INSERT INTO questions (
                                question_text, correct_answer, chunk_number,
                                distractor1, distractor2, distractor3, distractor4,
                                distractor5, distractor6, distractor7, distractor8
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', [question_text, correct_answer, chunk_number] + distractors)

                        # Get the question ID
                        question_id = cursor.lastrowid

                        # Initialize stats
                        cursor.execute('''
                            INSERT INTO question_stats (
                                question_id, times_answered, times_correct, success_rate, weight
                            ) VALUES (?, 0, 0, 0.0, 25.0)
                        ''', (question_id,))

                        questions_imported += 1

                        if questions_imported % 10 == 0:
                            print(f"Imported {questions_imported} questions (up to chunk {chunk_number})")

        # Initialize or update user progress
        cursor.execute('SELECT COUNT(*) FROM user_progress')
        user_progress_exists = cursor.fetchone()[0] > 0

        if not user_progress_exists:
            print("Initializing user progress...")
            cursor.execute('''
                INSERT INTO user_progress (max_unlocked_chunk, questions_in_current_set)
                VALUES (1, 10)
            ''')
        else:
            # Get current user progress
            cursor.execute('SELECT max_unlocked_chunk, questions_in_current_set FROM user_progress WHERE id = 1')
            result = cursor.fetchone()
            if result:
                current_max_chunk, current_set_size = result
                print(f"User progress: Currently on chunk {current_max_chunk} with {current_set_size} questions")

        conn.commit()

        print(f"\nImport complete!")
        print(f"SUCCESS: {questions_imported} questions imported")
        print(f"Chunks: {starting_chunk} to {starting_chunk + (questions_imported - 1) // 10}")
        print(f"Database: Questions initialized with default statistics")

        # Quality control summary
        if duplicate_distractors_found > 0:
            print(f"Duplicates: {duplicate_distractors_found} duplicate distractors removed")
        if invalid_distractors_found > 0:
            print(f"Quality: {invalid_distractors_found} low-quality distractors removed")
        if similar_distractors_found > 0:
            print(f"Similarity: {similar_distractors_found} similar distractors removed")
        if date_corrections > 0:
            print(f"Dates: {date_corrections} answers normalized (removed 'En ' prefixes)")
        if punctuation_corrections > 0:
            print(f"Punctuation: {punctuation_corrections} answers normalized for consistency")

        # Show chunk breakdown
        if questions_imported > 0:
            total_chunks = (questions_imported - 1) // 10 + 1
            print(f"\nChunk breakdown:")
            for i in range(total_chunks):
                chunk_num = starting_chunk + i
                questions_in_chunk = min(10, questions_imported - (i * 10))
                print(f"  Chunk {chunk_num}: {questions_in_chunk} questions")

        return True

    except Exception as e:
        print(f"ERROR importing questions: {e}")
        conn.rollback()
        return False

    finally:
        conn.close()


def show_database_status():
    """Show current database status."""
    if not os.path.exists('quiz.db'):
        print("Database: quiz.db does not exist")
        return

    conn = sqlite3.connect('quiz.db')
    cursor = conn.cursor()

    try:
        # Count questions
        cursor.execute('SELECT COUNT(*) FROM questions')
        total_questions = cursor.fetchone()[0]

        # Count chunks
        cursor.execute('SELECT MAX(chunk_number) FROM questions')
        max_chunk = cursor.fetchone()[0] or 0

        # Get user progress
        cursor.execute('SELECT max_unlocked_chunk, questions_in_current_set FROM user_progress WHERE id = 1')
        progress = cursor.fetchone()

        print(f"\nDatabase Status:")
        print(f"  Total questions: {total_questions}")
        print(f"  Total chunks: {max_chunk}")
        if progress:
            print(f"  User progress: Chunk {progress[0]} ({progress[1]} questions active)")
        else:
            print(f"  User progress: Not initialized")

    except Exception as e:
        print(f"ERROR reading database: {e}")
    finally:
        conn.close()


def main():
    if len(sys.argv) < 2:
        print("Database Import Tool")
        print("=" * 50)
        print("Usage: python import_distractors.py distractors.csv [options]")
        print("")
        print("Required:")
        print("  distractors.csv   CSV file with distractors (created by create_distractors.py)")
        print("")
        print("Options:")
        print("  --status          Show current database status")
        print("")
        print("Examples:")
        print("  python import_distractors.py questions_distractors.csv")
        print("  python import_distractors.py --status")
        print("")
        print("CSV Format Expected:")
        print("  Question,Correct_Answer,Distractor1,Distractor2,...,Distractor8")
        print("")
        print("This tool will:")
        print("  1. Initialize database tables if needed")
        print("  2. Import questions with distractors")
        print("  3. Set up chunking (10 questions per chunk)")
        print("  4. Initialize statistics for adaptive learning")
        sys.exit(1)

    # Handle status option
    if sys.argv[1] == "--status":
        show_database_status()
        sys.exit(0)

    csv_file = sys.argv[1]

    # Show current status first
    show_database_status()

    # Import the file
    success = import_distractors_csv(csv_file)

    if success:
        print("\nImport completed successfully!")
        print("Next steps:")
        print("  - Run 'python app.py' to start the quiz")
        print("  - Questions will appear in chunks as you progress")
        show_database_status()
    else:
        print("\nImport failed. Please check the errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()