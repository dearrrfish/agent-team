"""Conservative, text-preserving edits of TOML string leaves."""

from __future__ import annotations

import copy
import json
import math
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .diagnostics import Diagnostic, ValidationFailure


def _fail(path: tuple[str, ...], message: str) -> None:
    raise ValidationFailure(
        [Diagnostic(".".join(path) or "TOML", message, code="toml-edit")]
    )


def _string(value: str) -> str:
    # TOML accepts JSON's string escapes, except JSON surrogate pairs. Keep
    # Unicode literal and escape DEL, which TOML forbids as a literal character.
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _key(value: str) -> str:
    return value if re.fullmatch(r"[A-Za-z0-9_-]+", value) else _string(value)


def _key_path(value: str) -> tuple[str, ...]:
    components: list[str] = []
    remaining = value.strip()
    pattern = r'''(?:[A-Za-z0-9_-]+|"(?:[^"\\\n]|\\.)*"|'[^'\n]*')'''
    while remaining:
        match = re.match(pattern, remaining)
        if match is None:
            _fail((), "Unsupported key layout; use ordinary TOML keys and table headers.")
        token = match.group(0)
        components.append(next(iter(tomllib.loads(f"{token} = 0"))))
        remaining = remaining[match.end() :].strip()
        if remaining:
            if not remaining.startswith("."):
                _fail((), "Unsupported key layout; use ordinary TOML table headers.")
            remaining = remaining[1:].strip()
    return tuple(components)


def _statements(content: str) -> list[tuple[int, int]]:
    """Locate logical statements, ignoring newlines inside values/comments."""
    spans: list[tuple[int, int]] = []
    start = index = depth = 0
    quote = ""
    comment = False
    while index < len(content):
        character = content[index]
        if comment:
            if character != "\n":
                index += 1
                continue
            comment = False
        elif quote:
            if quote.startswith('"') and character == "\\":
                index += 2
                continue
            if content.startswith(quote, index):
                index += len(quote)
                if len(quote) == 3:
                    # A closing multiline delimiter can include one or two
                    # additional quote characters belonging to the value.
                    while index < len(content) and content[index] == quote[0]:
                        index += 1
                quote = ""
                continue
            index += 1
            continue
        elif character == "#":
            comment = True
        elif character in "\"'":
            quote = character * 3 if content.startswith(character * 3, index) else character
            index += len(quote)
            continue
        elif character in "[{":
            depth += 1
        elif character in "]}":
            depth -= 1
        if character == "\n" and depth == 0:
            spans.append((start, index + 1))
            start = index + 1
        index += 1
    if start < len(content):
        spans.append((start, len(content)))
    return spans


def _outside_index(text: str, character: str) -> int:
    """Find punctuation outside a single-line quoted key/header."""
    quote = ""
    index = 0
    while index < len(text):
        current = text[index]
        if quote:
            if quote == '"' and current == "\\":
                index += 2
                continue
            if current == quote:
                quote = ""
        elif current in "\"'":
            quote = current
        elif current == character:
            return index
        index += 1
    return -1


@dataclass(frozen=True)
class _Assignment:
    path: tuple[str, ...]
    table: tuple[str, ...]
    key: tuple[str, ...]
    value_start: int
    statement_end: int


def _layout(content: str) -> tuple[dict[tuple[str, ...], int], list[_Assignment]]:
    tables: dict[tuple[str, ...], int] = {}
    assignments: list[_Assignment] = []
    current: tuple[str, ...] = ()
    ordinary_table = True
    for start, end in _statements(content):
        statement = content[start:end]
        stripped = statement.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("["):
            if ordinary_table:
                tables[current] = start
            comment = _outside_index(stripped, "#")
            header = (stripped if comment == -1 else stripped[:comment]).strip()
            ordinary_table = not header.startswith("[[")
            current = _key_path(header[1:-1] if ordinary_table else header[2:-2])
            continue
        equals = _outside_index(statement, "=")
        if equals == -1:
            _fail((), "Unsupported statement layout; use ordinary TOML assignments.")
        key = _key_path(statement[:equals])
        value_start = start + equals + 1
        while value_start < end and content[value_start] in " \t":
            value_start += 1
        assignments.append(_Assignment(current + key, current, key, value_start, end))
    if ordinary_table:
        tables[current] = len(content)
    return tables, assignments


def _string_end(content: str, assignment: _Assignment) -> int:
    start = assignment.value_start
    quote = content[start : start + 1]
    if quote not in ("'", '"') or content.startswith(quote * 3, start):
        _fail(
            assignment.path,
            "Cannot edit this value layout; use a single-line TOML string assignment.",
        )
    index = start + 1
    while index < assignment.statement_end:
        if quote == '"' and content[index] == "\\":
            index += 2
            continue
        if content[index] == quote:
            return index + 1
        index += 1
    _fail(assignment.path, "Cannot locate string; use a single-line TOML string assignment.")
    raise AssertionError("unreachable")


def _same_values(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _same_values(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_values(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, float) and math.isnan(left):
        return math.isnan(right)
    return left == right


def upsert_strings(content: str, changes: Mapping[tuple[str, ...], str]) -> str:
    """Upsert string leaves without rewriting unrelated TOML text.

    Affected inline tables, dotted assignments and multiline strings are
    deliberately rejected. The parsed result must equal the original document
    with exactly the requested leaves changed, including newly created tables.
    """
    try:
        original = tomllib.loads(content)
    except tomllib.TOMLDecodeError as error:
        _fail((), f"Invalid original TOML: {error}")
    expected: dict[str, Any] = copy.deepcopy(original)
    effective: dict[tuple[str, ...], str] = {}
    for path, value in changes.items():
        if not isinstance(path, tuple) or not path or any(
            not isinstance(component, str) for component in path
        ):
            _fail((), "Each change must use a nonempty tuple of string key components.")
        if not isinstance(value, str):
            _fail(path, "Each replacement must be a string.")
        parent = expected
        for component in path[:-1]:
            child = parent.setdefault(component, {})
            if not isinstance(child, dict):
                _fail(path, "Parent is not a table; use an ordinary TOML table for this key.")
            parent = child
        if path[-1] in parent and not isinstance(parent[path[-1]], str):
            _fail(path, "Existing leaf is not a string; use a TOML string assignment.")
        if parent.get(path[-1]) != value:
            effective[path] = value
        parent[path[-1]] = value
    if not effective:
        return content

    tables, assignments = _layout(content)
    edits: list[tuple[int, int, str]] = []
    missing = dict(effective)
    for assignment in assignments:
        for path in effective:
            if len(assignment.key) > 1:
                implicit = assignment.table + assignment.key[:1]
                if path[: len(implicit)] == implicit:
                    _fail(path, "Affected dotted assignment; expand it into ordinary TOML tables first.")
            if len(path) > len(assignment.path) and path[: len(assignment.path)] == assignment.path:
                _fail(path, "Affected inline table; expand it into ordinary TOML tables first.")
        if assignment.path in effective:
            end = _string_end(content, assignment)
            edits.append((assignment.value_start, end, _string(effective[assignment.path])))
            missing.pop(assignment.path)

    newline = "\r\n" if "\r\n" in content else "\n"
    insertions: dict[tuple[str, ...], list[str]] = {}
    for path, value in missing.items():
        insertions.setdefault(path[:-1], []).append(f"{_key(path[-1])} = {_string(value)}{newline}")
    appended: list[str] = []
    for table, lines in insertions.items():
        if table in tables:
            position = tables[table]
            prefix = newline if position and content[position - 1] != "\n" else ""
            edits.append((position, position, prefix + "".join(lines)))
        else:
            header = ".".join(_key(component) for component in table)
            appended.append(f"{newline}[{header}]{newline}" + "".join(lines))
    if appended:
        edits.append((len(content), len(content), "".join(appended)))
    candidate = content
    # Equal-position insertions retain mapping order. Replacements are applied
    # against original offsets, from right to left.
    for _, (start, end, replacement) in sorted(
        enumerate(edits), key=lambda item: (item[1][0], item[0]), reverse=True
    ):
        candidate = candidate[:start] + replacement + candidate[end:]
    try:
        actual = tomllib.loads(candidate)
    except tomllib.TOMLDecodeError as error:
        _fail((), f"Unsupported affected TOML layout; expand it into ordinary tables first: {error}")
    if not _same_values(actual, expected):
        _fail((), "Edit would change unrelated TOML values; expand affected keys into ordinary tables first.")
    return candidate
