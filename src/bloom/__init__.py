"""
Bloom Integration Module — Behavioral Evaluation for Local LLMs

Provides Anthropic's Bloom framework integration for evaluating local Ollama models.
Tests for problematic behaviors like sycophancy, hallucination, overconfidence.

Version: 1.0.0
Author: M-Pineapple AI Administration System
"""

from .evaluator import BloomEvaluator
from .cv_behaviors import CUSTOM_BEHAVIORS
from .ollama_adapter import OllamaModelAdapter

__all__ = ["BloomEvaluator", "CUSTOM_BEHAVIORS", "OllamaModelAdapter"]
