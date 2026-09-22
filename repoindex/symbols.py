"""Tree-sitter based symbol extraction.

Returns symbol records {name, kind, start_line, end_line, signature} for a source text.
Unknown languages return []. Uses the 0.26 tree-sitter API.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import tree_sitter

from repoindex import ts

_DEF_KINDS = {
    "python": {"function_definition", "class_definition"},
    "javascript": {
        "function_declaration",
        "class_declaration",
        "method_definition",
        "lexical_declaration",
        "generator_function_declaration",
    },
    "typescript": {
        "function_declaration",
        "class_declaration",
        "interface_declaration",
        "type_alias_declaration",
        "method_definition",
        "function_signature",
        "method_signature",
        "lexical_declaration",
    },
    "bash": {"function_definition"},
    "go": {"function_declaration", "method_declaration", "type_declaration"},
    "rust": {
        "function_item",
        "struct_item",
        "enum_item",
        "trait_item",
        "impl_item",
        "mod_item",
        "type_item",
    },
}

_NAME_CHILD_KINDS = ("identifier", "type_identifier", "property_identifier", "field_identifier")


@dataclass
class Symbol:
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str

    def to_dict(self) -> dict:
        return asdict(self)


def _name_of(node: tree_sitter.Node) -> str | None:
    nb = node.child_by_field_name("name")
    if nb is not None:
        return nb.text.decode("utf-8", "replace")
    if node.type == "lexical_declaration":
        for child in node.named_children:
            if child.type == "variable_declarator":
                name_node = child.child_by_field_name("name")
                if name_node is not None:
                    return name_node.text.decode("utf-8", "replace")
    for child in node.named_children:
        if child.type in _NAME_CHILD_KINDS:
            return child.text.decode("utf-8", "replace")
    return None


def _signature(node: tree_sitter.Node, source_lines: list[str]) -> str:
    start, end = node.start_point[0], node.end_point[0]
    end = min(end, start + 11)
    snippet = "\n".join(source_lines[start:end + 1])
    return snippet[:1200]


def extract_symbols(language: str, source_text: str) -> list[Symbol]:
    tree = ts.parse_text(language, source_text)
    if tree is None:
        return []
    kinds = _DEF_KINDS[language]
    source_lines = source_text.splitlines()
    out: list[Symbol] = []

    def walk(node: tree_sitter.Node) -> None:
        if node.type in kinds:
            name = _name_of(node)
            if name:
                kind = "function" if "function" in node.type else node.type
                out.append(Symbol(
                    name=name,
                    kind=kind,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=_signature(node, source_lines),
                ))
            if node.type == "lexical_declaration":
                for child in node.named_children:
                    if child.type in ("function", "arrow_function") and _name_of(child):
                        out.append(Symbol(
                            name=_name_of(child) or name,
                            kind="function",
                            start_line=child.start_point[0] + 1,
                            end_line=child.end_point[0] + 1,
                            signature=_signature(child, source_lines),
                        ))
                return
        for child in node.named_children:
            walk(child)

    walk(tree.root_node)
    return out