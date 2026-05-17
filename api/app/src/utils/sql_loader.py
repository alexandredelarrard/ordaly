from pathlib import Path


def load_sql(relative_path: str) -> str:
    """Load a .sql file from ``src/sql_queries``."""
    base = Path(__file__).resolve().parent.parent / "sql_queries"
    path = base / relative_path
    if not path.is_file():
        raise FileNotFoundError(f"SQL file not found: {path}")
    return path.read_text(encoding="utf-8")
