"""Architecture boundary tests (AD-2, AD-5).

1. Only `app.orchestration` may import `langgraph`.
2. Nothing outside a business module (other modules, orchestration, agents, platform, entry
   points) imports that module's `domain` or `adapters` package.

3. Nothing outside `app/platform/uow.py` calls `.commit(` (AD-25: only the edge commits,
   through the Unit of Work).
4. The `api` process never imports the job claim loop (`app.platform.jobs.runner`,
   `app.main_worker`): an import-linter contract, plus a runtime check below.

All rules are checked by an AST scan of `app/`. Rule 1 is also an import-linter contract
(`[tool.importlinter]` in pyproject.toml), which this test runs as well.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "app"
PRIVATE_LAYERS = {"domain", "adapters"}
COMMIT_ALLOWED = ("platform", "uow")
_LINT_IMPORTS = (
    "from importlinter.cli import lint_imports; raise SystemExit(lint_imports(no_cache=True))"
)


def _module_name(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path, root: Path) -> list[tuple[int, str]]:
    """Absolute names imported by a file, with relative imports resolved."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    module = _module_name(path, root)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base_parts = package.split(".")
                base = ".".join(base_parts[: len(base_parts) - (node.level - 1)])
                target = f"{base}.{node.module}" if node.module else base
            else:
                target = node.module or ""
            found.append((node.lineno, target))
            # `from app.modules.x import domain` imports the subpackage too.
            found.extend((node.lineno, f"{target}.{alias.name}") for alias in node.names)
    return found


def _commit_calls(path: Path) -> list[int]:
    """Line numbers of `<anything>.commit(...)` calls in a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "commit"
    ]


def find_violations(root: Path) -> list[str]:
    """Return human-readable boundary violations for the package rooted at `root`."""
    pkg = root.name
    violations: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        parts = _module_name(path, root).split(".")
        if tuple(parts[1:]) != COMMIT_ALLOWED:
            for lineno in _commit_calls(path):
                where = f"{path.relative_to(root.parent).as_posix()}:{lineno}"
                violations.add(f"{where} calls .commit( outside platform/uow.py")
        in_orchestration = parts[:2] == [pkg, "orchestration"]
        own_module = parts[2] if parts[:2] == [pkg, "modules"] and len(parts) > 2 else None
        for lineno, target in _imports(path, root):
            where = f"{path.relative_to(root.parent).as_posix()}:{lineno}"
            tparts = target.split(".")
            if tparts[0] == "langgraph" and not in_orchestration:
                violations.add(f"{where} imports langgraph outside orchestration")
            # Applies to every file outside the target module: other modules, orchestration,
            # agents, platform and entry points all go through application/public.py.
            if (
                tparts[:2] == [pkg, "modules"]
                and len(tparts) > 3
                and tparts[2] != own_module
                and tparts[3] in PRIVATE_LAYERS
            ):
                violations.add(
                    f"{where} imports {'.'.join(tparts[:4])} from outside module "
                    f"'{tparts[2]}' (use application/public.py)"
                )
    return sorted(violations)


def test_app_respects_boundaries() -> None:
    assert find_violations(APP_DIR) == []


def test_import_linter_contracts_kept() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _LINT_IMPORTS],
        cwd=APP_DIR.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_api_process_does_not_load_the_job_runner() -> None:
    probe = (
        "import sys, app.main_api; "
        "loaded = [m for m in ('app.platform.jobs.runner', 'app.main_worker') "
        "if m in sys.modules]; "
        "print(loaded); raise SystemExit(1 if loaded else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=APP_DIR.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --- the checker itself must catch violations ---------------------------------------------


def _write(root: Path, rel: str, body: str = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.fixture
def fake_app(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    for rel in (
        "__init__.py",
        "modules/__init__.py",
        "modules/a/__init__.py",
        "modules/a/application/__init__.py",
        "modules/a/domain/__init__.py",
        "modules/a/adapters/__init__.py",
        "modules/b/__init__.py",
        "modules/b/application/public.py",
        "modules/b/domain/__init__.py",
        "orchestration/__init__.py",
    ):
        _write(root, rel)
    return root


def test_checker_allows_legal_imports(fake_app: Path) -> None:
    _write(fake_app, "orchestration/graph.py", "import langgraph\nfrom langgraph.graph import X\n")
    _write(fake_app, "modules/a/application/svc.py", "from app.modules.b.application import x\n")
    _write(fake_app, "modules/a/adapters/repo.py", "from ..domain import thing\n")
    _write(fake_app, "modules/a/application/own.py", "from app.modules.a.domain import thing\n")
    _write(fake_app, "platform/uow.py", "async def f(s):\n    await s.commit()\n")
    assert find_violations(fake_app) == []


@pytest.mark.parametrize(
    ("rel", "body"),
    [
        ("modules/a/application/svc.py", "import langgraph\n"),
        ("agents/x/agent.py", "from langgraph.graph import StateGraph\n"),
        ("platform/thing.py", "import langgraph.graph\n"),
        ("modules/a/application/svc.py", "from app.modules.b.domain import model\n"),
        ("modules/a/application/svc.py", "import app.modules.b.adapters.repo\n"),
        ("modules/a/application/svc.py", "from app.modules.b import domain\n"),
        ("modules/a/application/svc.py", "from ...b.domain import model\n"),
        ("orchestration/graph.py", "from app.modules.b.domain import model\n"),
        ("agents/x/agent.py", "import app.modules.b.adapters\n"),
        ("main_api.py", "from app.modules.b import adapters\n"),
        ("modules/a/application/svc.py", "async def f(uow):\n    await uow.session.commit()\n"),
        ("platform/trace/writer.py", "def f(conn):\n    conn.commit()\n"),
        ("main_api.py", "async def f(s):\n    await s.commit()\n"),
    ],
)
def test_checker_flags_violations(fake_app: Path, rel: str, body: str) -> None:
    _write(fake_app, rel, body)
    assert find_violations(fake_app) != []
