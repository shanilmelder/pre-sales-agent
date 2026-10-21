"""`make eval-retrieval` (Story 3.3): the cases in `evals/knowledge/` load, the pure scoring,
the report, the refusals, and a full run in the eval database with a fake embedding gateway
(skipped without `PSA_EVAL_DATABASE_URL` / `PSA_EVAL_MIGRATIONS_DATABASE_URL`; the run resets
that database)."""

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.evals import __main__ as cli
from app.evals import harness, retrieval
from app.platform.config import Settings, get_settings
from app.platform.model_gateway.port import EmbedRequest
from tests.conftest import run_async
from tests.test_knowledge_embedding import fake_vector


def test_the_cases_load_and_every_query_names_a_listed_source() -> None:
    cases = retrieval.load_cases()
    assert cases.k == 5 and len(cases.sources) == 4 and len(cases.queries) == 10
    files = {s.file for s in cases.sources}
    for query in cases.queries:
        assert query.source in files
        source = next(s for s in cases.sources if s.file == query.source)
        assert retrieval.normalized(query.contains) in retrieval.normalized(source.data.decode())


def _write(tmp_path: Path, text: str, files: dict[str, str] | None = None) -> Path:
    (tmp_path / "sources").mkdir(exist_ok=True)
    for name, body in (files or {"a.md": "# A\n\nport 1\n"}).items():
        (tmp_path / "sources" / name).write_text(body, encoding="utf-8")
    (tmp_path / "cases.yaml").write_text(text, encoding="utf-8")
    return tmp_path


SOURCE = "sources:\n  - {file: a.md, title: A, product: P, product_version: 1}\n"


@pytest.mark.parametrize(
    "text",
    [
        "- not a mapping\n",
        "k: 0\n" + SOURCE + "queries:\n  - {id: q, query: x, source: a.md, contains: p}\n",
        SOURCE + "queries:\n  - {id: q, query: x, source: b.md, contains: p}\n",
        SOURCE + "queries: []\n",
        "sources:\n  - {file: missing.md, title: A, product: P, product_version: 1}\n",
        SOURCE
        + "queries:\n  - {id: q, query: x, source: a.md, contains: p}\n"
        + "  - {id: q, query: y, source: a.md, contains: p}\n",
    ],
)
def test_malformed_cases_are_refused(tmp_path: Path, text: str) -> None:
    with pytest.raises(retrieval.CaseError):
        retrieval.load_cases(_write(tmp_path, text))


def test_scoring_and_the_report() -> None:
    hits = [retrieval.Hit("s1", "Other"), retrieval.Hit("s2", "Open PORT\n  4711")]
    assert retrieval.first_hit_rank(hits, "s2", "port 4711") == 2
    assert retrieval.first_hit_rank(hits, "s1", "port 4711") is None
    assert retrieval.ratio(1, 4) == 0.25 and retrieval.ratio(0, 0) is None
    report = {
        "query_count": 2,
        "source_count": 1,
        "profile": "bge-m3",
        "k": 5,
        "hits": 1,
        "hit_rate_at_k": 0.5,
        "citations": 4,
        "valid_citations": 4,
        "citation_validity": 1.0,
        "queries": [{"id": "a", "hit": True}, {"id": "b", "hit": False}],
        "sources_not_ready": {},
        "errors": {},
    }
    text = retrieval.render(report)
    assert "hit rate at 5:    50% (1/2)" in text
    assert "citation validity: 100% (4/4)" in text
    assert "miss: b" in text


def test_the_cli_refuses_without_an_eval_database(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("PSA_EVAL_DATABASE_URL", raising=False)
    monkeypatch.delenv("PSA_EVAL_MIGRATIONS_DATABASE_URL", raising=False)
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(_env_file=None))  # type: ignore[call-arg]
    assert cli.main(["retrieval"]) == cli.EXIT_REFUSED
    assert "Eval refused" in capsys.readouterr().err


class EmbedOnlyGateway:
    """Embeds with `fake_vector`; no chat, no call rows."""

    def __init__(self) -> None:
        self.texts = 0

    async def complete_structured(self, request: Any) -> Any:
        raise AssertionError("the retrieval eval makes no chat calls")

    async def embed(self, request: EmbedRequest) -> list[list[float]]:
        self.texts += len(request.texts)
        return [fake_vector(t) for t in request.texts]


@pytest.fixture
def eval_settings(
    db_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Settings]:
    url = os.environ.get("PSA_EVAL_DATABASE_URL")
    owner = os.environ.get("PSA_EVAL_MIGRATIONS_DATABASE_URL")
    if not url or not owner:
        pytest.skip("PSA_EVAL_DATABASE_URL / PSA_EVAL_MIGRATIONS_DATABASE_URL not set")
    get_settings.cache_clear()
    yield Settings(database_url=db_url, eval_database_url=url, eval_migrations_database_url=owner)
    get_settings.cache_clear()


def test_a_run_scores_every_query_and_every_citation_resolves(
    eval_settings: Settings, tmp_path: Path
) -> None:
    gateway = EmbedOnlyGateway()
    outcome = run_async(
        retrieval.run_retrieval_eval(
            eval_settings, gateway=gateway, out_dir=tmp_path / "out", poll_s=0.2, timeout_s=300
        )
    )
    report = outcome.report
    assert report["sources_not_ready"] == {} and report["errors"] == {}
    assert report["query_count"] == 10 and report["citations"] > 0
    assert report["citation_validity"] == 1.0  # every returned reference resolves
    assert report["hit_rate_at_k"] is not None and report["hit_rate_at_k"] >= 0.8
    assert gateway.texts > 10
    stored = json.loads((outcome.out_dir / "report.json").read_text(encoding="utf-8"))
    assert stored["hits"] == report["hits"]


def test_the_retrieval_eval_never_runs_against_the_main_database(db_url: str) -> None:
    settings = Settings(
        database_url=db_url, eval_database_url=db_url, eval_migrations_database_url=db_url
    )
    with pytest.raises(harness.EvalRefusedError):
        run_async(retrieval.run_retrieval_eval(settings))
