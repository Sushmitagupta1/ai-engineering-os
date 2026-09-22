"""Detection of repo files and language classification."""

from __future__ import annotations

from pathlib import Path

# extension -> canonical language name
EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".swift": "swift",
    ".sql": "sql",
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".scss": "scss",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".xml": "xml",
    ".dockerfile": "dockerfile",
}

# languages we can parse symbols for with tree-sitter
TREE_SITTER_LANGS = {"python", "javascript", "typescript", "bash", "rust", "go"}

# directories never indexed
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".os",
    ".idea",
    ".vscode",
    "target",
    "pgdata",
}

IGNORED_FILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "Cargo.lock"}


def lang_for(path: str | Path) -> str | None:
    name = Path(path).name.lower()
    if name in IGNORED_FILES:
        return None
    if name in (".dockerfile",) or name.endswith(".dockerfile"):
        return "dockerfile"
    return EXT_TO_LANG.get(Path(path).suffix.lower())


def is_indexable(path: str | Path) -> bool:
    return lang_for(path) is not None


def default_ignore(repo_root: str | Path) -> set[str]:
    return IGNORED_DIRS