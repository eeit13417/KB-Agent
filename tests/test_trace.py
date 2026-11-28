"""Tests for app/trace.py (docs/specs/chat-trace.md, AC-1 to AC-5)."""

import dataclasses
import hashlib
import json
import re

import pytest

import app.rag.generator as generator
import app.trace as trace_module
from app.config import settings
from app.trace import ChatTrace, cost_usd, prompt_version, to_json_line, write_trace


def make_trace(**overrides) -> ChatTrace:
    values = dict(
        request_id="0123456789abcdef0123456789abcdef",
        timestamp="2026-11-27T08:15:02.123Z",
        user_id=7,
        question="tips? 日本",
        question_chars=8,
        include_history=False,
        about_rulemaking=True,
        sources=[
            {"title": "29 CFR Part 541", "article_no": "§ 541.600", "status": "current", "distance": 0.21},
            {"title": "Defining and Delimiting", "article_no": "", "status": "rulemaking", "distance": 0.33},
        ],
        model="openai/gpt-oss-120b",
        prompt_version="abcdef012345",
        top_k=10,
        retrieval_ms=42,
        first_token_ms=310,
        total_ms=1250,
        prompt_tokens=1800,
        completion_tokens=40,
        llm_queue_ms=250,
        cost_usd=0.000294,
        declined=False,
        answer_chars=123,
        error=None,
    )
    values.update(overrides)
    return ChatTrace(**values)


# AC-1


def test_prompt_version_is_sha256_prefix_of_system_prompt():
    """AC-1: prompt_version is the first 12 lowercase hex chars of SHA-256(SYSTEM_PROMPT)."""
    version = prompt_version()
    expected = hashlib.sha256(generator.SYSTEM_PROMPT.encode()).hexdigest()[:12]
    assert version == expected
    assert re.fullmatch(r"[0-9a-f]{12}", version)


def test_prompt_version_changes_with_system_prompt(monkeypatch):
    """AC-1: prompt_version changes when SYSTEM_PROMPT is patched to another text."""
    before = prompt_version()
    new_prompt = "A completely different system prompt."
    monkeypatch.setattr(generator, "SYSTEM_PROMPT", new_prompt)
    # In case app.trace keeps its own reference to SYSTEM_PROMPT.
    monkeypatch.setattr(trace_module, "SYSTEM_PROMPT", new_prompt, raising=False)
    after = prompt_version()
    assert after != before
    assert after == hashlib.sha256(new_prompt.encode()).hexdigest()[:12]


# AC-2


def test_cost_usd_values(monkeypatch):
    """AC-2: cost_usd uses settings prices; None when a count is None; 0 for zero tokens."""
    monkeypatch.setattr(settings, "input_per_million", 0.15)
    monkeypatch.setattr(settings, "output_per_million", 0.60)
    assert cost_usd(2000, 500) == pytest.approx(0.0006)
    assert cost_usd(None, 500) is None
    assert cost_usd(2000, None) is None
    assert cost_usd(0, 0) == 0


def test_cost_usd_reads_prices_from_settings(monkeypatch):
    """AC-2: prices come from settings.input_per_million and output_per_million."""
    monkeypatch.setattr(settings, "input_per_million", 1.0)
    monkeypatch.setattr(settings, "output_per_million", 2.0)
    assert cost_usd(1_000_000, 1_000_000) == pytest.approx(3.0)


# AC-3


def test_to_json_line_round_trip():
    """AC-3: json.loads gives back every field, keys in field order, no newline, non-ASCII as is."""
    trace = make_trace()
    line = to_json_line(trace)
    assert "\n" not in line
    assert "日本" in line
    assert "\\u" not in line
    parsed = json.loads(line)
    field_names = [f.name for f in dataclasses.fields(ChatTrace)]
    assert list(parsed.keys()) == field_names
    assert parsed == dataclasses.asdict(trace)


# AC-4


def test_write_trace_prints_one_stdout_line(monkeypatch, capsys):
    """AC-4: write_trace prints exactly one line to stdout."""
    monkeypatch.setattr(settings, "trace_file", "")
    trace = make_trace()
    write_trace(trace)
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == dataclasses.asdict(trace)


def test_write_trace_appends_to_file_creating_folder(monkeypatch, tmp_path, capsys):
    """AC-4: with trace_file in a missing folder, two calls leave exactly two JSON lines."""
    path = tmp_path / "logs" / "traces.jsonl"
    monkeypatch.setattr(settings, "trace_file", str(path))
    write_trace(make_trace(request_id="a" * 32))
    write_trace(make_trace(request_id="b" * 32))
    capsys.readouterr()
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert len(lines) == 2
    assert text.endswith("\n")
    assert [json.loads(line)["request_id"] for line in lines] == ["a" * 32, "b" * 32]


# AC-5


def test_write_trace_file_failure_does_not_raise(monkeypatch, tmp_path, capsys):
    """AC-5: if appending fails (trace_file is a directory), no exception and stdout still written."""
    monkeypatch.setattr(settings, "trace_file", str(tmp_path))
    trace = make_trace()
    write_trace(trace)
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["request_id"] == trace.request_id
