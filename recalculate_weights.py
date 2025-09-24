#!/usr/bin/env python3
"""
Recalculate all question weights using the current weighting algorithm.

This script updates all existing question weights in the database
using the latest weighting formula from app.py.
"""

import sqlite3


# Configuration constants (matching app.py)
MAX_SUCCESS_RATE_CAP = 0.98  # Maximum success rate used for weight calculation (95%)
CONFIDENCE_THRESHOLD = 3  # Number of attempts needed for full confidence in statistics


def calculate_weight(times_answered, times_correct):
    """
    Calculate weight using the current ultra-aggressive algorithm from app.py.

    Args:
        times_answered: Total number of times question was answered
        times_correct: Number of times question was answered correctly

    Returns:
        float: Calculated weight for the question
    """
    # Calculate success rate
    if times_answered == 0:
        return 25.0  # Much higher weight for unanswered questions

    success_rate = times_correct / times_answered

    # Build confidence gradually (0.0 to 1.0 over CONFIDENCE_THRESHOLD attempts)
    confidence = min(times_answered / CONFIDENCE_THRESHOLD, 1.0)

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
            # Calculate new weight
            new_weight = calculate_weight(stat['times_answered'], stat['times_correct'])
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