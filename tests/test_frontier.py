"""Unit tests for the Cursor-agent handoff. No live cursor-agent process."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from src.frontier import (
    Completed,
    agent_env,
    ask_cursor_agent,
    build_argv,
    clean_answer,
    load_chat_id,
    parse_agent_output,
    save_chat_id,
)


def test_parse_ignores_trailing_usage_object():
    raw = json.dumps(
        {
            "type": "result",
            "result": "OK",
            "session_id": "chat-1",
            "usage": {"inputTokens": 1, "outputTokens": 1},
        }
    )
    answer, chat_id = parse_agent_output(raw)
    assert answer == "OK"
    assert chat_id == "chat-1"
    raw = json.dumps(
        {
            "type": "result",
            "result": "The capital is Antananarivo.",
            "session_id": "chat-1",
        }
    )
    answer, chat_id = parse_agent_output(raw)
    assert answer == "The capital is Antananarivo."
    assert chat_id == "chat-1"


def test_clean_answer_drops_session_ritual():
    raw = "\n".join(
        [
            "STARTUP LOG: grok @ cursor | role=lead | lane=coding",
            "The 40th prime is 173.",
            "Role=lead",
            "What is the compliance line for this session?",
        ]
    )
    assert clean_answer(raw) == "The 40th prime is 173."


def test_parse_uses_last_json_object_when_logs_precede_it():
    raw = "booting\n" + json.dumps({"result": "first", "session_id": "a"}) + "\n" + json.dumps(
        {"result": "second", "session_id": "b"}
    )
    answer, chat_id = parse_agent_output(raw)
    assert answer == "second"
    assert chat_id == "b"


def test_build_argv_resumes_and_stays_read_only():
    argv = build_argv("/bin/cursor-agent", "What is 2+2?", "chat-9", "/tmp/desk", "test-key")
    assert argv[0] == "/bin/cursor-agent"
    assert argv[1:3] == ["--api-key", "test-key"]
    assert "--resume" in argv and "chat-9" in argv
    assert "--mode" in argv and argv[argv.index("--mode") + 1] == "ask"
    assert "--force" not in argv
    assert "--yolo" not in argv
    assert argv[-1].endswith("What is 2+2?")
    assert "do not ask a follow-up" in argv[-1].lower()
    assert "move or delete files" in argv[-1].lower()


def test_fresh_call_omits_resume():
    argv = build_argv("/bin/cursor-agent", "Hi", None, "/tmp/desk")
    assert "--resume" not in argv


def test_session_file_is_user_readable_only(tmp_path: Path):
    path = tmp_path / "frontier-session.json"
    save_chat_id("abc", path)
    assert load_chat_id(path) == "abc"
    mode = path.stat().st_mode
    assert mode & stat.S_IRWXG == 0
    assert mode & stat.S_IRWXO == 0


def test_ask_resumes_saved_chat(tmp_path: Path):
    store = tmp_path / "frontier-session.json"
    save_chat_id("old-chat", store)
    seen = {}

    def runner(argv, timeout):
        seen["argv"] = list(argv)
        seen["timeout"] = timeout
        body = json.dumps({"result": "Still Antananarivo.", "session_id": "old-chat"})
        return Completed(0, body, "")

    outcome = ask_cursor_agent(
        "And the country?",
        runner=runner,
        session_path=store,
        binary="/bin/cursor-agent",
        workspace=str(tmp_path),
        timeout=15,
    )
    assert outcome.resumed is True
    assert outcome.answer == "Still Antananarivo."
    assert "--resume" in seen["argv"]
    assert "old-chat" in seen["argv"]
    assert load_chat_id(store) == "old-chat"


def test_fresh_ignores_saved_chat(tmp_path: Path):
    store = tmp_path / "frontier-session.json"
    save_chat_id("old-chat", store)

    def runner(argv, timeout):
        assert "--resume" not in argv
        return Completed(0, json.dumps({"result": "New.", "session_id": "new-chat"}), "")

    outcome = ask_cursor_agent(
        "Start over",
        fresh=True,
        runner=runner,
        session_path=store,
        binary="/bin/cursor-agent",
        workspace=str(tmp_path),
    )
    assert outcome.resumed is False
    assert outcome.chat_id == "new-chat"


def test_empty_api_key_is_removed_so_login_can_apply():
    env = agent_env({"CURSOR_API_KEY": "   ", "PATH": "/usr/bin"})
    assert "CURSOR_API_KEY" not in env
    kept = agent_env({"CURSOR_API_KEY": "present", "PATH": "/usr/bin"})
    assert kept["CURSOR_API_KEY"] == "present"


def test_empty_question_raises():
    with pytest.raises(ValueError):
        ask_cursor_agent("  ", runner=lambda argv, timeout: Completed(0, "", ""), binary="/bin/cursor-agent")


def test_overlapping_calls_share_one_cursor_run(tmp_path: Path):
    import threading

    calls = {"n": 0}
    started = threading.Event()

    def runner(argv, timeout):
        calls["n"] += 1
        started.set()
        threading.Event().wait(0.2)
        return Completed(0, json.dumps({"result": "173", "session_id": "once"}), "")

    results = []

    def run(question: str):
        results.append(
            ask_cursor_agent(
                question,
                fresh=True,
                runner=runner,
                session_path=tmp_path / "session.json",
                binary="/bin/cursor-agent",
                workspace=str(tmp_path),
                timeout=5,
            ).answer
        )

    first = threading.Thread(target=run, args=("What is the 40th prime?",))
    first.start()
    assert started.wait(2)
    second = threading.Thread(target=run, args=("What is the answer to the question?",))
    second.start()
    first.join(5)
    second.join(5)
    assert calls["n"] == 1
    assert results == ["173", "173"]


def test_failed_process_raises(tmp_path: Path):
    def runner(argv, timeout):
        return Completed(1, "", "not logged in")

    with pytest.raises(RuntimeError, match="not logged in"):
        ask_cursor_agent(
            "Hello",
            fresh=True,
            runner=runner,
            session_path=tmp_path / "session.json",
            binary="/bin/cursor-agent",
            workspace=str(tmp_path),
        )
