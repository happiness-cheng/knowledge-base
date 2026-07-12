"""Read-only compatibility checks for databases created before Alembic."""

import sys

from sqlalchemy import inspect

from app.database import Base, engine
from app.models import chat, node, relationship, source, tag, user  # noqa: F401


class SchemaCompatibilityError(RuntimeError):
    """Raised when an existing database cannot safely be Alembic-stamped."""


def schema_differences(database_engine) -> list[str]:
    """Return missing current-metadata tables or columns without modifying the DB."""
    inspector = inspect(database_engine)
    existing_tables = set(inspector.get_table_names())
    differences = []

    for table in Base.metadata.sorted_tables:
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


def validate_existing_schema(database_engine) -> None:
    """Fail if the database differs from the current metadata schema."""
    differences = schema_differences(database_engine)
    if differences:
        raise SchemaCompatibilityError("; ".join(differences))


def main() -> int:
    try:
        validate_existing_schema(engine)
    except SchemaCompatibilityError as exc:
        print(f"Schema is incompatible: {exc}", file=sys.stderr)
        return 1

    print("Schema is compatible; it is safe to run alembic stamp 20260712_01")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
