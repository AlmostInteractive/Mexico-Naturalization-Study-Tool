import sqlite3
import random
import secrets
from flask import Flask, render_template, request, jsonify, session
from weight_calculator import RECENT_ATTEMPTS_WINDOW, get_rolling_success_rate

# Initialize the Flask application
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False  # Preserve unicode characters in JSON responses
app.secret_key = secrets.token_hex(32)  # Generate a secure random secret key for sessions

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


def update_question_stats(question_id, is_correct):
    """
    Update statistics for a question after it's been answered.

    Simplified linear weight system:
    - Correct answer: reset this question to 0.0, increment all others in same category by 0.1
    - Incorrect answer: keep current weight (accumulates through other questions)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

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

    # Get current max unlocked chunk for category filtering
    cursor.execute('SELECT max_unlocked_chunk FROM user_progress WHERE id = 1')
    progress_result = cursor.fetchone()
    max_chunk = progress_result['max_unlocked_chunk'] if progress_result else 1

    # Determine if this question is mastered (for category separation and storage)
    is_mastered = is_question_mastered(question_id, cursor)
    is_mastered_int = 1 if is_mastered else 0

    if is_correct:
        # Reset this question's weight to 0.0
        weight = 0.0

        # Increment all OTHER questions in the same category by 0.1
        # Category = mastered vs unmastered (using stored is_mastered attribute)
        cursor.execute('''
            UPDATE question_stats
            SET weight = weight + ?
            WHERE question_id IN (
                SELECT id FROM questions WHERE chunk_number <= ? AND id != ?
            )
            AND is_mastered = ?
        ''', (WEIGHT_INCREMENT, max_chunk, question_id, is_mastered_int))
    else:
        # Keep current weight (it will accumulate as other questions are answered correctly)
        cursor.execute('SELECT weight FROM question_stats WHERE question_id = ?', (question_id,))
        current_weight = cursor.fetchone()['weight']
        weight = current_weight

    # Update stats (store lifetime success rate, weight, and mastery status)
    cursor.execute('''
        UPDATE question_stats
        SET times_answered = ?, times_correct = ?, success_rate = ?, weight = ?, is_mastered = ?
        WHERE question_id = ?
    ''', (times_answered, times_correct, lifetime_success_rate, weight, is_mastered_int, question_id))

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

    # If all weights are zero, use uniform random selection
    if sum(weights) == 0:
        selected_question = random.choice(unmastered_questions)
    else:
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

    # If all weights are zero, use uniform random selection
    if sum(weights) == 0:
        selected_question = random.choice(mastered_questions)
    else:
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
    # 0. Get previous question ID from session to avoid repeating
    prev_question_id = session.get('prev_question_id')

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

    # Store this question ID in session for next request
    session['prev_question_id'] = question_id

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
               qs.success_rate, qs.weight, qs.is_mastered
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
            'weight': f"{stat['weight']:.2f}",
            'is_mastered': bool(stat['is_mastered'])
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
def get_rolling_success_rate_geography(geography_id, cursor, window_size=RECENT_ATTEMPTS_WINDOW):
    """Calculate success rate based on the last N attempts for geography questions."""
    cursor.execute('''
        SELECT is_correct FROM geography_attempts
        WHERE geography_id = ?
        ORDER BY attempt_timestamp DESC
        LIMIT ?
    ''', (geography_id, window_size))

    recent_attempts = cursor.fetchall()

    if not recent_attempts:
        return 0.0, 0

    recent_correct = sum(1 for attempt in recent_attempts if attempt['is_correct'])
    recent_total = len(recent_attempts)

    return recent_correct / recent_total, recent_total


def is_geography_mastered(geography_id, cursor):
    """Check if a geography question is mastered (80%+ rolling success rate, 3+ attempts)."""
    rolling_success_rate, attempts = get_rolling_success_rate_geography(geography_id, cursor)
    return attempts >= 3 and rolling_success_rate >= 0.8


def update_geography_stats(geography_id, is_correct):
    """
    Update statistics for a geography question after it's been answered.

    Simplified linear weight system:
    - Correct answer: reset this question to 0.0, increment all others in same category by 0.1
    - Incorrect answer: keep current weight (accumulates through other questions)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Record the individual attempt
    cursor.execute('''
        INSERT INTO geography_attempts (geography_id, is_correct)
        VALUES (?, ?)
    ''', (geography_id, is_correct))

    # Get current stats (for total tracking)
    cursor.execute('''
        SELECT times_answered, times_correct FROM geography_stats
        WHERE geography_id = ?
    ''', (geography_id,))

    result = cursor.fetchone()
    times_answered = result['times_answered'] + 1
    times_correct = result['times_correct'] + (1 if is_correct else 0)

    # Calculate lifetime success rate (for display purposes)
    lifetime_success_rate = times_correct / times_answered

    # Determine if this question is mastered (for category separation)
    is_mastered = is_geography_mastered(geography_id, cursor)
    is_mastered_int = 1 if is_mastered else 0

    if is_correct:
        # Reset this question's weight to 0.0
        weight = 0.0

        # Increment all OTHER questions in the same category by 0.1
        # Category = mastered vs unmastered
        cursor.execute('''
            UPDATE geography_stats
            SET weight = weight + ?
            WHERE geography_id IN (
                SELECT id FROM geography_questions WHERE id != ?
            )
            AND is_mastered = ?
        ''', (WEIGHT_INCREMENT, geography_id, is_mastered_int))
    else:
        # Keep current weight (it will accumulate as other questions are answered correctly)
        cursor.execute('SELECT weight FROM geography_stats WHERE geography_id = ?', (geography_id,))
        current_weight = cursor.fetchone()['weight']
        weight = current_weight

    # Update stats (store lifetime success rate, weight, and mastery status)
    cursor.execute('''
        UPDATE geography_stats
        SET times_answered = ?, times_correct = ?, success_rate = ?, weight = ?, is_mastered = ?
        WHERE geography_id = ?
    ''', (times_answered, times_correct, lifetime_success_rate, weight, is_mastered_int, geography_id))

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
            if sum(weights) == 0:
                selected = random.choice(unmastered)
            else:
                selected = random.choices(unmastered, weights=weights, k=1)[0]
            conn.close()
            return dict(selected)
        # Fallback to mastered if no unmastered questions
        if mastered:
            weights = [g['weight'] for g in mastered]
            if sum(weights) == 0:
                selected = random.choice(mastered)
            else:
                selected = random.choices(mastered, weights=weights, k=1)[0]
            conn.close()
            return dict(selected)
    else:
        # 30% chance: Select from mastered questions
        if mastered:
            weights = [g['weight'] for g in mastered]
            if sum(weights) == 0:
                selected = random.choice(mastered)
            else:
                selected = random.choices(mastered, weights=weights, k=1)[0]
            conn.close()
            return dict(selected)
        # Fallback to unmastered if no mastered questions
        if unmastered:
            weights = [g['weight'] for g in unmastered]
            if sum(weights) == 0:
                selected = random.choice(unmastered)
            else:
                selected = random.choices(unmastered, weights=weights, k=1)[0]
            conn.close()
            return dict(selected)

    conn.close()
    return None


# --- Geography Routes ---
@app.route('/geography')
def geography_quiz():
    """Display the geography quiz page."""
    # Check if this is part 2 (capital question)
    part = request.args.get('part', type=int, default=1)
    geography_id_param = request.args.get('geography_id', type=int)

    # If part 2, show capital question
    if part == 2 and geography_id_param:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get the state info
        cursor.execute('''
            SELECT id, state_name, capital
            FROM geography_questions
            WHERE id = ?
        ''', (geography_id_param,))
        state_data = cursor.fetchone()

        if not state_data:
            conn.close()
            return "State not found!", 404

        geography_id = state_data['id']
        state_name = state_data['state_name']
        correct_capital = state_data['capital']

        # Get 3-4 random incorrect capitals as distractors
        # (we might need 4 if we replace one with the state name)
        cursor.execute('''
            SELECT capital FROM geography_questions
            WHERE id != ?
            ORDER BY RANDOM()
            LIMIT 4
        ''', (geography_id,))
        distractors = [row['capital'] for row in cursor.fetchall()]

        # If the capital doesn't contain the state name, add state name as a distractor
        if state_name.lower() not in correct_capital.lower():
            # Replace one of the distractors with the state name
            distractors = distractors[:2] + [state_name]
        else:
            # Use only 3 distractors
            distractors = distractors[:3]

        # Combine correct answer with distractors and shuffle
        options = distractors + [correct_capital]
        random.shuffle(options)

        # Get progress stats (same as part 1)
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
            part=2,
            geography_id=geography_id,
            question_text=f"¿Cuál es la capital de {state_name}?",
            correct_answer=correct_capital,
            state_name=state_name,
            options=options,
            mode=1,  # Always mode 1 (multiple choice) for capital questions
            state_number=None,
            correct_state=None,
            total_states=stats['total'],
            answered_count=stats['answered_count'],
            mastered_count=mastered_count
        )

    # Part 1: State identification question
    # Get previous question ID from session to avoid repeating
    prev_geography_id = session.get('prev_geography_id')

    # Select a geography question using weighted probability
    geography_data = get_weighted_geography_question(exclude_geography_id=prev_geography_id)

    if not geography_data:
        return "No geography questions available!", 500

    geography_id = geography_data['id']
    state_number = geography_data['state_number']
    correct_state = geography_data['state_name']

    # Store this geography ID in session for next request
    session['prev_geography_id'] = geography_id

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
        part=1,
        geography_id=geography_id,
        state_number=state_number,
        correct_state=correct_state,
        correct_answer=correct_state,
        options=options,
        mode=mode,
        question_text=None,
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
    part = data.get('part', 1)

    # Determine if answer is correct
    is_correct = selected_answer == correct_answer

    if part == 1:
        # Part 1: State identification
        if is_correct:
            # Don't update geography_stats yet - wait for Part 2
            # Only proceed to Part 2 if Part 1 is correct
            return jsonify({
                'success': True,
                'is_correct': is_correct,
                'show_capital': True,
                'geography_id': geography_id
            })
        else:
            # Part 1 incorrect: Mark the entire question as incorrect
            update_geography_stats(geography_id, False)

            # Skip Part 2, move to next question
            return jsonify({
                'success': True,
                'is_correct': False,
                'show_capital': False,
                'geography_id': geography_id
            })
    else:
        # Part 2: Capital question
        # Since we only reach Part 2 if Part 1 was correct,
        # the Part 2 result determines the overall question result

        # Update geography statistics with Part 2 result
        # (represents combined Part 1 + Part 2 correctness)
        update_geography_stats(geography_id, is_correct)

        # Always move to next question after part 2
        return jsonify({
            'success': True,
            'is_correct': is_correct,
            'show_capital': False
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
               gs.success_rate, gs.weight, gs.is_mastered
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
            'weight': f"{stat['weight']:.2f}",
            'is_mastered': bool(stat['is_mastered'])
        })

    conn.close()

    return jsonify(stats_list)


# --- Multiline Quiz Functions ---
def calculate_required_correct(total_items):
    """Calculate how many correct answers are required based on list size."""
    if total_items <= 5:
        return total_items  # All items required
    else:
        return int(total_items * 0.8 + 0.5)  # 80% rounded up


def is_multiline_item_mastered(item_id, cursor):
    """Check if a multiline item is mastered (80%+ rolling success rate, 3+ attempts)."""
    cursor.execute('''
        SELECT is_correct FROM multiline_attempts
        WHERE item_id = ?
        ORDER BY attempt_timestamp DESC
        LIMIT ?
    ''', (item_id, RECENT_ATTEMPTS_WINDOW))

    recent_attempts = cursor.fetchall()

    if not recent_attempts:
        return False

    recent_correct = sum(1 for attempt in recent_attempts if attempt['is_correct'])
    recent_total = len(recent_attempts)
    rolling_success_rate = recent_correct / recent_total

    return recent_total >= 3 and rolling_success_rate >= 0.8


def update_multiline_stats(item_id, is_correct):
    """
    Update statistics for a multiline item after it's been answered.

    Simplified linear weight system:
    - Correct answer: reset this item to 0.0, increment all others in same category by 0.1
    - Incorrect answer: keep current weight (accumulates through other questions)
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Record the individual attempt
    cursor.execute('''
        INSERT INTO multiline_attempts (item_id, is_correct)
        VALUES (?, ?)
    ''', (item_id, is_correct))

    # Get current stats
    cursor.execute('''
        SELECT times_shown, times_correct FROM multiline_stats
        WHERE item_id = ?
    ''', (item_id,))

    result = cursor.fetchone()
    times_shown = result['times_shown'] + 1
    times_correct = result['times_correct'] + (1 if is_correct else 0)

    # Calculate lifetime success rate
    lifetime_success_rate = times_correct / times_shown

    # Determine if this item is mastered (for category separation)
    is_mastered = is_multiline_item_mastered(item_id, cursor)
    is_mastered_int = 1 if is_mastered else 0

    # Get the question_id for this item (for category filtering)
    cursor.execute('''
        SELECT question_id FROM multiline_items WHERE id = ?
    ''', (item_id,))
    question_id = cursor.fetchone()['question_id']

    if is_correct:
        # Reset this item's weight to 0.0
        weight = 0.0

        # Increment all OTHER items in the same category by 0.1
        # Category = same question + same mastery status
        cursor.execute('''
            UPDATE multiline_stats
            SET weight = weight + ?
            WHERE item_id IN (
                SELECT id FROM multiline_items WHERE question_id = ? AND id != ?
            )
            AND is_mastered = ?
        ''', (WEIGHT_INCREMENT, question_id, item_id, is_mastered_int))
    else:
        # Keep current weight (it will accumulate as other items are answered correctly)
        cursor.execute('SELECT weight FROM multiline_stats WHERE item_id = ?', (item_id,))
        current_weight = cursor.fetchone()['weight']
        weight = current_weight

    # Update stats
    cursor.execute('''
        UPDATE multiline_stats
        SET times_shown = ?, times_correct = ?, success_rate = ?, weight = ?, is_mastered = ?
        WHERE item_id = ?
    ''', (times_shown, times_correct, lifetime_success_rate, weight, is_mastered_int, item_id))

    conn.commit()
    conn.close()


def get_weighted_multiline_question(exclude_question_id=None):
    """Select a multiline question using 70/30 strategy: 70% unmastered, 30% mastered."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get all multiline questions with their average weight and mastery status
    cursor.execute('''
        SELECT
            mq.id,
            mq.question_text,
            mq.category,
            mq.total_items,
            mq.required_correct,
            AVG(ms.weight) as avg_weight,
            AVG(ms.is_mastered) as mastery_ratio
        FROM multiline_questions mq
        JOIN multiline_items mi ON mq.id = mi.question_id
        JOIN multiline_stats ms ON mi.id = ms.item_id
        GROUP BY mq.id
    ''')

    questions = cursor.fetchall()

    # Filter out the excluded question if specified
    if exclude_question_id is not None:
        questions = [q for q in questions if q['id'] != exclude_question_id]

    if not questions:
        conn.close()
        return None

    # Separate into mastered and unmastered based on mastery ratio
    # A question is considered "mastered" if >80% of its items are mastered
    unmastered = [q for q in questions if q['mastery_ratio'] < 0.8]
    mastered = [q for q in questions if q['mastery_ratio'] >= 0.8]

    # 70/30 selection strategy
    if random.random() < 0.7:
        # 70% chance: Select from unmastered questions
        if unmastered:
            weights = [q['avg_weight'] for q in unmastered]
            if sum(weights) == 0:
                selected = random.choice(unmastered)
            else:
                selected = random.choices(unmastered, weights=weights, k=1)[0]
            conn.close()
            return dict(selected)
        # Fallback to mastered if no unmastered questions
        if mastered:
            weights = [q['avg_weight'] for q in mastered]
            if sum(weights) == 0:
                selected = random.choice(mastered)
            else:
                selected = random.choices(mastered, weights=weights, k=1)[0]
            conn.close()
            return dict(selected)
    else:
        # 30% chance: Select from mastered questions
        if mastered:
            weights = [q['avg_weight'] for q in mastered]
            if sum(weights) == 0:
                selected = random.choice(mastered)
            else:
                selected = random.choices(mastered, weights=weights, k=1)[0]
            conn.close()
            return dict(selected)
        # Fallback to unmastered if no mastered questions
        if unmastered:
            weights = [q['avg_weight'] for q in unmastered]
            if sum(weights) == 0:
                selected = random.choice(unmastered)
            else:
                selected = random.choices(unmastered, weights=weights, k=1)[0]
            conn.close()
            return dict(selected)

    conn.close()
    return None


# --- Multiline Routes ---
@app.route('/multiline')
def multiline_quiz():
    """Display the progressive multiline question quiz."""
    # Get session_id from query parameter
    session_id = request.args.get('session', type=int)

    conn = get_db_connection()
    cursor = conn.cursor()

    # If we have a session, load it
    if session_id:
        cursor.execute('''
            SELECT question_id, items_answered, consecutive_correct, completed
            FROM multiline_sessions
            WHERE id = ?
        ''', (session_id,))
        session = cursor.fetchone()

        if session and not session['completed']:
            question_id = session['question_id']
            items_answered = session['items_answered'].split(',') if session['items_answered'] else []
            consecutive_correct = session['consecutive_correct']
        else:
            # Session completed or not found, start a new question
            session_id = None
    else:
        session_id = None

    # If no valid session, start a new question
    if not session_id:
        # Select a question
        question_data = get_weighted_multiline_question()
        if not question_data:
            conn.close()
            return "No multiline questions available!", 500

        question_id = question_data['id']
        items_answered = []
        consecutive_correct = 0

        # Create a new session
        cursor.execute('''
            INSERT INTO multiline_sessions (question_id, items_answered, consecutive_correct, completed)
            VALUES (?, '', 0, 0)
        ''', (question_id,))
        session_id = cursor.lastrowid
        conn.commit()

    # Get question details
    cursor.execute('''
        SELECT question_text, category, total_items, required_correct
        FROM multiline_questions
        WHERE id = ?
    ''', (question_id,))
    question = cursor.fetchone()

    # Get all items for this question
    cursor.execute('''
        SELECT mi.id, mi.item_text, ms.weight
        FROM multiline_items mi
        JOIN multiline_stats ms ON mi.id = ms.item_id
        WHERE mi.question_id = ?
    ''', (question_id,))
    all_items = cursor.fetchall()

    # Filter out already-answered items
    items_answered_ids = [int(x) for x in items_answered if x]
    available_items = [item for item in all_items if item['id'] not in items_answered_ids]

    if not available_items:
        # All items answered, mark session as complete
        cursor.execute('''
            UPDATE multiline_sessions
            SET session_end = CURRENT_TIMESTAMP, completed = 1
            WHERE id = ?
        ''', (session_id,))
        conn.commit()
        conn.close()
        return "Question complete! All items answered.", 200

    # Select one correct answer from available items (weighted selection)
    weights = [item['weight'] for item in available_items]
    if sum(weights) == 0:
        correct_item = random.choice(available_items)
    else:
        correct_item = random.choices(available_items, weights=weights, k=1)[0]

    # Select 3 random distractors from OTHER questions in the same category
    cursor.execute('''
        SELECT mi.item_text
        FROM multiline_items mi
        JOIN multiline_questions mq ON mi.question_id = mq.id
        WHERE mq.category = ? AND mi.question_id != ? AND mi.id NOT IN (''' + ','.join(['?'] * len(items_answered_ids)) + ''')
        ORDER BY RANDOM()
        LIMIT 3
    ''', [question['category'], question_id] + items_answered_ids)
    distractors = [row['item_text'] for row in cursor.fetchall()]

    # If we don't have enough distractors, pad with generic ones
    while len(distractors) < 3:
        distractors.append("Ninguna de las anteriores")

    # Combine and shuffle
    options = distractors + [correct_item['item_text']]
    random.shuffle(options)

    conn.close()

    return render_template(
        'multiline.html',
        session_id=session_id,
        question_text=question['question_text'],
        category=question['category'],
        options=options,
        correct_answer=correct_item['item_text'],
        correct_item_id=correct_item['id'],
        consecutive_correct=consecutive_correct,
        required_correct=question['required_correct'],
        total_items=question['total_items'],
        items_answered=len(items_answered_ids)
    )


@app.route('/multiline_answer', methods=['POST'])
def record_multiline_answer():
    """Record the user's answer to a multiline question and update session."""
    data = request.get_json()

    session_id = data.get('session_id')
    item_id = data.get('item_id')
    selected_answer = data.get('selected_answer')
    correct_answer = data.get('correct_answer')

    # Determine if answer is correct
    is_correct = selected_answer == correct_answer

    # Update item statistics
    update_multiline_stats(item_id, is_correct)

    # Update session
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT question_id, items_answered, consecutive_correct, completed
        FROM multiline_sessions
        WHERE id = ?
    ''', (session_id,))
    session = cursor.fetchone()

    if not session:
        conn.close()
        return jsonify({'success': False, 'error': 'Session not found'}), 404

    question_id = session['question_id']
    items_answered = session['items_answered'].split(',') if session['items_answered'] else []
    consecutive_correct = session['consecutive_correct']

    # Add this item to answered list
    items_answered.append(str(item_id))
    items_answered_str = ','.join(items_answered)

    # Get required correct count
    cursor.execute('SELECT required_correct FROM multiline_questions WHERE id = ?', (question_id,))
    required_correct = cursor.fetchone()['required_correct']

    # Update consecutive correct count
    if is_correct:
        consecutive_correct += 1
    else:
        # Wrong answer, mark session as complete
        cursor.execute('''
            UPDATE multiline_sessions
            SET items_answered = ?, consecutive_correct = ?, session_end = CURRENT_TIMESTAMP, completed = 1
            WHERE id = ?
        ''', (items_answered_str, consecutive_correct, session_id))
        conn.commit()
        conn.close()
        return jsonify({
            'success': True,
            'is_correct': False,
            'completed': True,
            'score': consecutive_correct,
            'required': required_correct
        })

    # Check if we've reached the required count
    if consecutive_correct >= required_correct:
        # Success! Mark session as complete
        cursor.execute('''
            UPDATE multiline_sessions
            SET items_answered = ?, consecutive_correct = ?, session_end = CURRENT_TIMESTAMP, completed = 1
            WHERE id = ?
        ''', (items_answered_str, consecutive_correct, session_id))
        conn.commit()
        conn.close()
        return jsonify({
            'success': True,
            'is_correct': True,
            'completed': True,
            'score': consecutive_correct,
            'required': required_correct
        })

    # Continue - update session and continue
    cursor.execute('''
        UPDATE multiline_sessions
        SET items_answered = ?, consecutive_correct = ?
        WHERE id = ?
    ''', (items_answered_str, consecutive_correct, session_id))
    conn.commit()
    conn.close()

    return jsonify({
        'success': True,
        'is_correct': True,
        'completed': False,
        'score': consecutive_correct,
        'required': required_correct
    })


@app.route('/multiline_stats')
def show_multiline_stats():
    """Show multiline item statistics."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT
            mq.category,
            mi.item_text,
            ms.times_shown,
            ms.times_correct,
            ms.success_rate,
            ms.weight,
            ms.is_mastered
        FROM multiline_items mi
        JOIN multiline_questions mq ON mi.question_id = mq.id
        JOIN multiline_stats ms ON mi.id = ms.item_id
        WHERE ms.times_shown > 0
        ORDER BY ms.weight DESC
    ''')

    stats = cursor.fetchall()
    conn.close()

    # Convert to list of dicts for JSON serialization
    stats_list = [{
        'category': stat['category'],
        'item': stat['item_text'][:60] + '...' if len(stat['item_text']) > 60 else stat['item_text'],
        'times_shown': stat['times_shown'],
        'times_correct': stat['times_correct'],
        'success_rate': f"{stat['success_rate']:.1%}",
        'weight': f"{stat['weight']:.2f}",
        'is_mastered': bool(stat['is_mastered'])
    } for stat in stats]

    return jsonify(stats_list)


# --- Synopsis Routes ---
@app.route('/synopsis')
def synopsis():
    """Display the main synopsis introduction page."""
    return render_template('synopsis.html')


@app.route('/synopsis1')
def synopsis1():
    """Display the Ancient Mexico synopsis page."""
    return render_template('synopsis1.html')


@app.route('/synopsis2')
def synopsis2():
    """Display the Colonial Era to 1760 synopsis page."""
    return render_template('synopsis2.html')


@app.route('/synopsis3')
def synopsis3():
    """Display the Bourbon Reforms and Independence synopsis page."""
    return render_template('synopsis3.html')


@app.route('/synopsis4')
def synopsis4():
    """Display the Independence to Consolidation synopsis page."""
    return render_template('synopsis4.html')


@app.route('/synopsis5')
def synopsis5():
    """Display the Porfiriato synopsis page."""
    return render_template('synopsis5.html')


@app.route('/synopsis6')
def synopsis6():
    """Display the Revolution synopsis page."""
    return render_template('synopsis6.html')


@app.route('/synopsis7')
def synopsis7():
    """Display the Last Stretch synopsis page."""
    return render_template('synopsis7.html')


# --- Main execution block ---
if __name__ == '__main__':
    # Runs the Flask app. 'debug=True' means the server will auto-reload
    # when you save changes to the file, which is great for development.
    app.run(debug=True, use_reloader=False)
