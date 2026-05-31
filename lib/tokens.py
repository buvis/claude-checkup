"""The single token-estimation heuristic, owned here instead of in 4 skill prompts.

All counts are deliberate ESTIMATES. Callers must label them as such in output.
"""

from __future__ import annotations

WORD_TO_TOKEN = 1.3  # prose tokenizes ~1.3 tokens per word
CHARS_PER_TOKEN = 4  # code/JSON tokenizes ~4 chars per token
MCP_TOOL_NAME_TOKENS = 50  # a deferred tool name string in the listing
MCP_TOOL_SCHEMA_TOKENS = 500  # a full tool schema fetched on demand


def prose_tokens(word_count: int) -> int:
    return round(word_count * WORD_TO_TOKEN)


def config_tokens(char_count: int) -> int:
    return round(char_count / CHARS_PER_TOKEN)


def mcp_name_tokens(tool_count: int) -> int:
    return tool_count * MCP_TOOL_NAME_TOKENS


def mcp_schema_tokens(tool_count: int) -> int:
    return tool_count * MCP_TOOL_SCHEMA_TOKENS
