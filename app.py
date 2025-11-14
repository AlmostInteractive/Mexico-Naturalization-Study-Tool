import sqlite3
import random
from flask import Flask, render_template, request, jsonify
from weight_calculator import calculate_weight, RECENT_ATTEMPTS_WINDOW, get_rolling_success_rate

# Initialize the Flask application
app = Flask(__name__)

WEIGHT_INCREMENT = 0.1


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


def is_question_mastered(question_id, cursor):
    """Check if a question is mastered (80%+ rolling success rate, 3+ attempts)."""
    rolling_success_rate, attempts = get_rolling_success_rate(question_id, cursor)
    return attempts >= 3 and rolling_success_rate >= 0.8


def increment_mastered_weights(cursor, increment=WEIGHT_INCREMENT):
    """Increment weights for mastered questions only."""
    # Get current max unlocked chunk
    cursor.execute('SELECT max_unlocked_chunk FROM user_progress WHERE id = 1')
    result = cursor.fetchone()
    max_chunk = result['max_unlocked_chunk'] if result else 1

    # Get all questions in unlocked chunks
    cursor.execute('''
        SELECT q.id FROM questions q
        WHERE q.chunk_number <= ?
    ''', (max_chunk,))

    all_questions = cursor.fetchall()

    # Increment weights only for mastered questions
    for question_row in all_questions:
        question_id = question_row['id']
        if is_question_mastered(question_id, cursor):
            cursor.execute('''
                UPDATE question_stats
                SET weight = weight + ?
                WHERE question_id = ?
            ''', (increment, question_id))


def update_question_stats(question_id, is_correct):
    """Update statistics for a question after it's been answered."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # First increment weights for mastered questions only
    increment_mastered_weights(cursor)

    # Record the individual attempt
    cursor.execute('''
        INSERT INTO question_attempts (question_id, is_correct)
        VALUES (?, ?)
    ''', (question_id, is_correct))

    # Get current stats (for total tracking)
    cursor.execute('''
        SELECT times_answered, times_correct FROM question_stats
        WHERE question_id = ?
    ''', (question_id,))

    result = cursor.fetchone()
    times_answered = result['times_answered'] + 1
    times_correct = result['times_correct'] + (1 if is_correct else 0)

    # Calculate lifetime success rate (for display purposes)
    lifetime_success_rate = times_correct / times_answered

    # Calculate weight based on mastery status
    if is_question_mastered(question_id, cursor):
        # Mastered question: reset to 1 if answered correctly, keep current if wrong
        if is_correct:
            weight = 1.0
        else:
            # Keep current weight (don't reset on wrong answer for mastered questions)
            cursor.execute('SELECT weight FROM question_stats WHERE question_id = ?', (question_id,))
            current_weight = cursor.fetchone()['weight']
            weight = current_weight
    else:
        # Unmastered question: use rolling success rate based weight
        weight = calculate_weight(question_id, times_answered, times_correct, cursor)

    # Update stats (store lifetime success rate for display, weight calculated by shared library)
    cursor.execute('''
        UPDATE question_stats
        SET times_answered = ?, times_correct = ?, success_rate = ?, weight = ?
        WHERE question_id = ?
    ''', (times_answered, times_correct, lifetime_success_rate, weight, question_id))

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

    # Count questions that meet the criteria (80% rolling success + answered at least 3 times)
    qualified_questions = 0
    for question in all_questions:
        if question['times_answered'] >= 3:
            rolling_success_rate, _ = get_rolling_success_rate(question['id'], cursor)
            if rolling_success_rate >= 0.8:
                qualified_questions += 1

    # For progress display
    answered_count = sum(1 for q in all_questions if q['times_answered'] >= 3)
    avg_success = sum(q['success_rate'] for q in all_questions if q['times_answered'] >= 3) / max(answered_count, 1)
    mastered_count = qualified_questions  # Questions with 80%+ rolling success rate AND answered 3+ times

    # Unlock next chunk if ALL questions have 80% rolling success rate AND have been answered at least 3 times
    if qualified_questions == total_in_set:
        # Get total chunks available
        cursor.execute('SELECT MAX(chunk_number) FROM questions')
        max_available_chunk = cursor.fetchone()[0] or 1

        # Only unlock next chunk if we haven't reached the maximum
        if max_chunk < max_available_chunk:
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


def get_unmastered_question(cursor, max_chunk, available_questions):
    """Select a question from unmastered questions based on rolling success rate weights."""
    unmastered_questions = []

    for q in available_questions:
        if not is_question_mastered(q['id'], cursor):
            # Use the current weight (calculated via rolling success rate)
            unmastered_questions.append(q)

    if not unmastered_questions:
        return None

    # Create weighted list based on current weights
    weights = [q['weight'] for q in unmastered_questions]
    selected_question = random.choices(unmastered_questions, weights=weights, k=1)[0]
    return dict(selected_question)


def get_mastered_question(cursor, max_chunk, available_questions):
    """Select a question from mastered questions based on aging weights."""
    mastered_questions = []

    for q in available_questions:
        if is_question_mastered(q['id'], cursor):
            mastered_questions.append(q)

    if not mastered_questions:
        return None

    # Create weighted list based on aging weights
    weights = [q['weight'] for q in mastered_questions]
    selected_question = random.choices(mastered_questions, weights=weights, k=1)[0]
    return dict(selected_question)


def get_weighted_question(exclude_question_id=None):
    """Select a question using 70/30 strategy: 70% unmastered, 30% mastered."""
    max_chunk, current_set_size, avg_success, answered_count, total_in_set, mastered_count = get_current_question_set()

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get questions only from unlocked chunks
    cursor.execute('''
        SELECT q.id, q.question_text, q.correct_answer, q.notes, qs.weight
        FROM questions q
        JOIN question_stats qs ON q.id = qs.question_id
        WHERE q.chunk_number <= ?
    ''', (max_chunk,))

    questions = cursor.fetchall()

    # Filter out the excluded question if specified
    if exclude_question_id is not None:
        questions = [q for q in questions if q['id'] != exclude_question_id]

    if not questions:
        conn.close()
        return None

    # 70/30 selection strategy
    if random.random() < 0.7:
        # 70% chance: Select from unmastered questions
        selected = get_unmastered_question(cursor, max_chunk, questions)
        if selected:
            conn.close()
            return selected
        # Fallback to mastered if no unmastered questions
        selected = get_mastered_question(cursor, max_chunk, questions)
        conn.close()
        return selected
    else:
        # 30% chance: Select from mastered questions
        selected = get_mastered_question(cursor, max_chunk, questions)
        if selected:
            conn.close()
            return selected
        # Fallback to unmastered if no mastered questions
        selected = get_unmastered_question(cursor, max_chunk, questions)
        conn.close()
        return selected


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
    # 0. Get previous question ID to avoid repeating
    prev_question_id = request.args.get('prev', type=int)

    # Debug logging
    if prev_question_id:
        print(f"[DEBUG] Excluding previous question ID: {prev_question_id}")
    else:
        print("[DEBUG] No previous question to exclude")

    # 1. Get current progress info
    max_chunk, current_set_size, avg_success, answered_count, total_in_set, mastered_count = get_current_question_set()

    # 2. Select a question using weighted probability
    question_data = get_weighted_question(exclude_question_id=prev_question_id)

    if not question_data:
        return "No questions available!", 500

    question_id = question_data['id']
    question_text = question_data['question_text']
    correct_answer = question_data['correct_answer']
    notes = question_data['notes']

    # Debug logging
    print(f"[DEBUG] Selected question ID: {question_id}")

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
        notes=notes,
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
        SELECT q.id, q.question_text, qs.times_answered, qs.times_correct,
               qs.success_rate, qs.weight
        FROM questions q
        JOIN question_stats qs ON q.id = qs.question_id
        WHERE qs.times_answered > 0
        ORDER BY qs.weight DESC
    ''')

    stats = cursor.fetchall()

    # Convert to list of dicts for JSON serialization, including rolling success rate
    stats_list = []
    for stat in stats:
        # Get rolling window success rate for this question
        cursor.execute('''
            SELECT is_correct FROM question_attempts
            WHERE question_id = ?
            ORDER BY attempt_timestamp DESC
            LIMIT ?
        ''', (stat['id'], RECENT_ATTEMPTS_WINDOW))

        recent_attempts = cursor.fetchall()
        if recent_attempts:
            recent_correct = sum(1 for attempt in recent_attempts if attempt['is_correct'])
            recent_total = len(recent_attempts)
            rolling_success_rate = recent_correct / recent_total
        else:
            rolling_success_rate = 0.0

        stats_list.append({
            'question': stat['question_text'][:50] + '...',  # Truncate for display
            'times_answered': stat['times_answered'],
            'times_correct': stat['times_correct'],
            'lifetime_success_rate': f"{stat['success_rate']:.1%}",
            'rolling_success_rate': f"{rolling_success_rate:.1%}",
            'weight': f"{stat['weight']:.2f}"
        })

    conn.close()

    return jsonify(stats_list)


@app.route('/delete_question', methods=['POST'])
def delete_question():
    """Delete a question and its associated statistics from the database."""
    data = request.get_json()
    question_id = data.get('question_id')

    if not question_id:
        return jsonify({'success': False, 'error': 'No question ID provided'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Check if this question exists and get its info
        cursor.execute('SELECT id, question_text, chunk_number FROM questions WHERE id = ?', (question_id,))
        question_info = cursor.fetchone()

        if not question_info:
            return jsonify({'success': False, 'error': 'Question not found'}), 404

        chunk_number = question_info['chunk_number']

        # Check how many questions will remain in this chunk
        cursor.execute('SELECT COUNT(*) FROM questions WHERE chunk_number = ?', (chunk_number,))
        questions_in_chunk = cursor.fetchone()[0]

        # Warn if this will empty the chunk
        if questions_in_chunk <= 1:
            return jsonify({
                'success': False,
                'error': f'Cannot delete question: this would empty chunk {chunk_number}. At least one question per chunk is required.'
            }), 400

        # Delete from question_attempts first (foreign key constraint)
        cursor.execute('DELETE FROM question_attempts WHERE question_id = ?', (question_id,))

        # Delete from question_stats
        cursor.execute('DELETE FROM question_stats WHERE question_id = ?', (question_id,))

        # Delete from questions
        cursor.execute('DELETE FROM questions WHERE id = ?', (question_id,))

        conn.commit()

        return jsonify({
            'success': True,
            'message': f'Question deleted successfully from chunk {chunk_number}',
            'remaining_in_chunk': questions_in_chunk - 1
        })

    except Exception as e:
        conn.rollback()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

    finally:
        conn.close()


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


# --- Geography Quiz Functions ---
def is_geography_mastered(geography_id, cursor):
    """Check if a geography question is mastered (80%+ rolling success rate, 3+ attempts)."""
    # Calculate rolling success rate from recent attempts
    cursor.execute('''
        SELECT is_correct FROM geography_attempts
        WHERE geography_id = ?
        ORDER BY attempt_timestamp DESC
        LIMIT ?
    ''', (geography_id, RECENT_ATTEMPTS_WINDOW))

    recent_attempts = cursor.fetchall()
    if not recent_attempts:
        return False

    recent_correct = sum(1 for attempt in recent_attempts if attempt['is_correct'])
    recent_total = len(recent_attempts)
    rolling_success_rate = recent_correct / recent_total

    return recent_total >= 3 and rolling_success_rate >= 0.8


def calculate_geography_weight(geography_id, times_answered, times_correct, cursor):
    """Calculate weight for a geography question based on rolling success rate."""
    if times_answered < 3:
        # Not enough attempts yet, use default weight
        return 1.0

    # Get rolling success rate
    cursor.execute('''
        SELECT is_correct FROM geography_attempts
        WHERE geography_id = ?
        ORDER BY attempt_timestamp DESC
        LIMIT ?
    ''', (geography_id, RECENT_ATTEMPTS_WINDOW))

    recent_attempts = cursor.fetchall()
    if not recent_attempts:
        return 1.0

    recent_correct = sum(1 for attempt in recent_attempts if attempt['is_correct'])
    recent_total = len(recent_attempts)
    rolling_success_rate = recent_correct / recent_total

    # Weight calculation: lower success rate = higher weight
    # 0% success = 5.0 weight, 50% success = 3.0 weight, 100% success = 1.0 weight
    weight = 1.0 + (4.0 * (1.0 - rolling_success_rate))
    return max(1.0, weight)


def increment_mastered_geography_weights(cursor, increment=WEIGHT_INCREMENT):
    """Increment weights for mastered geography questions only."""
    cursor.execute('SELECT id FROM geography_questions')
    all_geographies = cursor.fetchall()

    for geo_row in all_geographies:
        geography_id = geo_row['id']
        if is_geography_mastered(geography_id, cursor):
            cursor.execute('''
                UPDATE geography_stats
                SET weight = weight + ?
                WHERE geography_id = ?
            ''', (increment, geography_id))


def update_geography_stats(geography_id, is_correct):
    """Update statistics for a geography question after it's been answered."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # First increment weights for mastered geography questions only
    increment_mastered_geography_weights(cursor)

    # Record the individual attempt
    cursor.execute('''
        INSERT INTO geography_attempts (geography_id, is_correct)
        VALUES (?, ?)
    ''', (geography_id, is_correct))

    # Get current stats
    cursor.execute('''
        SELECT times_answered, times_correct FROM geography_stats
        WHERE geography_id = ?
    ''', (geography_id,))

    result = cursor.fetchone()
    times_answered = result['times_answered'] + 1
    times_correct = result['times_correct'] + (1 if is_correct else 0)

    # Calculate success rate
    success_rate = times_correct / times_answered

    # Calculate weight based on mastery status
    if is_geography_mastered(geography_id, cursor):
        # Mastered: reset to 1 if answered correctly, keep current if wrong
        if is_correct:
            weight = 1.0
        else:
            cursor.execute('SELECT weight FROM geography_stats WHERE geography_id = ?', (geography_id,))
            current_weight = cursor.fetchone()['weight']
            weight = current_weight
    else:
        # Unmastered: use rolling success rate based weight
        weight = calculate_geography_weight(geography_id, times_answered, times_correct, cursor)

    # Update stats
    cursor.execute('''
        UPDATE geography_stats
        SET times_answered = ?, times_correct = ?, success_rate = ?, weight = ?
        WHERE geography_id = ?
    ''', (times_answered, times_correct, success_rate, weight, geography_id))

    conn.commit()
    conn.close()


def get_weighted_geography_question(exclude_geography_id=None):
    """Select a geography question using 70/30 strategy: 70% unmastered, 30% mastered."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all geography questions with their stats
    cursor.execute('''
        SELECT g.id, g.state_number, g.state_name, gs.weight
        FROM geography_questions g
        JOIN geography_stats gs ON g.id = gs.geography_id
    ''')

    geographies = cursor.fetchall()

    # Filter out the excluded question if specified
    if exclude_geography_id is not None:
        geographies = [g for g in geographies if g['id'] != exclude_geography_id]

    if not geographies:
        conn.close()
        return None

    # Separate into mastered and unmastered
    unmastered = [g for g in geographies if not is_geography_mastered(g['id'], cursor)]
    mastered = [g for g in geographies if is_geography_mastered(g['id'], cursor)]

    # 70/30 selection strategy
    if random.random() < 0.7:
        # 70% chance: Select from unmastered questions
        if unmastered:
            weights = [g['weight'] for g in unmastered]
            selected = random.choices(unmastered, weights=weights, k=1)[0]
            conn.close()
            return dict(selected)
        # Fallback to mastered if no unmastered questions
        if mastered:
            weights = [g['weight'] for g in mastered]
            selected = random.choices(mastered, weights=weights, k=1)[0]
            conn.close()
            return dict(selected)
    else:
        # 30% chance: Select from mastered questions
        if mastered:
            weights = [g['weight'] for g in mastered]
            selected = random.choices(mastered, weights=weights, k=1)[0]
            conn.close()
            return dict(selected)
        # Fallback to unmastered if no mastered questions
        if unmastered:
            weights = [g['weight'] for g in unmastered]
            selected = random.choices(unmastered, weights=weights, k=1)[0]
            conn.close()
            return dict(selected)

    conn.close()
    return None


# --- Geography Routes ---
@app.route('/geography')
def geography_quiz():
    """Display the geography quiz page."""
    # Get previous question ID to avoid repeating
    prev_geography_id = request.args.get('prev', type=int)

    # Select a geography question using weighted probability
    geography_data = get_weighted_geography_question(exclude_geography_id=prev_geography_id)

    if not geography_data:
        return "No geography questions available!", 500

    geography_id = geography_data['id']
    state_number = geography_data['state_number']
    correct_state = geography_data['state_name']

    # Randomly select mode (1 or 2)
    mode = random.randint(1, 2)

    # Get 3 random incorrect states as distractors (for mode 1)
    options = []
    if mode == 1:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT state_name FROM geography_questions
            WHERE id != ?
            ORDER BY RANDOM()
            LIMIT 3
        ''', (geography_id,))
        distractors = [row['state_name'] for row in cursor.fetchall()]
        conn.close()

        # Combine correct answer with distractors and shuffle
        options = distractors + [correct_state]
        random.shuffle(options)

    # Get progress stats
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) as total,
               SUM(CASE WHEN times_answered >= 3 THEN 1 ELSE 0 END) as answered_enough,
               COUNT(CASE WHEN times_answered >= 3 THEN 1 END) as answered_count
        FROM geography_stats
    ''')
    stats = cursor.fetchone()

    # Count mastered questions
    cursor.execute('SELECT id FROM geography_questions')
    all_geo_ids = cursor.fetchall()
    mastered_count = sum(1 for geo_row in all_geo_ids if is_geography_mastered(geo_row['id'], cursor))

    conn.close()

    return render_template(
        'geography.html',
        geography_id=geography_id,
        state_number=state_number,
        correct_state=correct_state,
        options=options,
        mode=mode,
        total_states=stats['total'],
        answered_count=stats['answered_count'],
        mastered_count=mastered_count
    )


@app.route('/geography_answer', methods=['POST'])
def record_geography_answer():
    """Record the user's answer to a geography question."""
    data = request.get_json()

    geography_id = data.get('geography_id')
    selected_answer = data.get('selected_answer')
    correct_answer = data.get('correct_answer')

    # Determine if answer is correct
    is_correct = selected_answer == correct_answer

    # Update geography statistics
    update_geography_stats(geography_id, is_correct)

    return jsonify({
        'success': True,
        'is_correct': is_correct
    })


@app.route('/geographyDebug')
def geography_debug():
    """Debug page to test state highlighting."""
    # Get state number from query parameter
    state_id = request.args.get('id', type=int)

    if state_id is None:
        return "Please provide a state ID: /geographyDebug?id=1", 400

    # Get state info from database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM geography_questions WHERE state_number = ?', (state_id,))
    state_info = cursor.fetchone()
    conn.close()

    if not state_info:
        return f"State number {state_id} not found in database", 404

    return render_template(
        'geography_debug.html',
        state_number=state_id,
        state_name=state_info['state_name']
    )


@app.route('/geography_stats')
def show_geography_stats():
    """Show geography learning statistics."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT g.id, g.state_name, g.state_number, gs.times_answered, gs.times_correct,
               gs.success_rate, gs.weight
        FROM geography_questions g
        JOIN geography_stats gs ON g.id = gs.geography_id
        ORDER BY gs.weight DESC, g.state_number ASC
    ''')

    stats = cursor.fetchall()

    # Convert to list of dicts for JSON serialization, including rolling success rate
    stats_list = []
    for stat in stats:
        # Get rolling window success rate for this state
        cursor.execute('''
            SELECT is_correct FROM geography_attempts
            WHERE geography_id = ?
            ORDER BY attempt_timestamp DESC
            LIMIT ?
        ''', (stat['id'], RECENT_ATTEMPTS_WINDOW))

        recent_attempts = cursor.fetchall()
        if recent_attempts:
            recent_correct = sum(1 for attempt in recent_attempts if attempt['is_correct'])
            recent_total = len(recent_attempts)
            rolling_success_rate = recent_correct / recent_total
        else:
            rolling_success_rate = 0.0

        stats_list.append({
            'state': f"{stat['state_number']}. {stat['state_name']}",
            'times_answered': stat['times_answered'],
            'times_correct': stat['times_correct'],
            'lifetime_success_rate': f"{stat['success_rate']:.1%}",
            'rolling_success_rate': f"{rolling_success_rate:.1%}",
            'weight': f"{stat['weight']:.2f}"
        })

    conn.close()

    return jsonify(stats_list)


# --- Main execution block ---
if __name__ == '__main__':
    # Runs the Flask app. 'debug=True' means the server will auto-reload
    # when you save changes to the file, which is great for development.
    app.run(debug=True, use_reloader=False)
