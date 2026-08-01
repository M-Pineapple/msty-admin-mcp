"""
Analytics derived from Msty Studio's own insights and entity tables.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src import db


def _parse_timeframe(timeframe: str) -> Optional[datetime]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    mapping = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90),
        "all": None,
    }
    delta = mapping.get(timeframe, timedelta(days=7))
    if delta is None:
        return None
    return now - delta


def get_insights_usage(
    model_id: Optional[str] = None,
    timeframe: str = "7d",
    limit: int = 500,
) -> Dict[str, Any]:
    if not db.table_exists("insightsLanguageModelUsage"):
        return {"error": "insightsLanguageModelUsage table not found", "metrics": {}}

    cutoff = _parse_timeframe(timeframe)
    rows = db.fetch_all(
        "insightsLanguageModelUsage",
        limit=limit,
        order_by="createdAt DESC",
    )
    if cutoff:
        filtered = []
        for row in rows:
            created = row.get("createdAt")
            try:
                ts = datetime.fromisoformat(str(created).replace("Z", ""))
            except Exception:
                filtered.append(row)
                continue
            if ts >= cutoff:
                filtered.append(row)
        rows = filtered

    if model_id:
        rows = [r for r in rows if r.get("modelId") == model_id]

    by_model: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "latency_sec_sum": 0.0,
            "tps_sum": 0.0,
        }
    )

    for row in rows:
        mid = row.get("modelId") or "unknown"
        bucket = by_model[mid]
        bucket["calls"] += 1
        bucket["prompt_tokens"] += int(row.get("promptTokens") or 0)
        bucket["completion_tokens"] += int(row.get("completionTokens") or 0)
        bucket["total_tokens"] += int(row.get("totalTokens") or 0)
        bucket["total_cost_usd"] += float(row.get("totalCostInUSD") or 0)
        bucket["latency_sec_sum"] += float(row.get("totalTimeInSec") or 0)
        bucket["tps_sum"] += float(row.get("tokensPerSec") or 0)
        bucket["provider"] = row.get("providerType") or row.get("providerId")

    models = []
    for mid, bucket in by_model.items():
        calls = max(bucket["calls"], 1)
        models.append(
            {
                "model_id": mid,
                "provider": bucket.get("provider"),
                "calls": bucket["calls"],
                "prompt_tokens": bucket["prompt_tokens"],
                "completion_tokens": bucket["completion_tokens"],
                "total_tokens": bucket["total_tokens"],
                "total_cost_usd": round(bucket["total_cost_usd"], 6),
                "avg_latency_sec": round(bucket["latency_sec_sum"] / calls, 3),
                "avg_tokens_per_sec": round(bucket["tps_sum"] / calls, 3),
            }
        )
    models.sort(key=lambda m: m["calls"], reverse=True)

    return {
        "timeframe": timeframe,
        "model_filter": model_id,
        "sample_size": len(rows),
        "models": models,
        "totals": {
            "calls": sum(m["calls"] for m in models),
            "total_tokens": sum(m["total_tokens"] for m in models),
            "total_cost_usd": round(sum(m["total_cost_usd"] for m in models), 6),
        },
    }


def analyse_conversation_patterns(model_id: Optional[str] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "conversations": 0,
        "messages": 0,
        "projects": 0,
        "patterns": [],
    }
    if db.table_exists("conversationTexts"):
        result["conversations"] = db.count_rows("conversationTexts")
    if db.table_exists("conversationTextMessages"):
        result["messages"] = db.count_rows("conversationTextMessages")
    if db.table_exists("conversationTextProjects"):
        result["projects"] = db.count_rows("conversationTextProjects")

    avg_msgs = (
        round(result["messages"] / result["conversations"], 2)
        if result["conversations"]
        else 0
    )
    result["patterns"].append(f"Average messages per conversation: {avg_msgs}")

    if db.table_exists("conversationTexts"):
        types = db.safe_query(
            "SELECT type, COUNT(*) AS c FROM conversationTexts GROUP BY type ORDER BY c DESC",
            limit=20,
        )[0]
        if types:
            result["conversation_types"] = types
            top = types[0]
            result["patterns"].append(
                f"Most common conversation type: {top.get('type') or 'null'} ({top.get('c')})"
            )

    if db.table_exists("insightsLanguageModelUsage"):
        insights = get_insights_usage(model_id=model_id, timeframe="30d")
        if insights.get("models"):
            top_model = insights["models"][0]
            result["patterns"].append(
                f"Most used model (30d): {top_model['model_id']} ({top_model['calls']} calls)"
            )
            result["top_models"] = insights["models"][:5]

    return result


def optimise_knowledge_stacks() -> Dict[str, Any]:
    suggestions: List[str] = []
    stacks: List[Dict[str, Any]] = []

    if not db.table_exists("knowledgeStacks"):
        return {
            "suggestions": ["Knowledge Stacks table not found — is Studio installed?"],
            "stacks": [],
        }

    stacks = db.fetch_all(
        "knowledgeStacks",
        columns=[
            "id",
            "title",
            "status",
            "composeStats",
            "updatedAt",
            "createdAt",
        ],
        limit=200,
        order_by="updatedAt DESC",
    )

    drafts = [s for s in stacks if (s.get("status") or "").lower() == "draft"]
    if drafts:
        suggestions.append(
            f"{len(drafts)} knowledge stack(s) are still in draft — compose them before use."
        )

    if not stacks:
        suggestions.append(
            "No Knowledge Stacks found. Create a Next Gen stack or install one from Discover Hub."
        )
    else:
        suggestions.append(
            f"{len(stacks)} Knowledge Stack(s) present. Prefer Next Gen stacks with folder sync for large corpora."
        )

    progress_issues = []
    if db.table_exists("knowledgeStackComposeProgress"):
        progress = db.fetch_all("knowledgeStackComposeProgress", limit=200)
        progress_issues = [
            p
            for p in progress
            if (p.get("processingStatus") or "").lower() in {"error", "failed", "pending"}
            or p.get("error")
        ]
        if progress_issues:
            suggestions.append(
                f"{len(progress_issues)} compose progress item(s) need attention (error/pending)."
            )

    return {
        "stack_count": len(stacks),
        "draft_count": len(drafts),
        "compose_issues": len(progress_issues),
        "suggestions": suggestions,
        "stacks": stacks[:50],
        "issue_samples": progress_issues[:20],
    }


def suggest_persona_improvements() -> Dict[str, Any]:
    suggestions: List[Dict[str, Any]] = []
    personas = []
    if db.table_exists("personas"):
        personas = db.fetch_all("personas", limit=100)

    for persona in personas:
        name = persona.get("name") or persona.get("id")
        prompt = persona.get("systemPrompt") or ""
        issues = []
        if len(prompt.strip()) < 40:
            issues.append("System prompt is very short — add role, constraints, and output format.")
        if "you are" not in prompt.lower() and "your role" not in prompt.lower():
            issues.append("Consider stating the persona role explicitly.")
        if not persona.get("partialKnowledgeStacksInfo"):
            issues.append("No Knowledge Stacks attached — add domain stacks for grounded answers.")
        if not persona.get("partialToolsetsInfo"):
            issues.append("No toolsets attached — attach Toolbox toolsets for action-capable work.")
        if issues:
            suggestions.append({"persona": name, "id": persona.get("id"), "improvements": issues})

    if not personas:
        suggestions.append(
            {
                "persona": None,
                "improvements": [
                    "No personas found. Create personas in Persona Studio or generate one via generate_persona."
                ],
            }
        )
    elif not suggestions:
        suggestions.append(
            {
                "persona": None,
                "improvements": [
                    "Personas look reasonably configured. Consider Shadow Personas for fact-checking overlays."
                ],
            }
        )

    crews = db.count_rows("crews") if db.table_exists("crews") else 0
    shadows = db.count_rows("shadowPersonas") if db.table_exists("shadowPersonas") else 0

    return {
        "persona_count": len(personas),
        "crew_count": crews,
        "shadow_persona_count": shadows,
        "suggestions": suggestions,
    }
