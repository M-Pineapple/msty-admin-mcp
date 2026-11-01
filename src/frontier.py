"""Hand a local-model question to Cursor, Grok, or Claude.

The local model calls ``ask_frontier``. Cursor runs ``cursor-agent`` in ask
mode. Grok uses the xAI API. Claude uses the Anthropic API. Each provider
keeps its own session file. This module does not write the Msty Studio database.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence


Runner = Callable[[Sequence[str], int], "Completed"]


@dataclass
class Completed:
    returncode: int
    stdout: str
    stderr: str


@dataclass
class FrontierResult:
    answer: str
    chat_id: Optional[str]
    resumed: bool


def cursor_agent_binary() -> str:
    override = os.environ.get("MSTY_CURSOR_AGENT", "").strip()
    if override:
        return override
    found = shutil.which("cursor-agent")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "cursor-agent"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    raise FileNotFoundError(
        "cursor-agent is not on PATH. Install the Cursor agent CLI and run `cursor-agent login`."
    )


def session_file() -> Path:
    return Path.home() / ".msty-admin" / "frontier-session.json"


def frontier_workspace() -> Path:
    override = os.environ.get("MSTY_FRONTIER_WORKSPACE", "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_dir():
            raise FileNotFoundError(f"MSTY_FRONTIER_WORKSPACE is not a directory: {path}")
        return path
    path = Path.home() / ".msty-admin" / "frontier-workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_chat_id(path: Optional[Path] = None) -> Optional[str]:
    file = path or session_file()
    if not file.is_file():
        return None
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    chat_id = data.get("chat_id")
    if isinstance(chat_id, str) and chat_id.strip():
        return chat_id.strip()
    return None


def save_chat_id(chat_id: str, path: Optional[Path] = None) -> None:
    file = path or session_file()
    file.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"chat_id": chat_id}, indent=2) + "\n"
    file.write_text(payload, encoding="utf-8")
    file.chmod(stat.S_IRUSR | stat.S_IWUSR)


def api_key_file() -> Path:
    return Path.home() / ".msty-admin" / "cursor-api-key"


def load_api_key() -> Optional[str]:
    env_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if env_key:
        return env_key
    path = api_key_file()
    if not path.is_file():
        return None
    try:
        key = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return key or None


def build_argv(
    binary: str,
    question: str,
    chat_id: Optional[str],
    workspace: str,
    api_key: Optional[str] = None,
) -> List[str]:
    # api_key is accepted for compatibility but never placed on argv:
    # argv is visible to every local user via `ps`. agent_env() passes it.
    del api_key
    argv = [binary]
    if chat_id:
        argv.extend(["--resume", chat_id])
    argv.extend(
        [
            "-p",
            "--mode",
            "ask",
            "--output-format",
            "json",
            "--trust",
            "--sandbox",
            "enabled",
            "--workspace",
            workspace,
            _wrap(question),
        ]
    )
    return argv


def _wrap(question: str) -> str:
    return (
        "Answer only the question below. One short reply. "
        "Do not mention logs, roles, lanes, compliance, rules, or tools. "
        "Do not ask a follow-up question. "
        "Do not send email, move or delete files, or use trading tools.\n\n"
        f"Question: {question.strip()}"
    )


def clean_answer(answer: str) -> str:
    """Drop the Cursor session ritual so the local model does not ask about it."""
    kept = []
    for line in answer.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if lower.startswith("startup log:"):
            continue
        if lower.startswith("role=") or lower.startswith("lane="):
            continue
        if "compliance" in lower and ("line" in lower or "session" in lower):
            continue
        kept.append(line)
    cleaned = "\n".join(kept).strip()
    return cleaned or answer.strip()


def parse_agent_output(stdout: str) -> tuple[str, Optional[str]]:
    """Pull the answer text and chat id out of cursor-agent JSON output."""
    text = stdout.strip()
    if not text:
        return "", None

    for value in reversed(_json_values(text)):
        if isinstance(value, dict):
            answer = clean_answer(_answer_from_object(value))
            if answer:
                return answer, _chat_id_from_object(value)
        if isinstance(value, list):
            for item in reversed(value):
                if isinstance(item, dict) and _answer_from_object(item):
                    return clean_answer(_answer_from_object(item)), _chat_id_from_object(item)
    return text, None


def _json_values(text: str) -> list:
    decoder = json.JSONDecoder()
    values = []
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        values.append(value)
    return values


def _chat_id_from_object(obj: dict) -> Optional[str]:
    for key in ("session_id", "sessionId", "chat_id", "chatId"):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _answer_from_object(obj: dict) -> str:
    for key in ("result", "answer", "text"):
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    message = obj.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    content = obj.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        joined = "\n".join(part.strip() for part in parts if part.strip())
        if joined:
            return joined
    return ""


def agent_env(base: Optional[dict] = None) -> dict:
    env = dict(base if base is not None else os.environ)
    if not str(env.get("CURSOR_API_KEY", "")).strip():
        env.pop("CURSOR_API_KEY", None)
        if base is None:
            key = load_api_key()
            if key:
                env["CURSOR_API_KEY"] = key
    return env


def default_runner(argv: Sequence[str], timeout: int) -> Completed:
    proc = subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=agent_env(),
    )
    return Completed(proc.returncode, proc.stdout or "", proc.stderr or "")


_flight_lock = threading.Lock()
_flight: Optional[tuple] = None


def ask_cursor_agent(
    question: str,
    fresh: bool = False,
    runner: Optional[Runner] = None,
    session_path: Optional[Path] = None,
    binary: Optional[str] = None,
    workspace: Optional[str] = None,
    timeout: Optional[int] = None,
) -> FrontierResult:
    """Run one Cursor call. Extra calls that arrive while it is running share that answer."""
    global _flight
    with _flight_lock:
        if _flight is not None:
            event, box = _flight
            leader = False
        else:
            event = threading.Event()
            box = {}
            _flight = (event, box)
            leader = True
    if not leader:
        limit = timeout if timeout is not None else int(os.environ.get("MSTY_FRONTIER_TIMEOUT", "180"))
        if not event.wait(limit):
            raise TimeoutError("timed out waiting for the frontier answer already in progress")
        if "error" in box:
            raise box["error"]
        if "result" not in box:
            raise RuntimeError("frontier call finished without an answer")
        return box["result"]
    try:
        result = _ask_cursor_agent(
            question,
            fresh=fresh,
            runner=runner,
            session_path=session_path,
            binary=binary,
            workspace=workspace,
            timeout=timeout,
        )
        box["result"] = result
        return result
    except Exception as exc:
        box["error"] = exc
        raise
    finally:
        event.set()
        with _flight_lock:
            if _flight is not None and _flight[0] is event:
                _flight = None


def _ask_cursor_agent(
    question: str,
    fresh: bool = False,
    runner: Optional[Runner] = None,
    session_path: Optional[Path] = None,
    binary: Optional[str] = None,
    workspace: Optional[str] = None,
    timeout: Optional[int] = None,
) -> FrontierResult:
    cleaned = question.strip()
    if not cleaned:
        raise ValueError("question is empty")

    exe = binary or cursor_agent_binary()
    store = session_path or session_file()
    previous = None if fresh else load_chat_id(store)
    argv = build_argv(
        exe,
        cleaned,
        previous,
        workspace or str(frontier_workspace()),
        load_api_key(),
    )
    limit = timeout if timeout is not None else int(os.environ.get("MSTY_FRONTIER_TIMEOUT", "180"))
    run = runner or default_runner
    try:
        completed = run(argv, limit)
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"cursor-agent exceeded {limit}s") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "cursor-agent failed").strip()
        raise RuntimeError(detail[:2000])

    answer, chat_id = parse_agent_output(completed.stdout)
    if not answer:
        raise RuntimeError("cursor-agent returned no answer text")
    kept = chat_id or previous
    if kept:
        save_chat_id(kept, store)
    return FrontierResult(answer=answer, chat_id=kept, resumed=previous is not None)


PROVIDERS = ("cursor", "grok", "claude")
HttpJson = Callable[[str, Dict[str, str], Dict[str, Any], int], Dict[str, Any]]


def resolve_provider(provider: Optional[str] = None) -> str:
    name = (provider or os.environ.get("MSTY_FRONTIER_PROVIDER") or "cursor").strip().lower()
    aliases = {"xai": "grok", "x-ai": "grok", "anthropic": "claude"}
    name = aliases.get(name, name)
    if name not in PROVIDERS:
        raise ValueError(f"Unknown frontier provider '{provider}'. Use cursor, grok, or claude.")
    return name


def provider_session_file(provider: str) -> Path:
    if provider == "cursor":
        return session_file()
    return Path.home() / ".msty-admin" / f"frontier-{provider}-session.json"


def load_messages(path: Path) -> List[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    messages = data.get("messages")
    if isinstance(messages, list):
        return [m for m in messages if isinstance(m, dict)]
    return []


def save_messages(messages: List[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"messages": messages}, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def default_http_json(
    url: str, headers: Dict[str, str], payload: Dict[str, Any], timeout: int
) -> Dict[str, Any]:
    from urllib import request
    from urllib.error import HTTPError, URLError

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, method="POST", headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        raise RuntimeError(f"HTTP {exc.code}: {detail[:2000]}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(str(exc)) from exc


def ask_grok(
    question: str,
    fresh: bool = False,
    session_path: Optional[Path] = None,
    http_json: Optional[HttpJson] = None,
    timeout: Optional[int] = None,
) -> FrontierResult:
    key = os.environ.get("XAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("XAI_API_KEY is not set")
    cleaned = question.strip()
    if not cleaned:
        raise ValueError("question is empty")
    store = session_path or provider_session_file("grok")
    previous = [] if fresh else load_messages(store)
    messages = list(previous)
    messages.append({"role": "user", "content": cleaned})
    model = os.environ.get("MSTY_GROK_MODEL", "grok-3").strip() or "grok-3"
    limit = timeout if timeout is not None else int(os.environ.get("MSTY_FRONTIER_TIMEOUT", "180"))
    poster = http_json or default_http_json
    data = poster(
        "https://api.x.ai/v1/chat/completions",
        {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        {"model": model, "messages": messages, "temperature": 0.2},
        limit,
    )
    try:
        answer = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Grok returned no answer text") from exc
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("Grok returned no answer text")
    messages.append({"role": "assistant", "content": answer.strip()})
    save_messages(messages, store)
    return FrontierResult(answer=answer.strip(), chat_id=None, resumed=bool(previous))


def ask_claude(
    question: str,
    fresh: bool = False,
    session_path: Optional[Path] = None,
    http_json: Optional[HttpJson] = None,
    timeout: Optional[int] = None,
) -> FrontierResult:
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    cleaned = question.strip()
    if not cleaned:
        raise ValueError("question is empty")
    store = session_path or provider_session_file("claude")
    previous = [] if fresh else load_messages(store)
    messages = list(previous)
    messages.append({"role": "user", "content": cleaned})
    model = os.environ.get("MSTY_CLAUDE_MODEL", "claude-sonnet-4-5").strip() or "claude-sonnet-4-5"
    limit = timeout if timeout is not None else int(os.environ.get("MSTY_FRONTIER_TIMEOUT", "180"))
    poster = http_json or default_http_json
    data = poster(
        "https://api.anthropic.com/v1/messages",
        {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        {"model": model, "max_tokens": 1024, "messages": messages, "temperature": 0.2},
        limit,
    )
    answer = ""
    content = data.get("content") if isinstance(data, dict) else None
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        answer = "\n".join(parts).strip()
    if not answer:
        raise RuntimeError("Claude returned no answer text")
    messages.append({"role": "assistant", "content": answer})
    save_messages(messages, store)
    return FrontierResult(answer=answer, chat_id=None, resumed=bool(previous))


def ask_frontier(
    question: str,
    provider: Optional[str] = None,
    fresh: bool = False,
    **kwargs: Any,
) -> FrontierResult:
    """Dispatch to Cursor, Grok, or Claude. Cursor is the default."""
    name = resolve_provider(provider)
    if name == "grok":
        allowed = {k: kwargs[k] for k in ("session_path", "http_json", "timeout") if k in kwargs}
        return ask_grok(question, fresh=fresh, **allowed)
    if name == "claude":
        allowed = {k: kwargs[k] for k in ("session_path", "http_json", "timeout") if k in kwargs}
        return ask_claude(question, fresh=fresh, **allowed)
    allowed = {
        k: kwargs[k]
        for k in ("runner", "session_path", "binary", "workspace", "timeout")
        if k in kwargs
    }
    return ask_cursor_agent(question, fresh=fresh, **allowed)
