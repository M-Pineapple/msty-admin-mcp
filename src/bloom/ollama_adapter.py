"""
Ollama Model Adapter for Bloom/LiteLLM Integration
===================================================

Provides the bridge between Bloom's LiteLLM-based pipeline and local Ollama models.
LiteLLM supports OpenAI-compatible endpoints, which Ollama exposes.
"""

import os
from typing import Optional
from dataclasses import dataclass


@dataclass
class OllamaModel:
    """Represents a local Ollama model for Bloom evaluation."""
    name: str                    # Model name in Ollama (e.g., "llama3.2:3b")
    litellm_id: str             # LiteLLM identifier
    display_name: str           # Human-readable name
    context_length: int         # Max context window
    supports_tools: bool        # Whether model supports function calling
    
    @classmethod
    def from_ollama_info(cls, model_info: dict) -> "OllamaModel":
        """Create from Ollama model info response."""
        name = model_info.get("name", "")
        
        # Estimate context length from model details
        details = model_info.get("details", {})
        context = details.get("context_length", 4096)
        
        # Check for tool support (usually larger models)
        param_size = details.get("parameter_size", "")
        supports_tools = "70b" in name.lower() or "405b" in name.lower()
        
        return cls(
            name=name,
            litellm_id=f"ollama/{name}",
            display_name=name.replace(":", " ").title(),
            context_length=context,
            supports_tools=supports_tools,
        )


class OllamaModelAdapter:
    """
    Adapts local Ollama models for use with Bloom's evaluation pipeline.
    
    Bloom uses LiteLLM which supports the 'ollama/' prefix for local models.
    This adapter helps configure and validate local models for evaluation.
    """
    
    def __init__(
        self,
        ollama_host: str = "http://localhost:11434",
        msty_host: Optional[str] = None,
    ):
        """
        Initialise the adapter.

        Args:
            ollama_host: Ollama API endpoint (default localhost:11434)
            msty_host: Optional Msty service host for proxied access
        """
        self.ollama_host = ollama_host
        self.msty_host = msty_host or os.environ.get("MSTY_HOST")

        # Set the base URL for LiteLLM to use
        if self.msty_host:
            os.environ["OLLAMA_API_BASE"] = f"http://{self.msty_host}:11434"
        else:
            os.environ["OLLAMA_API_BASE"] = ollama_host
    
    def get_litellm_model_id(self, model_name: str) -> str:
        """
        Convert Ollama model name to LiteLLM model ID.
        
        Args:
            model_name: Model name as shown in Ollama (e.g., "llama3.2:3b")
            
        Returns:
            LiteLLM model ID (e.g., "ollama/llama3.2:3b")
        """
        # LiteLLM uses 'ollama/' prefix for Ollama models
        if model_name.startswith("ollama/"):
            return model_name
        return f"ollama/{model_name}"
    
    def generate_bloom_model_config(self, models: list[dict]) -> dict:
        """
        Generate a globals.py-compatible model dictionary for Bloom.
        
        Args:
            models: List of model info dicts from Ollama API
            
        Returns:
            Dictionary in Bloom's globals.py format
        """
        result = {}
        
        for model_info in models:
            name = model_info.get("name", "")
            if not name:
                continue
                
            # Create a clean key (remove colons, lowercase)
            key = name.replace(":", "-").lower()
            
            result[key] = {
                "id": f"ollama/{name}",
                "org": "ollama",
                "name": name.replace(":", " ").title(),
            }
        
        return result
    
    def get_recommended_config(self, model_name: str) -> dict:
        """
        Get recommended Bloom configuration for a given model.
        
        Args:
            model_name: The Ollama model name
            
        Returns:
            Recommended seed.yaml parameters for this model
        """
        # Parse model size from name
        name_lower = model_name.lower()
        
        # Determine model tier
        if any(x in name_lower for x in ["70b", "72b", "405b"]):
            tier = "large"
        elif any(x in name_lower for x in ["8b", "7b", "13b"]):
            tier = "medium"
        else:
            tier = "small"
        
        configs = {
            "large": {
                "max_tokens": 4000,
                "max_turns": 4,
                "temperature": 0.7,
                "target_reasoning_effort": "medium",
                "recommended_for": ["investment_analysis", "advisory_tasks"],
            },
            "medium": {
                "max_tokens": 2000,
                "max_turns": 3,
                "temperature": 0.7,
                "target_reasoning_effort": "low",
                "recommended_for": ["general_business", "financial_calculations"],
            },
            "small": {
                "max_tokens": 1000,
                "max_turns": 2,
                "temperature": 0.8,
                "target_reasoning_effort": "none",
                "recommended_for": ["simple_tasks"],
                "warning": "Small models may have limited capability for complex business tasks",
            },
        }
        
        return configs[tier]
    
    def validate_model_for_bloom(self, model_name: str) -> dict:
        """
        Validate that a model is suitable for Bloom evaluation.
        
        Args:
            model_name: The Ollama model name
            
        Returns:
            Validation result with status and any warnings
        """
        warnings = []
        errors = []
        
        # Check model name format
        if ":" not in model_name and "/" not in model_name:
            warnings.append(f"Model '{model_name}' may need a tag (e.g., ':latest')")
        
        # Check for known problematic models
        name_lower = model_name.lower()
        if "embed" in name_lower:
            errors.append("Embedding models cannot be used for evaluation")
        
        if "vision" in name_lower and "language" not in name_lower:
            warnings.append("Vision-only models may have limited text capabilities")
        
        # Size warnings
        if any(x in name_lower for x in ["1b", "0.5b", "500m"]):
            warnings.append("Very small models may not produce meaningful evaluation results")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "model_id": self.get_litellm_model_id(model_name),
        }
