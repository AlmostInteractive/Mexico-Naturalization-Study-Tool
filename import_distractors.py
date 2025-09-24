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
            weight REAL DEFAULT 10.0,
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

            for row in reader:
                if len(row) >= 10:
                    question_text = row[0].strip()
                    correct_answer = row[1].strip()
                    distractors = [row[i].strip() for i in range(2, 10)]

                    if question_text and correct_answer:
                        # Normalize punctuation for consistency
                        correct_answer, distractors, was_corrected = normalize_punctuation(correct_answer, distractors)
                        if was_corrected:
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
                            ) VALUES (?, 0, 0, 0.0, 10.0)
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