"""Read-only compatibility checks for databases created before Alembic."""

import sys
import argparse

from sqlalchemy import inspect

from app.database import Base, engine
from app.models import chat, node, relationship, source, tag, user  # noqa: F401


class SchemaCompatibilityError(RuntimeError):
    """Raised when an existing database cannot safely be Alembic-stamped."""


def schema_differences(database_engine, *, baseline_only=False) -> list[str]:
    """Return missing current-metadata tables or columns without modifying the DB."""
    inspector = inspect(database_engine)
    existing_tables = set(inspector.get_table_names())
    differences = []
    if baseline_only and "index_jobs" in existing_tables:
        differences.append("index_jobs already exists; validate current schema instead")

    for table in Base.metadata.sorted_tables:
        if baseline_only and table.name == "index_jobs":
            continue
        if table.name not in existing_tables:
            differences.append(f"missing table: {table.name}")
            continue

        existing_columns = {
            column["name"] for column in inspector.get_columns(table.name)
        }
        for column in table.columns:
            if column.name not in existing_columns:
                differences.append(f"missing column: {table.name}.{column.name}")

    return differences


def validate_existing_schema(database_engine, *, baseline_only=False) -> None:
    """Fail if the database differs from the current metadata schema."""
    differences = schema_differences(database_engine, baseline_only=baseline_only)
    if differences:
        raise SchemaCompatibilityError("; ".join(differences))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-only", action="store_true", help="只核验尚未有 index_jobs 的20260712基线")
    args = parser.parse_args()
    try:
        validate_existing_schema(engine, baseline_only=args.baseline_only)
    except SchemaCompatibilityError as exc:
        print(f"Schema is incompatible: {exc}", file=sys.stderr)
        return 1

    revision = "20260712_01" if args.baseline_only else "20261014_02"
    print(f"Schema shape matches {revision}; confirm migration history before stamping. No DDL performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
