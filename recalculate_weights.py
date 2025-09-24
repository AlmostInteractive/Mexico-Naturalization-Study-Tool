#!/usr/bin/env python3
"""
Recalculate all question weights using the current weighting algorithm.

This script updates all existing question weights in the database
using the latest weighting formula from app.py.
"""

import sqlite3


# Configuration constants (matching app.py)
MAX_SUCCESS_RATE_CAP = 0.98  # Maximum success rate used for weight calculation (98%)
CONFIDENCE_THRESHOLD = 3  # Number of attempts needed for full confidence in statistics
RECENT_ATTEMPTS_WINDOW = 5  # Only consider the last N attempts for success rate calculation


def get_rolling_success_rate(question_id, cursor, window_size=RECENT_ATTEMPTS_WINDOW):
    """Calculate success rate based on the last N attempts."""
    # Get the last N attempts for this question
    cursor.execute('''
        SELECT is_correct FROM question_attempts
        WHERE question_id = ?
        ORDER BY attempt_timestamp DESC
        LIMIT ?
    ''', (question_id, window_size))

    recent_attempts = cursor.fetchall()

    if not recent_attempts:
        return 0.0, 0

    recent_correct = sum(1 for attempt in recent_attempts if attempt['is_correct'])
    recent_total = len(recent_attempts)

    return recent_correct / recent_total, recent_total


def calculate_weight(question_id, times_answered, times_correct, cursor):
    """
    Calculate weight using the current rolling window algorithm from app.py.

    Args:
        question_id: ID of the question
        times_answered: Total number of times question was answered
        times_correct: Number of times question was answered correctly
        cursor: Database cursor for rolling rate lookup

    Returns:
        float: Calculated weight for the question
    """
    # Calculate success rate
    if times_answered == 0:
        return 25.0  # Much higher weight for unanswered questions
    elif times_answered < CONFIDENCE_THRESHOLD:
        # Questions with insufficient attempts get maximum weight (like 0% success rate)
        return 25.0  # Same as unseen questions - we need more data

    # Get rolling window success rate
    rolling_success_rate, recent_attempts_count = get_rolling_success_rate(question_id, cursor)

    # Use rolling success rate for weight calculation
    success_rate = rolling_success_rate

    # Build confidence based on recent attempts (rolling window)
    confidence = min(recent_attempts_count / CONFIDENCE_THRESHOLD, 1.0)

    # Cap success rate for weight calculation
    effective_success_rate = min(success_rate, MAX_SUCCESS_RATE_CAP)

    # Very aggressive exponential weighting: poor performance = much higher weight
    # Adjusted to make 100% success rate close to 1.0 baseline
    base_weight = 0.2 + 25.0 * (5.0 ** (1 - effective_success_rate) - 1.0)

    # Apply confidence multiplier: less confident = higher weight
    # Reduced multiplier to get 100% success closer to 1.0
    confidence_multiplier = 1.0 + (1 - confidence) * 2.5

    weight = base_weight * confidence_multiplier

    # Cap at reasonable maximum (increased for very aggressive separation)
    weight = min(weight, 50.0)

    return weight


def recalculate_all_weights():
    """Recalculate weights for all questions in the database."""

    # Connect to database
    try:
        conn = sqlite3.connect('quiz.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
    except sqlite3.Error as e:
        print(f"ERROR: Could not connect to database: {e}")
        return False

    try:
        # Get all question statistics
        cursor.execute('''
            SELECT qs.id, qs.question_id, qs.times_answered, qs.times_correct,
                   qs.success_rate, qs.weight, q.question_text
            FROM question_stats qs
            JOIN questions q ON qs.question_id = q.id
            ORDER BY qs.weight DESC
        ''')

        stats = cursor.fetchall()

        if not stats:
            print("No question statistics found in database.")
            conn.close()
            return False

        print("Weight Recalculation Tool")
        print("=" * 50)
        print(f"Found {len(stats)} questions to process")
        print()

        updates_made = 0
        significant_changes = 0

        for stat in stats:
            # Calculate new weight using rolling window
            new_weight = calculate_weight(stat['question_id'], stat['times_answered'], stat['times_correct'], cursor)
            old_weight = stat['weight']

            # Update if weight has changed
            if abs(new_weight - old_weight) > 0.01:  # Only update if change is significant
                cursor.execute('''
                    UPDATE question_stats
                    SET weight = ?
                    WHERE id = ?
                ''', (new_weight, stat['id']))

                updates_made += 1

                # Track significant changes (>25% difference)
                change_percent = abs(new_weight - old_weight) / old_weight * 100
                if change_percent > 25:
                    significant_changes += 1
                    print(f"Significant change: {stat['question_text'][:50]}...")
                    print(f"  Success Rate: {stat['success_rate']:.1%}")
                    print(f"  Weight: {old_weight:.2f} -> {new_weight:.2f} ({change_percent:+.1f}%)")
                    print()

        # Commit changes
        conn.commit()

        print("=" * 50)
        print("Recalculation Complete!")
        print(f"Questions processed: {len(stats)}")
        print(f"Weights updated: {updates_made}")
        print(f"Significant changes: {significant_changes}")

        if updates_made > 0:
            print()
            print("Updated weights are now active.")
            print("Questions you struggle with will appear more frequently!")
        else:
            print()
            print("All weights were already up to date.")

        return True

    except sqlite3.Error as e:
        print(f"ERROR during recalculation: {e}")
        conn.rollback()
        return False

    finally:
        conn.close()


def show_current_weights():
    """Show current weight distribution for verification."""

    try:
        conn = sqlite3.connect('quiz.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute('''
            SELECT qs.times_answered, qs.times_correct, qs.success_rate, qs.weight,
                   q.question_text
            FROM question_stats qs
            JOIN questions q ON qs.question_id = q.id
            WHERE qs.times_answered > 0
            ORDER BY qs.weight DESC
            LIMIT 10
        ''')

        top_weights = cursor.fetchall()

        if top_weights:
            print()
            print("Top 10 Highest Weighted Questions:")
            print("=" * 80)
            print("Success Rate | Attempts | Weight | Question")
            print("-" * 80)

            for stat in top_weights:
                question_preview = stat['question_text'][:40] + "..." if len(stat['question_text']) > 40 else stat['question_text']
                print(f"{stat['success_rate']:11.1%} | {stat['times_answered']:8d} | {stat['weight']:6.2f} | {question_preview}")

        conn.close()

    except sqlite3.Error as e:
        print(f"ERROR showing weights: {e}")


if __name__ == "__main__":
    print("This script will recalculate all question weights using the latest algorithm.")
    print("The new ultra-aggressive weighting will make struggling questions appear much more frequently.")
    print()

    success = recalculate_all_weights()

    if success:
        show_current_weights()
        print()
        print("You can now run 'python app.py' to start the quiz with updated weights!")
    else:
        print("Weight recalculation failed. Please check the errors above.")