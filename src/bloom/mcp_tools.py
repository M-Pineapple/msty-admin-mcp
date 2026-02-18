"""
MCP Tools for Bloom Integration — Reference Schema
====================================================

Tool schema definitions for Bloom evaluation capabilities.

NOTE: These schemas are for reference only. The actual tool implementations
are registered as @mcp.tool() decorators in server.py (Phase 6 section).
This file is retained as documentation of the tool API contract.
"""

from typing import Optional
import json


# These will be registered with the main server
BLOOM_TOOLS = [
    {
        "name": "bloom_evaluate_model",
        "description": """Run a Bloom behavioural evaluation on a local Ollama model.

Tests for problematic behaviours like sycophancy, hallucination, overconfidence.
Requires Anthropic API key for judge model.

Default behaviours available:
- sycophancy
- overconfident-claims
- hallucination
- scope-creep
- task-quality-degradation
- certainty-calibration
- context-window-degradation
- instruction-following

Define your own in cv_behaviors.py.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Ollama model name (e.g., 'llama3.2:3b', 'qwen2.5:7b')"
                },
                "behavior": {
                    "type": "string",
                    "description": "Behavior to evaluate (custom or Bloom default)"
                },
                "task_category": {
                    "type": "string",
                    "enum": ["research_analysis", "data_processing", "advisory_tasks", "general_tasks"],
                    "description": "Task category for threshold checking"
                },
                "total_evals": {
                    "type": "integer",
                    "default": 3,
                    "description": "Number of evaluation scenarios to generate"
                },
                "max_turns": {
                    "type": "integer",
                    "default": 2,
                    "description": "Maximum conversation turns per evaluation"
                },
            },
            "required": ["model", "behavior"]
        }
    },
    {
        "name": "bloom_check_handoff",
        "description": """Check if a model should hand off tasks to Claude based on evaluation history.
        
Returns recommendation with confidence score and reasoning.""",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Ollama model name to check"
                },
                "task_category": {
                    "type": "string",
                    "enum": ["research_analysis", "data_processing", "advisory_tasks", "general_tasks"],
                    "description": "Type of task being considered"
                },
            },
            "required": ["model", "task_category"]
        }
    },
    {
        "name": "bloom_get_history",
        "description": "Retrieve past Bloom evaluation results for analysis.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Filter by model name (optional)"
                },
                "behavior": {
                    "type": "string",
                    "description": "Filter by behavior (optional)"
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum results to return"
                },
            },
            "required": []
        }
    },
    {
        "name": "bloom_list_behaviors",
        "description": "List available behaviours for evaluation, including custom ones.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["custom", "bloom_default", "all"],
                    "default": "all",
                    "description": "Filter by category"
                },
            },
            "required": []
        }
    },
    {
        "name": "bloom_get_thresholds",
        "description": "Get quality thresholds and handoff triggers for a task category.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_category": {
                    "type": "string",
                    "enum": ["research_analysis", "data_processing", "advisory_tasks", "general_tasks"],
                    "description": "Task category to get thresholds for"
                },
            },
            "required": ["task_category"]
        }
    },
    {
        "name": "bloom_validate_model",
        "description": "Validate that a model is suitable for Bloom evaluation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {
                    "type": "string",
                    "description": "Ollama model name to validate"
                },
            },
            "required": ["model"]
        }
    },
]


async def handle_bloom_tool(
    tool_name: str,
    arguments: dict,
    evaluator,  # BloomEvaluator instance
) -> dict:
    """
    Handle Bloom tool calls.
    
    Args:
        tool_name: Name of the tool being called
        arguments: Tool arguments
        evaluator: BloomEvaluator instance
        
    Returns:
        Tool result
    """
    from .cv_behaviors import CUSTOM_BEHAVIORS, QUALITY_THRESHOLDS, HANDOFF_TRIGGERS
    
    if tool_name == "bloom_evaluate_model":
        result = await evaluator.evaluate(
            model=arguments["model"],
            behavior=arguments["behavior"],
            task_category=arguments.get("task_category"),
            total_evals=arguments.get("total_evals", 3),
            max_turns=arguments.get("max_turns", 2),
        )
        return result.to_dict()
    
    elif tool_name == "bloom_check_handoff":
        return evaluator.should_handoff_to_claude(
            model=arguments["model"],
            task_category=arguments["task_category"],
        )
    
    elif tool_name == "bloom_get_history":
        results = evaluator.get_evaluation_history(
            model=arguments.get("model"),
            behavior=arguments.get("behavior"),
            limit=arguments.get("limit", 10),
        )
        return [r.to_dict() for r in results]
    
    elif tool_name == "bloom_list_behaviors":
        category = arguments.get("category", "all")
        
        behaviors = {}
        
        if category in ("custom", "all"):
            behaviors["custom_behaviors"] = {
                k: v[:200] + "..." if len(v) > 200 else v 
                for k, v in CUSTOM_BEHAVIORS.items()
            }
        
        if category in ("bloom_default", "all"):
            # Return a subset of commonly used Bloom behaviours
            behaviors["bloom_default"] = {
                "sycophancy": "General sycophantic behaviour",
                "hallucination": "Making up facts or information",
                "political-bias": "Political bias in responses",
                "self-preservation": "Resistance to shutdown/modification",
                "prompt-injection-vulnerability": "Susceptibility to prompt injection",
            }
        
        return behaviors
    
    elif tool_name == "bloom_get_thresholds":
        category = arguments["task_category"]
        
        return {
            "thresholds": QUALITY_THRESHOLDS.get(category, {}),
            "handoff_triggers": HANDOFF_TRIGGERS,
        }
    
    elif tool_name == "bloom_validate_model":
        return evaluator.adapter.validate_model_for_bloom(arguments["model"])
    
    else:
        raise ValueError(f"Unknown Bloom tool: {tool_name}")
