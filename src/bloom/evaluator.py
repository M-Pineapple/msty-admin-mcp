"""
Bloom Evaluator — Orchestrates behavioral evaluation of local Ollama models

Integrates Anthropic's Bloom framework for testing problematic behaviors.
Requires Anthropic API key for judge model.
"""

import os
import json
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path

from .ollama_adapter import OllamaModelAdapter
from .cv_behaviors import CUSTOM_BEHAVIORS, QUALITY_THRESHOLDS, HANDOFF_TRIGGERS


@dataclass
class EvaluationConfig:
    """Configuration for a Bloom evaluation run."""
    behavior: str                               # Behavior to evaluate
    target_model: str                          # Ollama model to evaluate
    task_category: Optional[str] = None        # Task category for thresholds
    total_evals: int = 3                       # Number of evaluation scenarios
    max_turns: int = 2                         # Max turns per evaluation
    judge_model: str = "claude-sonnet-4"       # Judge model for evaluation
    temperature: float = 0.7                   # Judge model temperature
    custom_seed: Optional[Dict[str, Any]] = None  # Custom seed configuration


@dataclass
class EvaluationResult:
    """Result of a Bloom evaluation."""
    behavior: str
    model: str
    task_category: Optional[str]
    quality_score: float                       # 0.0-1.0
    passed: bool                               # Score >= threshold
    timestamp: str
    evaluation_details: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class BloomEvaluator:
    """
    Orchestrates Bloom behavioral evaluation of local Ollama models.
    
    Requires:
    - Anthropic API key (ANTHROPIC_API_KEY environment variable)
    - Bloom framework installed locally
    - Target Ollama model running
    """
    
    def __init__(
        self,
        ollama_host: str = "http://localhost:11434",
        msty_host: Optional[str] = None,
        bloom_path: Optional[str] = None,
    ):
        """Initialize BloomEvaluator.
        
        Args:
            ollama_host: Ollama API endpoint
            msty_host: Optional Msty service host
            bloom_path: Path to Bloom framework (auto-detected if None)
        """
        self.adapter = OllamaModelAdapter(ollama_host, msty_host)
        self.bloom_path = bloom_path or self._find_bloom_path()
        self.evaluation_history: List[EvaluationResult] = []
        
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ValueError("ANTHROPIC_API_KEY environment variable required for Bloom")
    
    def _find_bloom_path(self) -> Optional[str]:
        """Locate Bloom framework installation."""
        candidates = [
            Path.home() / "bloom",
            Path.home() / "Github" / "bloom",
            Path("/opt/bloom"),
        ]
        
        for path in candidates:
            if path.exists() and (path / "run.py").exists():
                return str(path)
        
        return None
    
    async def evaluate(
        self,
        model: str,
        behavior: str,
        task_category: Optional[str] = None,
        total_evals: int = 3,
        max_turns: int = 2,
    ) -> EvaluationResult:
        """Run a Bloom evaluation on the specified model.
        
        Args:
            model: Ollama model name
            behavior: Behavior to evaluate
            task_category: Task category for threshold checking
            total_evals: Number of evaluation scenarios
            max_turns: Maximum conversation turns
            
        Returns:
            EvaluationResult with quality score
        """
        # Validate inputs
        if not self.bloom_path:
            return EvaluationResult(
                behavior=behavior,
                model=model,
                task_category=task_category,
                quality_score=0.0,
                passed=False,
                timestamp=datetime.now().isoformat(),
                recommendations=["Bloom framework not found. Install from GitHub: https://github.com/anthropics/bloom"]
            )
        
        validation = self.adapter.validate_model_for_bloom(model)
        if not validation["valid"]:
            return EvaluationResult(
                behavior=behavior,
                model=model,
                task_category=task_category,
                quality_score=0.0,
                passed=False,
                timestamp=datetime.now().isoformat(),
                recommendations=validation["errors"]
            )
        
        # Generate seed configuration
        seed_config = self._generate_seed_config(
            model, behavior, task_category, total_evals, max_turns
        )
        
        # Run Bloom pipeline
        result = await self._run_bloom_pipeline(seed_config)
        
        # Process results
        return self._process_results(result, model, behavior, task_category)
    
    def _generate_seed_config(self, model: str, behavior: str, task_category: Optional[str],
                              total_evals: int, max_turns: int) -> Dict[str, Any]:
        """Generate YAML seed configuration for Bloom."""
        return {
            "behaviors": [behavior],
            "target_model": {
                "model": self.adapter.get_litellm_model_id(model),
                "temperature": 0.7,
            },
            "judge_model": "claude-sonnet-4",
            "num_evaluations": total_evals,
            "max_turns_per_evaluation": max_turns,
            "task_category": task_category or "general_tasks",
        }
    
    async def _run_bloom_pipeline(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Execute Bloom evaluation pipeline."""
        try:
            # Write config to temporary file
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
                import yaml
                yaml.dump(config, f)
                config_path = f.name
            
            # Run Bloom
            result = subprocess.run(
                ["python", str(Path(self.bloom_path) / "run.py"), config_path],
                capture_output=True,
                text=True,
                timeout=300,
                env={**os.environ, "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")}
            )
            
            # Parse results
            output = result.stdout
            # Bloom outputs JSON results
            results = json.loads(output) if output else {}
            
            return results
        except Exception as e:
            return {"error": str(e)}
    
    def _process_results(self, bloom_output: Dict[str, Any], model: str, behavior: str,
                        task_category: Optional[str]) -> EvaluationResult:
        """Process Bloom pipeline results into EvaluationResult."""
        # Extract quality score from Bloom output
        quality_score = bloom_output.get("overall_score", 0.5)
        
        # Check against threshold
        threshold = QUALITY_THRESHOLDS.get(task_category or "general_tasks", {})
        min_score = threshold.get("min_score", 0.5)
        passed = quality_score >= min_score
        
        # Generate recommendations
        recommendations = []
        if not passed:
            recommendations.append(f"Score {quality_score:.2f} below minimum {min_score:.2f}")
            if quality_score < 0.4:
                recommendations.append("Consider using a larger model")
        
        if bloom_output.get("error"):
            recommendations.append(f"Evaluation error: {bloom_output['error']}")
        
        return EvaluationResult(
            behavior=behavior,
            model=model,
            task_category=task_category,
            quality_score=quality_score,
            passed=passed,
            timestamp=datetime.now().isoformat(),
            evaluation_details=bloom_output,
            recommendations=recommendations
        )
    
    def get_evaluation_history(self, model: Optional[str] = None,
                              behavior: Optional[str] = None,
                              limit: int = 10) -> List[EvaluationResult]:
        """Get historical evaluation results."""
        results = self.evaluation_history
        
        if model:
            results = [r for r in results if r.model == model]
        if behavior:
            results = [r for r in results if r.behavior == behavior]
        
        return results[-limit:]
    
    def should_handoff_to_claude(self, model: str,
                                task_category: str) -> Dict[str, Any]:
        """Determine if model should hand off task to Claude."""
        # Get recent evaluations for this model/category
        history = self.get_evaluation_history(model=model, limit=10)
        
        if not history:
            return {
                "should_handoff": False,
                "confidence": 0.3,
                "reason": "No evaluation history. Run bloom_evaluate_model first.",
            }
        
        # Calculate average score
        scores = [r.quality_score for r in history if r.task_category == task_category]
        if not scores:
            scores = [r.quality_score for r in history]
        
        avg_score = sum(scores) / len(scores) if scores else 0.5
        
        # Check against thresholds
        threshold = QUALITY_THRESHOLDS.get(task_category, {})
        min_score = threshold.get("min_score", 0.5)
        
        if avg_score < min_score:
            return {
                "should_handoff": True,
                "confidence": min(1.0, 1.0 - (avg_score / min_score)),
                "reason": f"Average score {avg_score:.2f} below minimum {min_score:.2f}",
                "recent_scores": scores[-3:],
            }
        else:
            return {
                "should_handoff": False,
                "confidence": min(avg_score, 1.0),
                "reason": f"Score {avg_score:.2f} meets minimum requirements",
                "recent_scores": scores[-3:],
            }
