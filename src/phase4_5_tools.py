"""
Phase 4 & 5 Tools for Msty Admin MCP

Phase 4: Intelligence Layer
- get_model_performance_metrics
- analyse_conversation_patterns
- compare_model_responses
- optimise_knowledge_stacks
- suggest_persona_improvements

Phase 5: Tiered AI Workflow
- run_calibration_test
- evaluate_response_quality
- identify_handoff_triggers
- get_calibration_history

Created by Pineapple 🍍 AI Administration System
"""

import json
import time
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Dict, List

# =============================================================================
# Constants
# =============================================================================

METRICS_DB_NAME = "msty_admin_metrics.db"

# Calibration test prompts by category
CALIBRATION_PROMPTS = {
    "reasoning": [
        "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. How much does the ball cost? Explain your reasoning step by step.",
        "If it takes 5 machines 5 minutes to make 5 widgets, how long would it take 100 machines to make 100 widgets? Show your work.",
    ],
    "coding": [
        "Write a Python function that finds the longest palindromic substring in a given string. Include comments explaining your approach.",
        "Implement a simple LRU cache in Python with O(1) get and put operations.",
    ],
    "writing": [
        "Write a professional email declining a meeting invitation due to a scheduling conflict. Keep it concise and courteous.",
        "Summarise the key benefits of renewable energy in 100 words or less, using British English spelling.",
    ],
    "analysis": [
        "What are the potential risks and benefits of a company moving from on-premises infrastructure to cloud computing? Provide a balanced analysis.",
        "Compare and contrast microservices and monolithic architecture. When would you recommend each approach?",
    ],
    "creative": [
        "Write a short story opening (100 words) that hooks the reader immediately.",
        "Create a haiku about artificial intelligence.",
    ]
}

# Quality scoring rubric
QUALITY_RUBRIC = {
    "accuracy": "Response is factually correct and logically sound",
    "completeness": "Response addresses all aspects of the prompt",
    "clarity": "Response is clear, well-organised, and easy to understand",
    "relevance": "Response stays on topic and provides useful information",
    "formatting": "Response uses appropriate formatting and structure"
}


def get_metrics_db_path() -> Path:
    """Get path to the metrics database"""
    metrics_dir = Path.home() / ".msty-admin"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    return metrics_dir / METRICS_DB_NAME


def init_metrics_db():
    """Initialise the metrics database with required tables"""
    db_path = get_metrics_db_path()
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Model performance metrics
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id TEXT NOT NULL,
            request_timestamp TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            latency_seconds REAL DEFAULT 0.0,
            tokens_per_second REAL DEFAULT 0.0,
            success INTEGER DEFAULT 1,
            error_message TEXT,
            use_case TEXT,
            UNIQUE(model_id, request_timestamp)
        )
    """)
    
    # Calibration tests
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS calibration_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_id TEXT UNIQUE NOT NULL,
            model_id TEXT NOT NULL,
            prompt_category TEXT NOT NULL,
            prompt TEXT NOT NULL,
            local_response TEXT,
            quality_score REAL DEFAULT 0.0,
            evaluation_notes TEXT,
            tokens_per_second REAL DEFAULT 0.0,
            timestamp TEXT NOT NULL,
            passed INTEGER DEFAULT 0
        )
    """)
    
    # Handoff triggers
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS handoff_triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pattern_type TEXT NOT NULL,
            pattern_description TEXT NOT NULL,
            trigger_count INTEGER DEFAULT 1,
            last_triggered TEXT,
            confidence REAL DEFAULT 0.5,
            active INTEGER DEFAULT 1
        )
    """)
    
    # Conversation analytics
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversation_analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            model_id TEXT,
            session_count INTEGER DEFAULT 0,
            message_count INTEGER DEFAULT 0,
            avg_session_length_minutes REAL DEFAULT 0.0,
            avg_messages_per_session REAL DEFAULT 0.0,
            primary_use_case TEXT,
            UNIQUE(date, model_id)
        )
    """)
    
    conn.commit()
    conn.close()
    return str(db_path)


def record_model_metric(
    model_id: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_seconds: float = 0.0,
    success: bool = True,
    error_message: str = None,
    use_case: str = None
):
    """Record a model performance metric"""
    db_path = get_metrics_db_path()
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    total_tokens = prompt_tokens + completion_tokens
    tokens_per_second = completion_tokens / max(latency_seconds, 0.1) if completion_tokens > 0 else 0.0
    
    try:
        cursor.execute("""
            INSERT INTO model_metrics 
            (model_id, request_timestamp, prompt_tokens, completion_tokens, total_tokens,
             latency_seconds, tokens_per_second, success, error_message, use_case)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            model_id,
            datetime.now().isoformat(),
            prompt_tokens,
            completion_tokens,
            total_tokens,
            latency_seconds,
            tokens_per_second,
            1 if success else 0,
            error_message,
            use_case
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        pass  # Duplicate entry
    finally:
        conn.close()


def get_model_metrics_summary(model_id: str = None, days: int = 30) -> Dict[str, Any]:
    """Get aggregated metrics for models"""
    db_path = get_metrics_db_path()
    if not db_path.exists():
        return {"error": "Metrics database not initialised"}
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
    
    if model_id:
        cursor.execute("""
            SELECT 
                model_id,
                COUNT(*) as total_requests,
                SUM(total_tokens) as total_tokens,
                AVG(tokens_per_second) as avg_tokens_per_second,
                AVG(latency_seconds) as avg_latency_seconds,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as error_count,
                MAX(request_timestamp) as last_used
            FROM model_metrics
            WHERE model_id = ? AND request_timestamp > ?
            GROUP BY model_id
        """, (model_id, cutoff_date))
    else:
        cursor.execute("""
            SELECT 
                model_id,
                COUNT(*) as total_requests,
                SUM(total_tokens) as total_tokens,
                AVG(tokens_per_second) as avg_tokens_per_second,
                AVG(latency_seconds) as avg_latency_seconds,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as error_count,
                MAX(request_timestamp) as last_used
            FROM model_metrics
            WHERE request_timestamp > ?
            GROUP BY model_id
            ORDER BY total_requests DESC
        """, (cutoff_date,))
    
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return {
        "period_days": days,
        "models": results,
        "model_count": len(results)
    }


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
    """Save a calibration test result"""
    db_path = get_metrics_db_path()
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO calibration_tests
            (test_id, model_id, prompt_category, prompt, local_response, 
             quality_score, evaluation_notes, tokens_per_second, timestamp, passed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            test_id,
            model_id,
            prompt_category,
            prompt,
            local_response,
            quality_score,
            evaluation_notes,
            tokens_per_second,
            datetime.now().isoformat(),
            1 if passed else 0
        ))
        conn.commit()
    finally:
        conn.close()


def get_calibration_results(model_id: str = None, limit: int = 50) -> List[Dict]:
    """Get calibration test results"""
    db_path = get_metrics_db_path()
    if not db_path.exists():
        return []
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if model_id:
        cursor.execute("""
            SELECT * FROM calibration_tests
            WHERE model_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (model_id, limit))
    else:
        cursor.execute("""
            SELECT * FROM calibration_tests
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
    
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def record_handoff_trigger(pattern_type: str, pattern_description: str, confidence: float = 0.5):
    """Record or update a handoff trigger pattern"""
    db_path = get_metrics_db_path()
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    
    # Check if pattern exists
    cursor.execute("""
        SELECT id, trigger_count FROM handoff_triggers
        WHERE pattern_type = ? AND pattern_description = ?
    """, (pattern_type, pattern_description))
    
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute("""
            UPDATE handoff_triggers
            SET trigger_count = trigger_count + 1,
                last_triggered = ?,
                confidence = ?
            WHERE id = ?
        """, (datetime.now().isoformat(), confidence, existing[0]))
    else:
        cursor.execute("""
            INSERT INTO handoff_triggers
            (pattern_type, pattern_description, trigger_count, last_triggered, confidence)
            VALUES (?, ?, 1, ?, ?)
        """, (pattern_type, pattern_description, datetime.now().isoformat(), confidence))
    
    conn.commit()
    conn.close()


def get_handoff_triggers(active_only: bool = True) -> List[Dict]:
    """Get recorded handoff triggers"""
    db_path = get_metrics_db_path()
    if not db_path.exists():
        return []
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if active_only:
        cursor.execute("""
            SELECT * FROM handoff_triggers
            WHERE active = 1
            ORDER BY trigger_count DESC
        """)
    else:
        cursor.execute("""
            SELECT * FROM handoff_triggers
            ORDER BY trigger_count DESC
        """)
    
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


def evaluate_response_heuristic(
    prompt: str,
    response: str,
    category: str
) -> Dict[str, Any]:
    """
    Evaluate response quality using heuristics.
    
    Returns a score from 0.0 to 1.0 with evaluation notes.
    """
    evaluation = {
        "score": 0.0,
        "notes": [],
        "criteria_scores": {}
    }
    
    if not response or len(response.strip()) < 10:
        evaluation["notes"].append("Response too short or empty")
        return evaluation
    
    # Length appropriateness (not too short, not excessive)
    response_len = len(response)
    if response_len < 50:
        evaluation["criteria_scores"]["length"] = 0.3
        evaluation["notes"].append("Response may be too brief")
    elif response_len < 100:
        evaluation["criteria_scores"]["length"] = 0.6
    elif response_len < 2000:
        evaluation["criteria_scores"]["length"] = 1.0
    else:
        evaluation["criteria_scores"]["length"] = 0.8
        evaluation["notes"].append("Response may be overly verbose")
    
    # Formatting quality
    has_structure = any(marker in response for marker in ["\n\n", "1.", "- ", "* ", "##"])
    if has_structure:
        evaluation["criteria_scores"]["formatting"] = 0.9
    else:
        evaluation["criteria_scores"]["formatting"] = 0.6
    
    # Relevance (basic keyword matching)
    prompt_keywords = set(prompt.lower().split())
    response_keywords = set(response.lower().split())
    overlap = len(prompt_keywords & response_keywords)
    relevance_score = min(overlap / max(len(prompt_keywords), 1), 1.0)
    evaluation["criteria_scores"]["relevance"] = relevance_score * 0.8 + 0.2
    
    # Category-specific checks
    if category == "coding":
        has_code = "```" in response or "def " in response or "function" in response
        evaluation["criteria_scores"]["code_presence"] = 1.0 if has_code else 0.4
        if not has_code:
            evaluation["notes"].append("Expected code block not found")
    
    elif category == "reasoning":
        has_reasoning = any(word in response.lower() for word in 
                          ["because", "therefore", "since", "step", "first", "then"])
        evaluation["criteria_scores"]["reasoning_markers"] = 1.0 if has_reasoning else 0.5
        if not has_reasoning:
            evaluation["notes"].append("Limited reasoning markers found")
    
    elif category == "writing":
        # Check for British English indicators (if applicable)
        british_markers = ["colour", "organise", "centre", "programme", "behaviour"]
        has_british = any(word in response.lower() for word in british_markers)
        # Not penalising if not British, just noting
        if has_british:
            evaluation["notes"].append("British English detected ✓")
    
    # Calculate overall score
    scores = list(evaluation["criteria_scores"].values())
    evaluation["score"] = sum(scores) / len(scores) if scores else 0.0
    
    # Determine pass/fail
    evaluation["passed"] = evaluation["score"] >= 0.6
    
    return evaluation


# Export functions for use in main server
__all__ = [
    'init_metrics_db',
    'record_model_metric',
    'get_model_metrics_summary',
    'save_calibration_result',
    'get_calibration_results',
    'record_handoff_trigger',
    'get_handoff_triggers',
    'evaluate_response_heuristic',
    'CALIBRATION_PROMPTS',
    'QUALITY_RUBRIC'
]
