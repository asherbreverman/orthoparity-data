"""OrthoParity core library: trace FDA 510(k) predicate ancestor chains from public FDA data, plus shared helpers."""

# Bump this whenever the parser logic changes. Every extraction row stores it,
# and older results are kept when a newer version re-extracts.
PARSER_VERSION = "1.3.1"
TOOL_VERSION = "0.4.0"
