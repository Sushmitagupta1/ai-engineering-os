"""repoindex — M1 repository ingestion engine.

Walks a repo, extracts symbol-level structure with tree-sitter, chunks files, stores an
SQLite index, and can enrich chunks with free-model summaries.
"""

__version__ = "0.1.0"