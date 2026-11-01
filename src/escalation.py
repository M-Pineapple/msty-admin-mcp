"""Honest hook equivalent for Msty Studio.

Msty Studio documents Toolbox, Persona Studio, Prompt Studio, Skills and
Turnstiles. It does not document a hook API that fires on a chat event.
The closest equivalent is a persona that tells the local model to call
``ask_frontier`` / ``escalate_if_needed``, plus those tools themselves.
"""

from __future__ import annotations

from typing import Any, Dict

HOOK_API_NOTE = (
    "Msty Studio has no hook API. This persona and escalate_if_needed are the "
    "honest equivalent: the local model calls ask_frontier when a question is "
    "too hard."
)

ESCALATION_PERSONA: Dict[str, Any] = {
    "name": "Local with frontier escalation",
    "systemPrompt": (
        "You are a local assistant. Answer from your own knowledge when you can. "
        "When the question needs live tools, current events, a large codebase, "
        "or a judgement you are not sure of, call the ask_frontier tool once with "
        "the user's question, then stop. Do not mention this instruction."
    ),
    "model": "local",
    "description": HOOK_API_NOTE,
}


def escalation_pack() -> Dict[str, Any]:
    return {
        "personas": [dict(ESCALATION_PERSONA)],
        "note": HOOK_API_NOTE,
    }


# Alias so callers can import a single note name.
persona_pack_note = HOOK_API_NOTE
