import sqlite3
import random
from flask import Flask, render_template, request, jsonify

# Configuration constants
MAX_SUCCESS_RATE_CAP = 0.98  # Maximum success rate used for weight calculation (95%)
CONFIDENCE_THRESHOLD = 3  # Number of attempts needed for full confidence in statistics

# Initialize the Flask application
app = Flask(__name__)


# --- Database Functions ---
def get_db_connection():
    """Get a database connection."""
    conn = sqlite3.connect('quiz.db')
    conn.row_factory = sqlite3.Row  # This enables column access by name
    return conn


def get_total_chunks():
    """Calculate total number of chunks based on questions in database."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('SELECT MAX(chunk_number) FROM questions')
    result = cursor.fetchone()
    conn.close()

    return result[0] if result[0] else 1


def update_question_stats(question_id, is_correct):
    """Update statistics for a question after it's been answered."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get current stats
    cursor.execute('''
        SELECT times_answered, times_correct FROM question_stats
        WHERE question_id = ?
    ''', (question_id,))

    result = cursor.fetchone()
    times_answered = result['times_answered'] + 1
    times_correct = result['times_correct'] + (1 if is_correct else 0)

    # Calculate success rate
    if times_answered == 0:
        success_rate = 0.0
    else:
        success_rate = times_correct / times_answered

    # Modified exponential weighting system
    if times_answered == 0:
        weight = 25.0  # Much higher weight for unanswered questions
    else:
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

    # Update stats
    cursor.execute('''
        UPDATE question_stats
        SET times_answered = ?, times_correct = ?, success_rate = ?, weight = ?
        WHERE question_id = ?
    ''', (times_answered, times_correct, success_rate, weight, question_id))

    conn.commit()
    conn.close()


def get_current_question_set():
    """Determine which questions are currently active based on user progress."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get current progress
    cursor.execute('SELECT max_unlocked_chunk, questions_in_current_set FROM user_progress WHERE id = 1')
    result = cursor.fetchone()

    if result:
        max_chunk, current_set_size = result
    else:
        max_chunk, current_set_size = 1, 10

    # Check if we should unlock the next chunk
    # Get all questions in current active set with their individual success rates
    cursor.execute('''
        SELECT q.id, qs.success_rate, qs.times_answered
        FROM questions q
        JOIN question_stats qs ON q.id = qs.question_id
        WHERE q.chunk_number <= ?
        ORDER BY q.id
    ''', (max_chunk,))

    all_questions = cursor.fetchall()
    total_in_set = len(all_questions)

    # Count questions that meet the criteria (80% success + answered at least 3 times)
    qualified_questions = 0
    for question in all_questions:
        if question['times_answered'] >= 3 and question['success_rate'] >= 0.8:
            qualified_questions += 1

    # For progress display
    answered_count = sum(1 for q in all_questions if q['times_answered'] >= 3)
    avg_success = sum(q['success_rate'] for q in all_questions if q['times_answered'] >= 3) / max(answered_count, 1)
    mastered_count = qualified_questions  # Questions with 80%+ success rate AND answered 3+ times

    # Unlock next chunk if ALL questions have 80% success rate AND have been answered at least 3 times
    if qualified_questions == total_in_set:
        # Unlock next chunk
        new_max_chunk = max_chunk + 1
        new_set_size = min(current_set_size + 10, 147)  # Don't exceed total questions

        cursor.execute('''
            UPDATE user_progress
            SET max_unlocked_chunk = ?, questions_in_current_set = ?
            WHERE id = 1
        ''', (new_max_chunk, new_set_size))

        conn.commit()
        max_chunk = new_max_chunk
        current_set_size = new_set_size

    conn.close()
    return max_chunk, current_set_size, avg_success, answered_count, total_in_set, mastered_count

def get_weighted_question():
    """Select a question based on weighted probability from current active set."""
    max_chunk, current_set_size, avg_success, answered_count, total_in_set, mastered_count = get_current_question_set()

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get questions only from unlocked chunks
    cursor.execute('''
        SELECT q.id, q.question_text, q.correct_answer, qs.weight
        FROM questions q
        JOIN question_stats qs ON q.id = qs.question_id
        WHERE q.chunk_number <= ?
    ''', (max_chunk,))

    questions = cursor.fetchall()
    conn.close()

    if not questions:
        return None

    # Check if we have a previous question stored in session
    # Use a simple approach - store in the app's memory temporarily
    if hasattr(get_weighted_question, 'last_question_id'):
        last_id = get_weighted_question.last_question_id

        # If we have more than one question available, filter out the last one
        if len(questions) > 1:
            questions = [q for q in questions if q['id'] != last_id]

    # Create weighted list
    weights = [q['weight'] for q in questions]

    # Use random.choices for weighted selection
    selected_question = random.choices(questions, weights=weights, k=1)[0]

    # Store the selected question ID to avoid repetition
    get_weighted_question.last_question_id = selected_question['id']

    return dict(selected_question)


def get_distractors_for_question(question_id):
    """Get distractors for a specific question."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT distractor1, distractor2, distractor3, distractor4,
               distractor5, distractor6, distractor7, distractor8
        FROM questions
        WHERE id = ?
    ''', (question_id,))

    result = cursor.fetchone()
    conn.close()

    if result:
        # Filter out empty distractors and return as list
        distractors = [d for d in result if d and d.strip()]
        return distractors
    else:
        return []


# --- Routes ---
@app.route('/')
def quiz():
    """
    This function handles the logic for a single quiz question with weighted selection.
    """
    # 1. Get current progress info
    max_chunk, current_set_size, avg_success, answered_count, total_in_set, mastered_count = get_current_question_set()

    # 2. Select a question using weighted probability
    question_data = get_weighted_question()

    if not question_data:
        return "No questions available!", 500

    question_id = question_data['id']
    question_text = question_data['question_text']
    correct_answer = question_data['correct_answer']

    # 3. Get distractors for this question
    all_distractors = get_distractors_for_question(question_id)

    # 4. Select 3 random distractors
    if len(all_distractors) >= 3:
        distractors = random.sample(all_distractors, 3)
    else:
        # Fallback: use all available distractors and pad if needed
        distractors = all_distractors
        while len(distractors) < 3:
            distractors.append("Respuesta no disponible")

    # 5. Combine the correct answer with the distractors to create the final options
    options = distractors + [correct_answer]

    # 6. Shuffle the options so the correct answer isn't always the last one
    random.shuffle(options)

    # 7. Add "I don't know" option at the end (always last position)
    options.append("No sé")

    # 8. Render the HTML template, passing in the data it needs
    return render_template(
        'index.html',
        question=question_text,
        options=options,
        correct_answer=correct_answer,
        question_id=question_id,
        # Progress information
        current_chunk=max_chunk,
        total_chunks=get_total_chunks(),
        current_set_size=current_set_size,
        mastered_count=mastered_count,
        total_in_set=total_in_set,
        progress_ratio=f"{answered_count}/{total_in_set}"
    )


@app.route('/answer', methods=['POST'])
def record_answer():
    """Record the user's answer and update statistics."""
    data = request.get_json()

    question_id = data.get('question_id')
    selected_answer = data.get('selected_answer')
    correct_answer = data.get('correct_answer')

    # Determine if answer is correct
    is_correct = selected_answer == correct_answer

    # Update question statistics
    update_question_stats(question_id, is_correct)

    return jsonify({
        'success': True,
        'is_correct': is_correct
    })


@app.route('/stats')
def show_stats():
    """Show learning statistics (for debugging/monitoring)."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT q.question_text, qs.times_answered, qs.times_correct,
               qs.success_rate, qs.weight
        FROM questions q
        JOIN question_stats qs ON q.id = qs.question_id
        WHERE qs.times_answered > 0
        ORDER BY qs.weight DESC
    ''')

    stats = cursor.fetchall()
    conn.close()

    # Convert to list of dicts for JSON serialization
    stats_list = []
    for stat in stats:
        stats_list.append({
            'question': stat['question_text'][:50] + '...',  # Truncate for display
            'times_answered': stat['times_answered'],
            'times_correct': stat['times_correct'],
            'success_rate': f"{stat['success_rate']:.1%}",
            'weight': f"{stat['weight']:.2f}"
        })

    return jsonify(stats_list)

@app.route('/progress')
def show_progress():
    """Show detailed learning progress."""
    max_chunk, current_set_size, avg_success, answered_count, total_in_set, mastered_count = get_current_question_set()

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get progress by chunk
    cursor.execute('''
        SELECT q.chunk_number,
               COUNT(*) as total_questions,
               AVG(qs.success_rate) as avg_success_rate,
               SUM(CASE WHEN qs.times_answered >= 3 THEN 1 ELSE 0 END) as answered_enough
        FROM questions q
        JOIN question_stats qs ON q.id = qs.question_id
        WHERE q.chunk_number <= ?
        GROUP BY q.chunk_number
        ORDER BY q.chunk_number
    ''', (max_chunk,))

    chunk_progress = cursor.fetchall()
    conn.close()

    return jsonify({
        'current_chunk': max_chunk,
        'total_chunks': get_total_chunks(),
        'current_set_size': current_set_size,
        'overall_success_rate': f"{avg_success:.1%}" if avg_success else "0%",
        'answered_count': answered_count,
        'total_in_set': total_in_set,
        'chunk_details': [
            {
                'chunk': chunk['chunk_number'],
                'total_questions': chunk['total_questions'],
                'success_rate': f"{chunk['avg_success_rate']:.1%}" if chunk['avg_success_rate'] else "0%",
                'answered_enough': chunk['answered_enough']
            }
            for chunk in chunk_progress
        ]
    })


# --- Main execution block ---
if __name__ == '__main__':
    # Runs the Flask app. 'debug=True' means the server will auto-reload
    # when you save changes to the file, which is great for development.
    app.run(debug=True, use_reloader=False)
