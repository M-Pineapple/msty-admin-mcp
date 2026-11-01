"""Approximate Q4 GGUF sizes for hardware-aware model recommendations.

Sizes are on-disk estimates for a typical Q4_K_M GGUF, not a guarantee of
runtime memory. Apple Silicon unified memory and discrete VRAM still need
headroom for context and the OS.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

# q4_gb is an approximate Q4_K_M GGUF on-disk size.
CATALOG: List[Dict[str, Any]] = [
    {
        "id": "llama3.2:1b",
        "q4_gb": 0.8,
        "params": "1B",
        "use_cases": ["general", "chat", "summarise"],
    },
    {
        "id": "llama3.2:3b",
        "q4_gb": 2.0,
        "params": "3B",
        "use_cases": ["general", "chat", "summarise"],
    },
    {
        "id": "phi3:mini",
        "q4_gb": 2.2,
        "params": "3.8B",
        "use_cases": ["general", "chat"],
    },
    {
        "id": "qwen2.5-coder:3b",
        "q4_gb": 2.0,
        "params": "3B",
        "use_cases": ["coding"],
    },
    {
        "id": "mistral:7b",
        "q4_gb": 4.4,
        "params": "7B",
        "use_cases": ["general", "chat", "summarise"],
    },
    {
        "id": "llama3.1:8b",
        "q4_gb": 4.9,
        "params": "8B",
        "use_cases": ["general", "chat", "summarise"],
    },
    {
        "id": "qwen2.5:7b",
        "q4_gb": 4.7,
        "params": "7B",
        "use_cases": ["general", "coding", "chat"],
    },
    {
        "id": "qwen2.5-coder:7b",
        "q4_gb": 4.7,
        "params": "7B",
        "use_cases": ["coding"],
    },
    {
        "id": "deepseek-coder:6.7b",
        "q4_gb": 4.1,
        "params": "6.7B",
        "use_cases": ["coding"],
    },
    {
        "id": "gemma2:9b",
        "q4_gb": 5.5,
        "params": "9B",
        "use_cases": ["general", "chat"],
    },
    {
        "id": "qwen2.5:14b",
        "q4_gb": 9.0,
        "params": "14B",
        "use_cases": ["general", "coding", "research"],
    },
    {
        "id": "qwen2.5:32b",
        "q4_gb": 20.0,
        "params": "32B",
        "use_cases": ["research", "coding"],
    },
    {
        "id": "llama3.1:70b",
        "q4_gb": 40.0,
        "params": "70B",
        "use_cases": ["research"],
    },
]

_PARAM_RE = re.compile(r"(?P<n>\d+(?:\.\d+)?)[bB]\b")

# Rough Q4 GB from a parameter count in the model name, when the id is not in CATALOG.
_PARAM_TO_Q4 = (
    (70.0, 40.0),
    (32.0, 20.0),
    (14.0, 9.0),
    (13.0, 8.0),
    (9.0, 5.5),
    (8.0, 4.9),
    (7.0, 4.5),
    (3.0, 2.0),
    (1.0, 0.8),
)


def memory_budget_gb(profile: Dict[str, Any]) -> float:
    """Safe load for a Q4 model.

    Apple unified memory: about 60% of total RAM.
    Discrete VRAM: about 85% of reported VRAM.
    Other systems: about 50% of system RAM.
    """
    ram = float(profile.get("ram_gb") or 0)
    vram = profile.get("vram_gb")
    unified = bool(profile.get("unified_memory"))
    if unified and ram > 0:
        return round(ram * 0.60, 1)
    if isinstance(vram, (int, float)) and vram > 0:
        return round(float(vram) * 0.85, 1)
    if ram > 0:
        return round(ram * 0.50, 1)
    return 0.0


def estimate_q4_gb(model_id: str) -> Optional[float]:
    """Return a Q4 size estimate for a model id, or None if unknown."""
    lowered = (model_id or "").strip().lower()
    for entry in CATALOG:
        if entry["id"] == lowered or entry["id"].split(":")[0] == lowered:
            return float(entry["q4_gb"])
    match = _PARAM_RE.search(lowered)
    if not match:
        return None
    params = float(match.group("n"))
    for threshold, size in _PARAM_TO_Q4:
        if params >= threshold:
            return size
    return 0.8


def fits(model_id: str, budget_gb: float) -> Optional[bool]:
    size = estimate_q4_gb(model_id)
    if size is None:
        return None
    return size <= budget_gb


def recommend(
    profile: Dict[str, Any],
    use_case: str = "general",
    insights_models: Optional[Sequence[Dict[str, Any]]] = None,
    limit: int = 4,
) -> Dict[str, Any]:
    """Pick catalog models that fit the memory budget, boosted by recent use."""
    budget = memory_budget_gb(profile)
    use = (use_case or "general").strip().lower()
    candidates = [dict(entry) for entry in CATALOG if entry["q4_gb"] <= budget]
    if not candidates:
        smallest = min(CATALOG, key=lambda e: e["q4_gb"])
        return {
            "recommendation": smallest["id"],
            "fits": smallest["q4_gb"] <= budget,
            "budget_gb": budget,
            "alternatives": [],
            "reason": (
                f"The memory budget is {budget:.1f} GB, which is tight even for a Q4 "
                f"{smallest['params']} model ({smallest['q4_gb']} GB). "
                f"{smallest['id']} is the smallest catalog entry."
            ),
            "source": "hardware-catalog",
            "candidates": [],
        }

    preferred = [c for c in candidates if use in c["use_cases"]]
    rest = [c for c in candidates if c not in preferred]
    ordered = preferred + rest

    used_fit: Optional[Dict[str, Any]] = None
    used_too_big: Optional[str] = None
    for item in insights_models or []:
        model_id = str(item.get("model_id") or item.get("id") or "").strip()
        if not model_id:
            continue
        size = estimate_q4_gb(model_id)
        if size is None:
            continue
        if size <= budget:
            used_fit = {
                "id": model_id,
                "q4_gb": size,
                "calls": item.get("calls"),
                "avg_tokens_per_sec": item.get("avg_tokens_per_sec"),
            }
            break
        if used_too_big is None:
            used_too_big = model_id

    pick = dict(ordered[0])
    source = "hardware-catalog"
    if used_fit:
        pick = {
            "id": used_fit["id"],
            "q4_gb": used_fit["q4_gb"],
            "params": used_fit["id"],
            "use_cases": [use],
        }
        source = "insights+hardware"
        # Keep the catalog head as an alternative if it differs.
        if ordered and ordered[0]["id"] != used_fit["id"]:
            ordered = [c for c in ordered if c["id"] != used_fit["id"]]

    alternatives = [c["id"] for c in ordered[:limit] if c["id"] != pick["id"]][: max(limit - 1, 0)]
    memory_kind = "unified memory" if profile.get("unified_memory") else "system memory"
    if profile.get("vram_gb") and not profile.get("unified_memory"):
        memory_kind = "discrete VRAM"

    reason_parts = [
        (
            f"A Q4 model should stay within about {budget:.1f} GB "
            f"({memory_kind} budget on this machine)."
        )
    ]
    if used_fit:
        reason_parts.append(
            f"{used_fit['id']} is your most used recent model that still fits "
            f"(about {used_fit['q4_gb']} GB Q4)."
        )
    else:
        reason_parts.append(
            f"{pick['id']} is the best catalog match for use case '{use}' "
            f"(about {pick['q4_gb']} GB Q4)."
        )
    if used_too_big and not used_fit:
        reason_parts.append(
            f"{used_too_big} shows up in recent use but is larger than the budget, so it was skipped."
        )

    return {
        "recommendation": pick["id"],
        "fits": True,
        "budget_gb": budget,
        "q4_gb": pick.get("q4_gb"),
        "alternatives": alternatives,
        "reason": " ".join(reason_parts),
        "source": source,
        "use_case": use,
        "candidates": [
            {"id": c["id"], "q4_gb": c["q4_gb"], "params": c["params"]}
            for c in ordered[:limit]
        ],
    }
