# Alembic Baseline Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox ([ ]) syntax for tracking.

**Goal:** Replace runtime schema creation with an Alembic baseline migration that safely supports both fresh and existing databases.

**Architecture:** The first revision creates the current metadata for empty databases. A read-only schema validator decides whether an existing database may be stamped to that revision without DDL. Deployment and local launchers run Alembic before the application process; FastAPI itself never performs schema creation.

**Tech Stack:** Alembic, SQLAlchemy 2.x, FastAPI, SQLite, MySQL, pytest, Docker Compose.

---

## File map

| Path | Responsibility |
|---|---|
| backend/alembic/versions/20260712_01_initial_schema.py | Initial reversible schema revision. |
| backend/app/schema_validation.py | Read-only compatibility check and command-line entry point for legacy databases. |
| backend/tests/test_migrations.py | Fresh upgrade, safe legacy stamp, and incompatible-schema tests. |
| backend/app/main.py | Removes runtime Base.metadata.create_all. |
| Dockerfile | Upgrades to head once before Uvicorn worker startup. |
| backend/migrate_to_mysql.py | Uses Alembic upgrade instead of metadata create_all. |
| backend/launcher.py and start.bat | Run explicit local migration before launching the backend. |
| README.md and README_zh.md | Document fresh setup, existing-database adoption, and rollback limits. |

### Task 1: Add read-only legacy schema validation

**Files:**
- Create: backend/app/schema_validation.py
- Create: backend/tests/test_migrations.py

- [ ] **Step 1: Write failing validator tests**

    from sqlalchemy import create_engine, text
    from app.database import Base
    from app.models import chat, node, relationship, source, tag, user
    from app.schema_validation import SchemaCompatibilityError, validate_existing_schema

    def test_validator_accepts_schema_created_from_current_metadata(tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
        Base.metadata.create_all(engine)
        validate_existing_schema(engine)

    def test_validator_reports_missing_table_without_writing_version_table(tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'incomplete.db'}")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        with pytest.raises(SchemaCompatibilityError, match="knowledge_nodes"):
            validate_existing_schema(engine)
        assert "alembic_version" not in inspect(engine).get_table_names()

- [ ] **Step 2: Confirm the red test**

Run: backend\venv\Scripts\python.exe -m pytest backend\tests\test_migrations.py -q --tb=short

Expected: collection fails because app.schema_validation does not exist.

- [ ] **Step 3: Implement the validator without DDL**

Create backend/app/schema_validation.py:

    import sys
    from sqlalchemy import inspect
    from app.database import Base, engine
    from app.models import chat, node, relationship, source, tag, user

    class SchemaCompatibilityError(RuntimeError):
        pass

    def schema_differences(database_engine) -> list[str]:
        inspector = inspect(database_engine)
        existing_tables = set(inspector.get_table_names())
        differences = []
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                differences.append(f"missing table: {table.name}")
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing_columns:
                    differences.append(f"missing column: {table.name}.{column.name}")
        return differences

    def validate_existing_schema(database_engine) -> None:
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

- [ ] **Step 4: Verify validator behavior**

Run: backend\venv\Scripts\python.exe -m pytest backend\tests\test_migrations.py -q --tb=short

Expected: a current legacy schema passes; an incomplete schema reports missing tables and has no alembic_version table.

- [ ] **Step 5: Commit checkpoint**

    git add backend/app/schema_validation.py backend/tests/test_migrations.py
    git commit -m "feat: validate legacy database schemas"

### Task 2: Create and test the initial Alembic revision

**Files:**
- Create: backend/alembic/versions/20260712_01_initial_schema.py
- Modify: backend/tests/test_migrations.py

- [ ] **Step 1: Add a fresh-database migration smoke test**

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text

    def alembic_config(database_url):
        config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", database_url)
        return config

    def test_upgrade_creates_schema_and_records_head(tmp_path):
        database_url = f"sqlite:///{tmp_path / 'fresh.db'}"
        command.upgrade(alembic_config(database_url), "head")
        engine = create_engine(database_url)
        tables = set(inspect(engine).get_table_names())
        assert {"users", "knowledge_nodes", "tags", "relationships", "sources",
                "conversations", "messages", "node_tags", "message_sources"} <= tables
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260712_01"

- [ ] **Step 2: Confirm the fresh-upgrade test is red**

Run: backend\venv\Scripts\python.exe -m pytest backend\tests\test_migrations.py::test_upgrade_creates_schema_and_records_head -q

Expected: Alembic cannot upgrade because no revision exists.

- [ ] **Step 3: Write the baseline revision explicitly**

Create backend/alembic/versions/20260712_01_initial_schema.py with revision identifiers:

    revision = "20260712_01"
    down_revision = None
    branch_labels = None
    depends_on = None

In upgrade, create tables in this order: users, sources, tags, knowledge_nodes, node_tags, relationships, conversations, messages, message_sources. Use the same SQLAlchemy names, types, nullable flags, unique constraint uq_tag_user_name, indexes, foreign keys, and message-source ondelete CASCADE constraints declared by current models.

The users table definition must include every currently stored credential field so fresh environments match the running model:

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("ai_api_key", sa.String(length=500), nullable=True),
        sa.Column("ai_base_url", sa.String(length=500), nullable=True),
        sa.Column("ai_model_name", sa.String(length=100), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
        sa.UniqueConstraint("email"),
    )

Create matching indexes for each model field declared with index=True. In downgrade, drop message_sources, messages, conversations, relationships, node_tags, knowledge_nodes, tags, sources, and users in reverse dependency order.

- [ ] **Step 4: Add a legacy adoption test**

    def test_stamp_preserves_existing_data(tmp_path):
        database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
        engine = create_engine(database_url)
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users (username, hashed_password, is_admin) VALUES ('existing', 'hash', 0)"
            ))
        validate_existing_schema(engine)
        command.stamp(alembic_config(database_url), "20260712_01")
        with engine.connect() as connection:
            assert connection.execute(text("SELECT username FROM users")).scalar_one() == "existing"
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260712_01"

- [ ] **Step 5: Run all migration tests**

Run: backend\venv\Scripts\python.exe -m pytest backend\tests\test_migrations.py -q --tb=short

Expected: fresh upgrade creates the schema, legacy stamp preserves rows, and incompatible schema validation remains read-only.

- [ ] **Step 6: Commit checkpoint**

    git add backend/alembic/versions/20260712_01_initial_schema.py backend/tests/test_migrations.py
    git commit -m "feat: add initial Alembic schema revision"

### Task 3: Remove runtime schema creation and migrate deployment tools

**Files:**
- Modify: backend/app/main.py
- Modify: Dockerfile
- Modify: backend/migrate_to_mysql.py

- [ ] **Step 1: Add a failing source-level guard**

Append this test to backend/tests/test_migrations.py:

    def test_application_source_does_not_create_schema_at_runtime():
        main_source = (Path(__file__).parents[1] / "app" / "main.py").read_text(encoding="utf-8")
        assert "Base.metadata.create_all" not in main_source

- [ ] **Step 2: Confirm the guard is red**

Run: backend\venv\Scripts\python.exe -m pytest backend\tests\test_migrations.py::test_application_source_does_not_create_schema_at_runtime -q

Expected: failure identifies the current FastAPI lifespan create_all call.

- [ ] **Step 3: Move DDL responsibility to Alembic commands**

In backend/app/main.py, remove Base and engine imports and leave lifespan as:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.validate_runtime()
        yield

Replace the Docker command with a single migration-before-server command:

    CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8766 --workers 2"]

Replace migrate_to_mysql.py create_tables implementation with a function that configures backend/alembic.ini, overrides sqlalchemy.url with the selected MySQL URL, and executes command.upgrade(config, "head"). It must not import Base, create an engine, or call Base.metadata.create_all.

- [ ] **Step 4: Verify migration responsibilities**

Run: backend\venv\Scripts\python.exe -m pytest backend\tests\test_migrations.py -q --tb=short

Expected: no runtime create_all exists; all schema DDL paths use Alembic.

- [ ] **Step 5: Commit checkpoint**

    git add backend/app/main.py Dockerfile backend/migrate_to_mysql.py backend/tests/test_migrations.py
    git commit -m "refactor: run schema changes through Alembic"

### Task 4: Make local launchers migrate explicitly

**Files:**
- Modify: backend/launcher.py
- Modify: start.bat
- Modify: backend/tests/test_migrations.py

- [ ] **Step 1: Add launcher migration-order test**

    def test_desktop_launcher_runs_migrations_before_importing_app():
        source = (Path(__file__).parents[1] / "launcher.py").read_text(encoding="utf-8")
        start_server = source.index("def start_server")
        assert source.index("run_database_migrations()", start_server) < source.index(
            "from app.main import app", start_server
        )

- [ ] **Step 2: Confirm the test is red**

Run: backend\venv\Scripts\python.exe -m pytest backend\tests\test_migrations.py::test_desktop_launcher_runs_migrations_before_importing_app -q

Expected: failure because launcher imports app without migration.

- [ ] **Step 3: Add explicit launcher commands**

In backend/launcher.py, create run_database_migrations that builds an Alembic Config from the backend-local alembic.ini and runs command.upgrade(config, "head"). Call it as the first statement in start_server before importing app.

In start.bat, replace the backend launch command with:

    start "Backend" cmd /c "venv\Scripts\python.exe -m alembic upgrade head && venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8766"

- [ ] **Step 4: Verify launcher tests and migration tests**

Run: backend\venv\Scripts\python.exe -m pytest backend\tests\test_migrations.py -q --tb=short

Expected: desktop and batch launch paths request migration before server startup.

- [ ] **Step 5: Commit checkpoint**

    git add backend/launcher.py start.bat backend/tests/test_migrations.py
    git commit -m "fix: migrate schema before local startup"

### Task 5: Document the migration runbook and verify delivery

**Files:**
- Modify: README.md
- Modify: README_zh.md
- Verify: backend/tests, frontend, Dockerfile

- [ ] **Step 1: Add documented fresh and existing database commands**

Document these production-safe commands in both READMEs:

    # Fresh database
    cd backend
    python -m alembic upgrade head

    # Existing database created by older releases
    python -m app.schema_validation
    python -m alembic stamp 20260712_01

State that stamp is valid only after validation succeeds, and that rollback of a populated production database requires a backup and an approved runbook.

- [ ] **Step 2: Run migration and application verification**

Run: backend\venv\Scripts\python.exe -m pytest backend\tests\test_migrations.py -q --tb=short

Run: backend\venv\Scripts\python.exe -m pytest backend\tests -q --tb=short

Run from frontend: npm run build

Expected: migration tests pass, backend suite passes, and the production frontend bundle builds.

- [ ] **Step 3: Perform migration diff and safety review**

Run: git diff --check; git status --short

Review these exact conditions:

    1. No non-test production source calls Base.metadata.create_all.
    2. The only destructive downgrade is isolated to the initial revision and documented as unsuitable for populated production databases.
    3. Existing-database validation performs no DDL before alembic stamp.
    4. Docker invokes alembic before the Uvicorn worker process.
    5. MySQL and SQLite configuration remain environment-driven and do not introduce credentials into tracked files.

- [ ] **Step 4: Commit verified documentation**

    git add README.md README_zh.md
    git commit -m "docs: add safe database migration runbook"
