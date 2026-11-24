"""生产层不得反向依赖评测包；检索核心必须留在 app 内。"""

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_app_does_not_import_eval_package():
    offenders = []
    for path in (BACKEND / "app").rglob("*.py"):
        modules = _imported_modules(path)
        bad = sorted(
            name for name in modules
            if name == "eval" or name.startswith("eval.")
        )
        if bad:
            offenders.append(f"{path.relative_to(BACKEND)} -> {bad}")
    assert offenders == []


def test_retrieval_pipeline_uses_app_core_not_eval():
    path = BACKEND / "app" / "services" / "retrieval_pipeline.py"
    modules = _imported_modules(path)
    assert "app.services.retrieval_core" in modules
    assert not any(name == "eval" or name.startswith("eval.") for name in modules)


def test_retrieval_core_is_standalone():
    path = BACKEND / "app" / "services" / "retrieval_core.py"
    modules = _imported_modules(path)
    assert not any(name == "app" or name.startswith("app.") for name in modules)
    assert not any(name == "eval" or name.startswith("eval.") for name in modules)


def test_eval_retrieval_candidates_reexports_the_core_types():
    from app.services import retrieval_core
    from eval import retrieval_candidates

    for name in (
        "BM25Retriever", "CandidateChunk", "RankedChunk", "dense_rank",
        "pack_context", "reciprocal_rank_fusion", "rerank_candidates",
    ):
        assert getattr(retrieval_candidates, name) is getattr(retrieval_core, name)