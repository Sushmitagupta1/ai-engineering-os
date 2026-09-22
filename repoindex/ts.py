"""Shared tree-sitter wiring: language registry, parsing, and call-site queries.

Single source of truth for grammars + queries used by repoindex.symbols and tools.codelens.
"""

from __future__ import annotations

import tree_sitter
import tree_sitter_bash
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript

_RAW = {
    "python": tree_sitter_python.language(),
    "javascript": tree_sitter_javascript.language(),
    "bash": tree_sitter_bash.language(),
    "typescript": tree_sitter_typescript.language_typescript(),
}

try:
    import tree_sitter_go  # type: ignore
    _RAW["go"] = tree_sitter_go.language()
except ImportError:
    pass

try:
    import tree_sitter_rust  # type: ignore
    _RAW["rust"] = tree_sitter_rust.language()
except ImportError:
    pass

LANGUAGES: dict[str, tree_sitter.Language] = {
    k: tree_sitter.Language(v) for k, v in _RAW.items()
}

# call-site queries: capture the callee name token as @name
CALL_QUERIES: dict[str, str] = {
    "python": "(call function: (identifier) @name)",
    "javascript": "(call_expression function: (identifier) @name)",
    "typescript": "(call_expression function: (identifier) @name)",
    "bash": "(command name: (command_name) @name)",
    "go": "(call_expression function: (identifier) @name)",
    "rust": "(call_expression function: (identifier) @name)",
}

# member-style calls: obj.method(), self.method() etc.
MEMBER_QUERIES: dict[str, str] = {
    "python": "(call function: (attribute attribute: (identifier) @name))",
    "javascript": "(call_expression function: (member_expression property: (property_identifier) @name))",
    "typescript": "(call_expression function: (member_expression property: (property_identifier) @name))",
}

# identifiers that should never count as callees (language builtins / noise)
IGNORED_CALLEES: dict[str, set[str]] = {
    "python": {
        "print", "len", "range", "type", "str", "int", "float", "list", "dict", "set",
        "tuple", "bool", "open", "isinstance", "getattr", "setattr", "hasattr", "enumerate",
        "zip", "map", "filter", "super", "self", "cls", "not", "and", "or", "return",
        "sum", "min", "max", "sorted", "any", "all", "repr", "abs", "round", "format",
    },
    "javascript": {
        "console", "Math", "JSON", "Object", "Array", "String", "Number", "Boolean",
        "Promise", "setTimeout", "setInterval", "parseInt", "parseFloat", "this", "keys",
        "values", "entries", "log",
    },
    "typescript": {"console", "Math", "JSON", "Object", "Array", "String", "Number", "Boolean", "Promise", "this"},
    "bash": {"echo", "printf", "cd", "export", "local", "return", "exit", "read", "test", "true", "false"},
    "go": {"fmt", "log", "panic", "len", "cap", "make", "new", "append", "copy", "delete", "println"},
    "rust": {"println", "println!", "print", "print!", "vec", "format", "format!", "unwrap", "none", "some", "eq", "ok", "err"},
}


def get_language(lang: str) -> tree_sitter.Language | None:
    return LANGUAGES.get(lang)


def parse_text(lang: str, text: str) -> tree_sitter.Tree | None:
    language = LANGUAGES.get(lang)
    if language is None:
        return None
    parser = tree_sitter.Parser()
    parser.language = language
    return parser.parse(text.encode("utf-8"))


def call_sites(tree: tree_sitter.Tree, lang: str) -> list[tuple[int, str]]:
    """Return [(line1_based, callee_name)] for every call site in the tree.

    tree-sitter 0.26: queries execute through QueryCursor(query).captures(node).
    """
    out: list[tuple[int, str]] = []
    for src in (CALL_QUERIES.get(lang), MEMBER_QUERIES.get(lang)):
        if not src:
            continue
        try:
            query = tree_sitter.Query(LANGUAGES[lang], src)
            caps = tree_sitter.QueryCursor(query).captures(tree.root_node)
        except Exception:  # noqa: BLE001 - grammar variations; skip this query
            continue
        for nodes in caps.values():
            for node in nodes:
                out.append((node.start_point[0] + 1, node.text.decode("utf-8", "replace")))
    return out