import sqlite3
import sys

def reset_progress():
    """Reset all learning progress while keeping questions intact."""

    try:
        conn = sqlite3.connect('quiz.db')
        cursor = conn.cursor()

        print("🔄 Mexico Study Guide - Progress Reset")
        print("=" * 40)

        # Check if database exists and has data
        cursor.execute('SELECT COUNT(*) FROM questions')
        question_count = cursor.fetchone()[0]

        if question_count == 0:
            print("❌ No questions found in database!")
            print("   Run the setup scripts first to load questions.")
            conn.close()
            return False

        # Reset user progress to beginning
        cursor.execute('''
            UPDATE user_progress
            SET max_unlocked_chunk = 1, questions_in_current_set = 10
            WHERE id = 1
        ''')

        # Reset all question statistics
        cursor.execute('''
            UPDATE question_stats
            SET times_answered = 0, times_correct = 0, success_rate = 0.0, weight = 10.0
        ''')

        # Get counts for confirmation
        cursor.execute('SELECT COUNT(*) FROM question_stats WHERE times_answered > 0')
        remaining_stats = cursor.fetchone()[0]

        conn.commit()
        conn.close()

        print(f"✅ Progress reset successfully!")
        print(f"📊 {question_count} questions preserved")
        print(f"🔄 All statistics cleared")
        print(f"🎯 Back to Chunk 1 (first 10 questions)")
        print()
        print("Next steps:")
        print("  - Run 'python app.py' to start fresh")
        print("  - Begin with the first 10 questions again")

        return True

    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def main():
    print("⚠️  WARNING: This will reset ALL your learning progress!")
    print("   Your questions will be preserved, but all statistics will be cleared.")
    print("   You'll start over from Chunk 1 with fresh progress tracking.")
    print()

    # Confirm reset
    confirm = input("Are you sure you want to reset? Type 'yes' to confirm: ").lower().strip()

    if confirm == 'yes':
        success = reset_progress()
        if not success:
            sys.exit(1)
    else:
        print("Reset cancelled.")

if __name__ == "__main__":
    main()