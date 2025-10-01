#!/usr/bin/env python3
"""
Shared weight calculation library for the Mexico Study Guide quiz system.

This module provides a consistent implementation of the adaptive learning
weight calculation algorithm used throughout the application.
"""

# Configuration constants (must match app.py)
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
    Calculate weight using the current rolling window algorithm.

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

    # Build confidence based on recent attempts (rolling window)
    confidence = min(recent_attempts_count / CONFIDENCE_THRESHOLD, 1.0)

    # Cap success rate for weight calculation
    effective_success_rate = min(rolling_success_rate, MAX_SUCCESS_RATE_CAP)

    # Very aggressive exponential weighting: poor performance = much higher weight
    # Adjusted to make 100% success rate close to 1.0 baseline
    base_weight = 0.2 + 25.0 * (5.0 ** (1 - effective_success_rate) - 1.0)

    # Apply confidence multiplier: less confident = higher weight
    # Reduced multiplier to get 100% success closer to 1.0
    confidence_multiplier = 1.0 + (1 - confidence) * 2.5

    weight = base_weight * confidence_multiplier

    # Cap at reasonable maximum (should not exceed unseen question weight)
    weight = min(weight, 25.0)

    return weight