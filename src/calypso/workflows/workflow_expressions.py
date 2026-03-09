"""Safe reference expression parser for workflow conditions.

Evaluates simple boolean expressions against a WorkflowExecutionContext
without using ``eval()`` or ``exec()``.

Supported syntax:
    step_1.status == "pass"
    step_1.total_fail == 0
    step_1.pass_rate > 90.0
    step_1.total_pass >= 5 and step_2.status == "pass"
    step_1.status != "fail" or step_2.status == "pass"
    (step_1.status == "pass" or step_2.status == "pass") and step_3.total_fail == 0
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from calypso.workflows.workflow_context import WorkflowExecutionContext


_TOKEN_RE = re.compile(
    r"""
    (?P<string>"[^"]*"|'[^']*')    # quoted strings
    | (?P<number>-?\d+\.?\d*)       # numbers
    | (?P<op>==|!=|>=|<=|>|<)       # comparison operators
    | (?P<logic>and|or|not)         # logical operators
    | (?P<bool>true|false)          # boolean literals
    | (?P<paren>[()]) # parentheses
    | (?P<ref>[a-zA-Z_][\w.]*)      # references (step_id.attr)
    | (?P<ws>\s+)                   # whitespace (ignored)
    """,
    re.VERBOSE,
)


def evaluate_condition(expression: str, ctx: WorkflowExecutionContext) -> bool:
    """Evaluate a condition expression against the workflow context.

    Returns True if the expression evaluates to truthy, False otherwise.
    An empty expression always returns True (unconditional).
    """
    if not expression or not expression.strip():
        return True

    tokens = _tokenize(expression)
    if not tokens:
        return True

    return _evaluate_tokens(tokens, ctx)


def _tokenize(expression: str) -> list[tuple[str, str]]:
    """Tokenize an expression into (type, value) pairs."""
    tokens: list[tuple[str, str]] = []
    for match in _TOKEN_RE.finditer(expression):
        if match.group("ws"):
            continue
        for group_name in ("string", "number", "op", "logic", "bool", "paren", "ref"):
            value = match.group(group_name)
            if value is not None:
                tokens.append((group_name, value))
                break
    return tokens


def _evaluate_tokens(tokens: list[tuple[str, str]], ctx: WorkflowExecutionContext) -> bool:
    """Evaluate tokenized expression with short-circuit logic."""
    # Resolve parenthesized sub-expressions first
    tokens = _resolve_parens(tokens, ctx)
    # Split on 'or' first (lowest precedence)
    or_groups = _split_tokens(tokens, "or")
    return any(_evaluate_and_group(group, ctx) for group in or_groups)


def _resolve_parens(
    tokens: list[tuple[str, str]], ctx: WorkflowExecutionContext
) -> list[tuple[str, str]]:
    """Recursively resolve innermost parenthesized groups to boolean tokens."""
    while True:
        # Find the innermost '(' ... ')' pair
        last_open = -1
        for i, (kind, value) in enumerate(tokens):
            if kind == "paren" and value == "(":
                last_open = i
            elif kind == "paren" and value == ")" and last_open >= 0:
                # Evaluate the sub-expression inside the parens
                inner = tokens[last_open + 1 : i]
                result = _evaluate_tokens(inner, ctx)
                # Replace the entire (...) span with a single bool token
                tokens = (
                    tokens[:last_open] + [("bool", "true" if result else "false")] + tokens[i + 1 :]
                )
                break
        else:
            # No more parens found
            break
    # Reject any stray/unmatched parentheses
    for kind, value in tokens:
        if kind == "paren":
            raise ValueError(f"Unmatched parenthesis '{value}' in expression")
    return tokens


def _evaluate_and_group(tokens: list[tuple[str, str]], ctx: WorkflowExecutionContext) -> bool:
    """Evaluate tokens connected by 'and'."""
    and_groups = _split_tokens(tokens, "and")
    return all(_evaluate_comparison(group, ctx) for group in and_groups)


def _evaluate_comparison(tokens: list[tuple[str, str]], ctx: WorkflowExecutionContext) -> bool:
    """Evaluate a single comparison or value."""
    # Handle 'not' prefix
    if tokens and tokens[0] == ("logic", "not"):
        return not _evaluate_comparison(tokens[1:], ctx)

    if len(tokens) == 1:
        val = _resolve_value(tokens[0], ctx)
        return bool(val)

    if len(tokens) == 3:
        left = _resolve_value(tokens[0], ctx)
        op = tokens[1][1] if tokens[1][0] == "op" else ""
        right = _resolve_value(tokens[2], ctx)
        return _compare(left, op, right)

    # Fallback: try to resolve as a single truthy value
    if tokens:
        val = _resolve_value(tokens[0], ctx)
        return bool(val)

    return True


def _resolve_value(token: tuple[str, str], ctx: WorkflowExecutionContext) -> object:
    """Resolve a token to its actual value."""
    kind, value = token
    if kind == "string":
        return value.strip("\"'")
    elif kind == "number":
        return float(value) if "." in value else int(value)
    elif kind == "bool":
        return value.lower() == "true"
    elif kind == "ref":
        resolved = ctx.resolve_binding(value)
        return resolved
    return value


def _compare(left: object, op: str, right: object) -> bool:
    """Compare two values with the given operator."""
    # Coerce types for numeric comparison
    if isinstance(left, str) and isinstance(right, (int, float)):
        try:
            left = float(left)
        except (ValueError, TypeError):
            pass
    if isinstance(right, str) and isinstance(left, (int, float)):
        try:
            right = float(right)
        except (ValueError, TypeError):
            pass

    if op == "==":
        return left == right
    elif op == "!=":
        return left != right
    elif op == ">":
        return left > right  # type: ignore[operator]
    elif op == "<":
        return left < right  # type: ignore[operator]
    elif op == ">=":
        return left >= right  # type: ignore[operator]
    elif op == "<=":
        return left <= right  # type: ignore[operator]
    return False


def _split_tokens(tokens: list[tuple[str, str]], operator: str) -> list[list[tuple[str, str]]]:
    """Split token list on a logical operator."""
    groups: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for token in tokens:
        if token == ("logic", operator):
            if current:
                groups.append(current)
            current = []
        else:
            current.append(token)
    if current:
        groups.append(current)
    return groups if groups else [tokens]
