"""Tests for the single token-estimation heuristic shared across audits."""

from tokens import (
    config_tokens,
    mcp_name_tokens,
    mcp_schema_tokens,
    prose_tokens,
)


def test_prose_uses_word_ratio():
    assert prose_tokens(100) == 130
    assert prose_tokens(0) == 0


def test_config_uses_char_ratio():
    assert config_tokens(400) == 100
    assert config_tokens(0) == 0


def test_mcp_name_and_schema_costs_differ_by_order_of_magnitude():
    assert mcp_name_tokens(10) == 500
    assert mcp_schema_tokens(10) == 5000
    assert mcp_schema_tokens(1) == 10 * mcp_name_tokens(1)
