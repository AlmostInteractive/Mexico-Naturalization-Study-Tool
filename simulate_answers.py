#!/usr/bin/env python3
"""
Tool to simulate answering questions correctly.
This script simulates answering the first 213 questions correctly four times each.
"""

import sqlite3
from weight_calculator import calculate_weight, get_rolling_success_rate


def get_db_connection():
    """Get a database connection."""
    conn = sqlite3.connect('quiz.db')
    conn.row_factory = sqlite3.Row
    return conn


def simulate_correct_answers(num_questions=213, num_attempts=4):
    """
    Simulate answering questions correctly multiple times.

    Args:
        num_questions: Number of questions to answer (default: 213)
        num_attempts: Number of correct attempts per question (default: 4)
    """
    print("=" * 60)
    print("Mexico Study Guide - Answer Simulation Tool")
    print("=" * 60)
    print(f"Simulating {num_attempts} correct answers for the first {num_questions} questions")
    print("=" * 60)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Get the first N questions
        cursor.execute('''
            SELECT id, question_text FROM questions
            ORDER BY id
            LIMIT ?
        ''', (num_questions,))

        questions = cursor.fetchall()

        if not questions:
            print("ERROR: No questions found in database")
            return False

        actual_count = len(questions)
        if actual_count < num_questions:
            print(f"WARNING: Only {actual_count} questions found in database")
            print(f"Proceeding with {actual_count} questions")

        print(f"\nProcessing {actual_count} questions...")

        for idx, question in enumerate(questions, 1):
            question_id = question['id']

            # Insert N correct attempts for this question
            for attempt_num in range(num_attempts):
                cursor.execute('''
                    INSERT INTO question_attempts (question_id, is_correct)
                    VALUES (?, 1)
                ''', (question_id,))

            # Calculate the rolling success rate using the shared library
            rolling_success_rate, attempts_count = get_rolling_success_rate(question_id, cursor)

            # Calculate weight using the shared library
            weight = calculate_weight(question_id, num_attempts, num_attempts, cursor)

            # Update question_stats
            cursor.execute('''
                UPDATE question_stats
                SET times_answered = ?,
                    times_correct = ?,
                    success_rate = ?,
                    weight = ?
                WHERE question_id = ?
            ''', (num_attempts, num_attempts, 1.0, weight, question_id))

            # Progress indicator every 10 questions
            if idx % 10 == 0:
                print(f"  Processed {idx}/{actual_count} questions...")

        conn.commit()

        print(f"\n{'=' * 60}")
        print(f"SUCCESS: Simulated {num_attempts} correct answers for {actual_count} questions")
        print(f"{'=' * 60}")

        # Show summary statistics
        cursor.execute('''
            SELECT
                COUNT(*) as total_questions,
                SUM(times_answered) as total_attempts,
                AVG(success_rate) as avg_success_rate,
                AVG(weight) as avg_weight
            FROM question_stats
            WHERE times_answered > 0
        ''')

        stats = cursor.fetchone()

        print(f"\nDatabase Statistics:")
        print(f"  Questions answered: {stats['total_questions']}")
        print(f"  Total attempts recorded: {stats['total_attempts']}")
        print(f"  Average success rate: {stats['avg_success_rate']:.1%}")
        print(f"  Average weight: {stats['avg_weight']:.2f}")

        return True

    except Exception as e:
        print(f"\nERROR: {e}")
        conn.rollback()
        return False

    finally:
        conn.close()


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Simulate correct answers for quiz questions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python simulate_answers.py                    # Answer first 213 questions 4 times each
  python simulate_answers.py --questions 100    # Answer first 100 questions 4 times each
  python simulate_answers.py --attempts 10      # Answer first 213 questions 10 times each
  python simulate_answers.py -q 50 -a 5         # Answer first 50 questions 5 times each

This tool will:
  1. Insert correct attempt records into question_attempts table
  2. Update question_stats with the new statistics
  3. Calculate appropriate weights using the rolling window algorithm
        """
    )

    parser.add_argument('-q', '--questions', type=int, default=213,
                       help='Number of questions to answer (default: 213)')
    parser.add_argument('-a', '--attempts', type=int, default=4,
                       help='Number of correct attempts per question (default: 4)')

    args = parser.parse_args()

    # Validate arguments
    if args.questions < 1:
        print("ERROR: Number of questions must be at least 1")
        return 1

    if args.attempts < 1:
        print("ERROR: Number of attempts must be at least 1")
        return 1

    success = simulate_correct_answers(args.questions, args.attempts)

    if success:
        print("\nSimulation completed successfully!")
        print("You can now run 'python app.py' to start the quiz with the simulated progress.")
        return 0
    else:
        print("\nSimulation failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
