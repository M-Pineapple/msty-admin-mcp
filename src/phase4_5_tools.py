"""
Utility functions for Phase 4 (Intelligence Layer) and Phase 5 (Tiered AI Workflow)

Provides:
- Calibration prompts and quality rubrics
- Response evaluation heuristics
- Metrics database operations
- Handoff trigger tracking
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

# Calibration test prompts by category
CALIBRATION_PROMPTS = {
    "reasoning": [
        "A company has 100 employees. Each employee works 40 hours per week. If the company pays $50 per hour on average, what is the weekly payroll cost? Show your working.",
        "If all squares are rectangles, and all rectangles are quadrilaterals, are all squares quadrilaterals? Explain your logic.",
    ],
    "coding": [
        "Write a Python function that takes a list of numbers and returns the sum of all even numbers.",
        "How would you implement a simple LRU (Least Recently Used) cache in Python?",
    ],
    "writing": [
        "Write a professional email requesting a project deadline extension due to unforeseen circumstances.",
        "Create a compelling product description for a hypothetical AI-powered note-taking app.",
    ],
    "analysis": [
        "What are the key factors that would influence the adoption rate of a new technology in enterprise settings?",
        "Analyze the trade-offs between speed and accuracy in machine learning model selection.",
    ],
    "creative": [
        "Generate a creative product name and slogan for an eco-friendly water bottle startup.",
        "Write a short creative story (2-3 paragraphs) about an unexpected discovery.",
    ],
}

# Quality evaluation rubric
QUALITY_RUBRIC = {
    "accuracy": {
        "description": "Factual correctness and absence of errors",
        "weight": 0.25,
    },
    "completeness": {
        "description": "Coverage of all relevant aspects",
        "weight": 0.25,
    },
    "clarity": {
        "description": "Clarity of expression and structure",
        "weight": 0.20,
    },
    "relevance": {
        "description": "Directly addresses the prompt",
        "weight": 0.15,
    },
    "formatting": {
        "description": "Proper formatting and presentation",
        "weight": 0.15,
    },
}


def get_metrics_db_path() -> Path:
    """Get path to metrics database."""
    return Path.home() / ".msty-admin" / "msty_admin_metrics.db"


def init_metrics_db():
    """Initialize metrics database with required tables."""
    db_path = get_metrics_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Model metrics table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_metrics (
            id INTEGER PRIMARY KEY,
            model_id TEXT NOT NULL,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            latency_seconds REAL,
            success BOOLEAN,
            use_case TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Calibration tests table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calibration_tests (
            id INTEGER PRIMARY KEY,
            test_id TEXT UNIQUE,
            model_id TEXT NOT NULL,
            prompt_category TEXT,
            prompt TEXT,
            local_response TEXT,
            quality_score REAL,
            evaluation_notes TEXT,
            tokens_per_second REAL,
            passed BOOLEAN,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Handoff triggers table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS handoff_triggers (
            id INTEGER PRIMARY KEY,
            pattern_type TEXT,
            pattern_description TEXT,
            confidence REAL,
            is_active BOOLEAN DEFAULT 1,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Conversation analytics table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversation_analytics (
            id INTEGER PRIMARY KEY,
            model_id TEXT,
            total_turns INTEGER,
            avg_response_time REAL,
            error_count INTEGER,
            conversation_quality REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()


def record_model_metric(
    model_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_seconds: float,
    success: bool,
    use_case: str = "general"
):
    """Record a model performance metric."""
    db_path = get_metrics_db_path()
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO model_metrics
        (model_id, prompt_tokens, completion_tokens, latency_seconds, success, use_case)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (model_id, prompt_tokens, completion_tokens, latency_seconds, success, use_case))
    
    conn.commit()
    conn.close()


def get_model_metrics_summary(model_id: Optional[str] = None, days: int = 7) -> Dict[str, Any]:
    """Get summary metrics for a model over a time period."""
    db_path = get_metrics_db_path()
    if not db_path.exists():
        return {}
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = """
        SELECT
            model_id,
            COUNT(*) as request_count,
            AVG(latency_seconds) as avg_latency,
            AVG(prompt_tokens) as avg_prompt_tokens,
            AVG(completion_tokens) as avg_completion_tokens,
            SUM(CASE WHEN success THEN 1 ELSE 0 END) * 1.0 / COUNT(*) as success_rate
        FROM model_metrics
        WHERE datetime(timestamp) > datetime('now', '-' || ? || ' days')
    """
    
    params = [days]
    if model_id:
        query += " AND model_id = ?"
        params.append(model_id)
    
    query += " GROUP BY model_id"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def save_calibration_result(
    test_id: str,
    model_id: str,
    prompt_category: str,
    prompt: str,
    local_response: str,
    quality_score: float,
    evaluation_notes: str,
    tokens_per_second: float,
    passed: bool
):
    """Save a calibration test result."""
    db_path = get_metrics_db_path()
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO calibration_tests
        (test_id, model_id, prompt_category, prompt, local_response, quality_score,
         evaluation_notes, tokens_per_second, passed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (test_id, model_id, prompt_category, prompt, local_response, quality_score,
           evaluation_notes, tokens_per_second, passed))
    
    conn.commit()
    conn.close()


def get_calibration_results(
    model_id: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get calibration test results."""
    db_path = get_metrics_db_path()
    if not db_path.exists():
        return []
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = "SELECT * FROM calibration_tests"
    params = []
    
    if model_id:
        query += " WHERE model_id = ?"
        params.append(model_id)
    
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def record_handoff_trigger(
    pattern_type: str,
    pattern_description: str,
    confidence: float
):
    """Record a handoff trigger pattern."""
    db_path = get_metrics_db_path()
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO handoff_triggers
        (pattern_type, pattern_description, confidence)
        VALUES (?, ?, ?)
    """, (pattern_type, pattern_description, confidence))
    
    conn.commit()
    conn.close()


def get_handoff_triggers(active_only: bool = True) -> List[Dict[str, Any]]:
    """Get recorded handoff trigger patterns."""
    db_path = get_metrics_db_path()
    if not db_path.exists():
        return []
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = "SELECT * FROM handoff_triggers"
    params = []
    
    if active_only:
        query += " WHERE is_active = 1"
    
    query += " ORDER BY confidence DESC"
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def evaluate_response_heuristic(
    prompt: str,
    response: str,
    category: str = "general"
) -> Dict[str, Any]:
    """Evaluate response quality using heuristics.
    
    Returns score (0.0-1.0), criteria scores, notes, and pass status.
    """
    criteria_scores = {}
    
    # Accuracy: Check for common error patterns
    accuracy_score = 0.7  # Baseline
    if len(response) < 10:
        accuracy_score = 0.3  # Too short
    elif "i don't know" in response.lower() or "i cannot" in response.lower():
        accuracy_score = 0.5  # Uncertain
    elif "error" in response.lower() or "sorry" in response.lower():
        accuracy_score = 0.6  # Acknowledges issues
    
    # Completeness: Check response length and structure
    response_length = len(response.split())
    if response_length < 10:
        completeness_score = 0.4
    elif response_length < 50:
        completeness_score = 0.6
    elif response_length < 200:
        completeness_score = 0.8
    else:
        completeness_score = 0.85
    
    # Clarity: Check for formatting and structure
    clarity_score = 0.7  # Baseline
    if "\n" in response:
        clarity_score += 0.1  # Has structure
    if response.count(".") >= 3:
        clarity_score += 0.05  # Multiple sentences
    clarity_score = min(clarity_score, 1.0)
    
    # Relevance: Simple check for prompt keywords
    prompt_keywords = set(w.lower() for w in prompt.split() if len(w) > 3)
    response_words = set(w.lower() for w in response.split())
    overlap = len(prompt_keywords & response_words)
    relevance_score = min(overlap / max(len(prompt_keywords), 1) * 0.8 + 0.2, 1.0)
    
    # Formatting: Check for proper punctuation
    formatting_score = 0.5
    if response.endswith(".") or response.endswith("!") or response.endswith("?"):
        formatting_score += 0.3
    if response[0].isupper():
        formatting_score += 0.2
    
    criteria_scores["accuracy"] = accuracy_score
    criteria_scores["completeness"] = completeness_score
    criteria_scores["clarity"] = clarity_score
    criteria_scores["relevance"] = relevance_score
    criteria_scores["formatting"] = formatting_score
    
    # Calculate weighted score
    weighted_score = sum(
        criteria_scores[criterion] * QUALITY_RUBRIC[criterion]["weight"]
        for criterion in criteria_scores
    )
    
    return {
        "score": min(weighted_score, 1.0),
        "criteria_scores": criteria_scores,
        "passed": weighted_score >= 0.6,
        "notes": f"Response length: {response_length} words. Accuracy: {accuracy_score:.2f}, Completeness: {completeness_score:.2f}, Clarity: {clarity_score:.2f}, Relevance: {relevance_score:.2f}, Formatting: {formatting_score:.2f}"
    }
