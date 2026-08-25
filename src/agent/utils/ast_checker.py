"""AST-based assertion integrity middleware.

Extracts Python ``assert`` statements (and unittest ``self.assert*`` calls used by
generated tests), fingerprints them, and blocks graph progress if later rewrites
weaken or drop assertions.
"""

from __future__ import annotations

import ast
import hashlib
from typing import Any


class AssertionTamperedError(Exception):
    """Raised when assertion count drops or assertion expression hashes diverge."""


def _canonical_hash(expression: str) -> str:
    normalized = " ".join(expression.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _is_unittest_assert_call(node: ast.Call) -> bool:
    """True for calls like self.assertEqual(...) / assertTrue(...)."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr.startswith("assert")
    # 判断调用目标是否为「裸名字」节点（如 assertEqual(...)），相对上面的 Attribute（如 self.assertEqual）
    if isinstance(func, ast.Name):
        return func.id.startswith("assert") and func.id != "assert"
    return False


class _AssertVisitor(ast.NodeVisitor):
    """Collect assertion expressions from ``ast.Assert`` and unittest assert* calls."""

    def __init__(self) -> None:
        self.expressions: list[str] = []

    def visit_Assert(self, node: ast.Assert) -> None:
        self.expressions.append(ast.unparse(node.test))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if _is_unittest_assert_call(node):
            self.expressions.append(ast.unparse(node))
        self.generic_visit(node)


def extract_asserts(code_str: str) -> list[dict[str, str]]:
    """Parse *code_str* and return assertion fingerprints.

    Each item is ``{"expression": <canonical source>, "hash": <sha256>}``.
    Covers:
    - ``ast.Assert`` nodes (``assert expr``)
    - unittest-style ``self.assert*`` / ``assert*`` Call nodes
    """
    if not code_str or not code_str.strip():
        return []

    tree = ast.parse(code_str)
    visitor = _AssertVisitor()
    visitor.visit(tree)

    results: list[dict[str, str]] = []
    for expr in visitor.expressions:
        results.append(
            {
                "expression": expr,
                "hash": _canonical_hash(expr),
            }
        )
    return results


def assertion_hashes(code_str: str) -> list[str]:
    """Return ordered list of assertion hashes for *code_str*."""
    return [item["hash"] for item in extract_asserts(code_str)]


def verify_assertions_unchanged(
    original_assertions: list[str] | list[dict[str, Any]] | None,
    code_str: str,
) -> None:
    """Ensure current code preserves the original assertion fingerprints.

    Raises:
        AssertionTamperedError: if assertion count decreases or any hash mismatches
            (e.g. assert removed, or rewritten to ``assert True``).
    """
    original_hashes = _normalize_hashes(original_assertions)
    # No baseline yet (first generation before record_assertions) — nothing to enforce.
    if not original_hashes:
        return

    current = extract_asserts(code_str)
    current_hashes = [item["hash"] for item in current]

    if len(current_hashes) < len(original_hashes):
        raise AssertionTamperedError(
            f"Assertion count decreased: original={len(original_hashes)}, "
            f"current={len(current_hashes)}. Assertions must not be deleted."
        )

    sorted_original = sorted(original_hashes)
    sorted_current = sorted(current_hashes)

    # Exact multiset match required (unchanged). Extra asserts alone still fail
    # when hashes diverge from the recorded baseline.
    if sorted_current != sorted_original:
        original_set = set(original_hashes)
        current_set = set(current_hashes)
        missing = sorted(original_set - current_set)
        unexpected = sorted(current_set - original_set)
        detail_parts: list[str] = []
        if missing:
            detail_parts.append(f"missing_hashes={missing}")
        if unexpected:
            detail_parts.append(f"unexpected_hashes={unexpected}")
        if len(current_hashes) != len(original_hashes):
            detail_parts.append(
                f"count_mismatch original={len(original_hashes)} current={len(current_hashes)}"
            )
        current_exprs = [item["expression"] for item in current]
        raise AssertionTamperedError(
            "Assertion expressions were modified (hash mismatch). "
            + "; ".join(detail_parts)
            + f"; current_expressions={current_exprs!r}"
        )


def _normalize_hashes(
    original_assertions: list[str] | list[dict[str, Any]] | None,
) -> list[str]:
    if not original_assertions:
        return []
    hashes: list[str] = []
    for item in original_assertions:
        if isinstance(item, str):
            hashes.append(item)
        elif isinstance(item, dict) and "hash" in item:
            hashes.append(str(item["hash"]))
        else:
            raise TypeError(
                f"Unsupported original_assertions entry type: {type(item)!r}"
            )
    return hashes
