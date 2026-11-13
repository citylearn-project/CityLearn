from __future__ import annotations

import json
import re
from typing import Any, Iterator

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", flags=re.DOTALL | re.IGNORECASE)
_CODE_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", flags=re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _try_parse_json(candidate: str) -> tuple[bool, Any]:
    snippet = candidate.strip()
    if not snippet:
        return False, None
    for attempt in (snippet, _TRAILING_COMMA_RE.sub(r"\1", snippet)):
        try:
            return True, json.loads(attempt)
        except json.JSONDecodeError:
            continue
    return False, None


def _iter_balanced_json_spans(text: str) -> Iterator[str]:
    n = len(text)
    for start_idx, ch in enumerate(text):
        if ch not in "{[":
            continue
        closing = "}" if ch == "{" else "]"
        stack = [closing]
        in_string = False
        escape = False
        for idx in range(start_idx + 1, n):
            cur = text[idx]
            if in_string:
                if escape:
                    escape = False
                elif cur == "\\":
                    escape = True
                elif cur == '"':
                    in_string = False
                continue

            if cur == '"':
                in_string = True
            elif cur == "{":
                stack.append("}")
            elif cur == "[":
                stack.append("]")
            elif cur in "}]":
                if not stack or cur != stack[-1]:
                    break
                stack.pop()
                if not stack:
                    yield text[start_idx : idx + 1]
                    break


def extract_json_from_polluted_string(text: str) -> Any:
    """Extract and parse a JSON object or array from noisy LLM text output.

    Handles reasoning blocks (``<think>...</think>``), Markdown code fences,
    conversational prose before/after JSON, braces inside string literals, and
    minor trailing-comma formatting issues.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Cannot extract JSON from an empty or non-string response.")

    cleaned = _THINK_BLOCK_RE.sub("", text).strip()
    if "<think>" in cleaned.lower():
        # Handle truncated reasoning blocks when a JSON payload still follows.
        lower_idx = cleaned.lower().find("<think>")
        brace_after = cleaned.find("{", lower_idx)
        if brace_after != -1:
            cleaned = cleaned[:lower_idx] + cleaned[brace_after:]

    ok, parsed = _try_parse_json(cleaned)
    if ok:
        return parsed

    for match in _CODE_FENCE_RE.finditer(cleaned):
        fenced = match.group(1)
        ok, parsed = _try_parse_json(fenced)
        if ok:
            return parsed
        for span in _iter_balanced_json_spans(fenced):
            ok, parsed = _try_parse_json(span)
            if ok:
                return parsed

    for span in _iter_balanced_json_spans(cleaned):
        ok, parsed = _try_parse_json(span)
        if ok:
            return parsed

    raise ValueError(f"Could not extract valid JSON from LLM response: {text[:240]!r}")


extract_json_from = extract_json_from_polluted_string
