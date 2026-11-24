"""可移植入口不得硬编码个人绝对路径。

历史一次性诊断脚本不在本测试的“可移植入口”范围内；生产代码与 README/CI
实际引用的离线入口必须能从任意检出目录运行。
"""

from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]

ACTIVE_EVAL_ENTRYPOINTS = (
    "benchmark.py",
    "core_corpus.py",
    "offline_tests.py",
    "retrieval_candidates.py",
    "run_benchmark.py",
    "run_core_rag_comparison.py",
    "run_context_matrix.py",
    "run_native_rag_validation.py",
    "run_retrieval_matrix.py",
    "run_slice_comparison.py",
    "generation_eval.py",
    "run_generation_eval.py",
)


def _files() -> list[Path]:
    files = list((BACKEND / "app").rglob("*.py"))
    files.extend(BACKEND / "eval" / name for name in ACTIVE_EVAL_ENTRYPOINTS)
    return [path for path in files if path.is_file()]


def test_active_code_has_no_personal_absolute_paths():
    needles = ("C:/Users/", "C:\\Users\\", "/Users/", "\\Users\\")
    offenders = []
    for path in _files():
        text = path.read_text(encoding="utf-8")
        for needle in needles:
            if needle in text:
                offenders.append(f"{path.relative_to(BACKEND)} contains {needle!r}")
                break
    assert offenders == []


def test_generation_eval_uses_repository_relative_base():
    path = BACKEND / "eval" / "generation_eval.py"
    text = path.read_text(encoding="utf-8")
    assert "Path(__file__).resolve().parents[1]" in text
    assert "C:/Users" not in text