"""`make eval-retrieval` (Story 3.3): hit rate at k and citation validity of Knowledge search.

`evals/knowledge/cases.yaml` lists synthetic Knowledge Sources (files under
`evals/knowledge/sources/`) and questions, each with the Source that answers it and a phrase
the answering passage contains. The runner:

1. **Refuses** (exit 2) unless the eval database URLs are set and differ from the main
   database (as `make eval`), or when the cases don't fit the format.
2. **Resets** the eval database (`alembic downgrade base`, `upgrade head`) and uses a
   temporary file store.
3. **Registers** one Integration Type and every Source there through `knowledge`'s public API,
   then runs the worker loop until `knowledge.parse_source` and `knowledge.embed_source` are
   done, through the real ModelGateway (`PSA_MODEL_PROFILE_EMBED`, needs `ollama pull bge-m3`).
4. **Searches** each question (`knowledge.search`, top k, `background` priority) and scores:
   - *hit rate at k*: the share of questions with a passage of the expected Source containing
     the phrase (ignoring case and line breaks) among the top k;
   - *citation validity*: the share of returned Evidence references that resolve
     (`knowledge.check_chunk_refs`) and whose span slices the version's stored extracted text
     to exactly the returned passage.
5. **Writes** `evals/out/retrieval-<timestamp>/report.json` and prints a summary. Nothing is
   stored in the main database and there is no gate.
"""

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy.ext.asyncio import AsyncEngine

from app.evals import harness
from app.modules.knowledge.application import public as knowledge
from app.platform.config import Settings
from app.platform.db import create_engine
from app.platform.logging import get_logger
from app.platform.model_gateway.gateway import ModelGateway
from app.platform.model_gateway.port import ModelGatewayPort
from app.platform.storage import BlobStore
from app.platform.uow import unit_of_work

_log = get_logger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]
CASES_DIR = BACKEND_DIR.parent / "evals" / "knowledge"
OUT_DIR = BACKEND_DIR.parent / "evals" / "out"
JOB_TYPES = frozenset({"knowledge.parse_source", "knowledge.embed_source"})
DEFAULT_TIMEOUT_S = 1800.0


class CaseError(ValueError):
    """`cases.yaml` doesn't fit the format (module docstring)."""


@dataclass(frozen=True, slots=True)
class SourceCase:
    file: str
    title: str
    product: str
    product_version: str
    data: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class QueryCase:
    id: str
    query: str = field(repr=False)
    source: str
    contains: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class Cases:
    k: int
    sources: tuple[SourceCase, ...]
    queries: tuple[QueryCase, ...]


@dataclass(frozen=True, slots=True)
class RetrievalOutcome:
    report: dict[str, Any]
    out_dir: Path


def _str(raw: Mapping[str, Any], key: str, where: str) -> str:
    value = raw.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str) or not value.strip():
        raise CaseError(f"{where}: `{key}` must be a non-empty string")
    return value.strip()


def load_cases(cases_dir: Path = CASES_DIR) -> Cases:
    path = cases_dir / "cases.yaml"
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CaseError(f"{path}: {type(exc).__name__}") from None
    if not isinstance(raw, dict):
        raise CaseError(f"{path}: expected a mapping")
    k = raw.get("k", knowledge.SEARCH_K_DEFAULT)
    if not isinstance(k, int) or not 1 <= k <= knowledge.SEARCH_K_MAX:
        raise CaseError(f"{path}: `k` must be an integer 1-{knowledge.SEARCH_K_MAX}")
    sources: list[SourceCase] = []
    for index, item in enumerate(raw.get("sources") or []):
        where = f"sources[{index}]"
        if not isinstance(item, dict):
            raise CaseError(f"{where}: expected a mapping")
        name = _str(item, "file", where)
        file = cases_dir / "sources" / name
        if file.parent != cases_dir / "sources" or not file.is_file():
            raise CaseError(f"{where}: no file sources/{name}")
        sources.append(
            SourceCase(
                file=name,
                title=_str(item, "title", where),
                product=_str(item, "product", where),
                product_version=_str(item, "product_version", where),
                data=file.read_bytes(),
            )
        )
    names = {s.file for s in sources}
    if len(names) != len(sources) or not sources:
        raise CaseError(f"{path}: `sources` must list distinct files, at least one")
    queries: list[QueryCase] = []
    for index, item in enumerate(raw.get("queries") or []):
        where = f"queries[{index}]"
        if not isinstance(item, dict):
            raise CaseError(f"{where}: expected a mapping")
        case = QueryCase(
            id=_str(item, "id", where),
            query=_str(item, "query", where),
            source=_str(item, "source", where),
            contains=_str(item, "contains", where),
        )
        if case.source not in names:
            raise CaseError(f"{where}: `source` {case.source!r} is not listed under sources")
        queries.append(case)
    if not queries or len({q.id for q in queries}) != len(queries):
        raise CaseError(f"{path}: `queries` must have distinct ids, at least one")
    return Cases(k=k, sources=tuple(sources), queries=tuple(queries))


# --- scoring (pure) -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Hit:
    source_id: str
    text: str = field(repr=False)


def normalized(text: str) -> str:
    """Case-folded, with every run of whitespace a single space."""
    return " ".join(text.split()).casefold()


def first_hit_rank(hits: Sequence[Hit], source_id: str, contains: str) -> int | None:
    """The 1-based rank of the first hit from `source_id` containing `contains` (ignoring
    case and how whitespace is laid out), or None."""
    wanted = normalized(contains)
    for rank, hit in enumerate(hits, start=1):
        if hit.source_id == source_id and wanted in normalized(hit.text):
            return rank
    return None


def ratio(part: int, whole: int) -> float | None:
    return None if whole == 0 else part / whole


# --- the run ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _Ref:
    kind: str
    id: UUID
    version: int | None
    span: _Span | None


async def _register(
    db: AsyncEngine, settings: Settings, cases: Cases, principal: Any
) -> dict[str, str]:
    """Register the Sources; file name → Source id."""
    store = BlobStore(settings.storage_dir)
    async with unit_of_work(db) as uow:
        entry = await knowledge.create_entry(
            uow,
            principal,
            knowledge.NewEntry(
                kind="integration_type",
                code="EVAL-DOCS",
                name="Eval documentation",
                definition="Synthetic documentation for the retrieval eval.",
            ),
        )
    ids: dict[str, str] = {}
    for source in cases.sources:
        async with unit_of_work(db) as uow:
            registered = await knowledge.register_source(
                uow,
                principal,
                harness.Upload(source.file, source.data),
                title=source.title,
                product=source.product,
                product_version=source.product_version,
                integration_type_ids=[entry.id],
                owner_id=None,
                store=store,
                max_bytes=settings.upload_max_bytes,
                content_length=None,
                stale_months=settings.knowledge_stale_months,
            )
        ids[source.file] = registered.id
    return ids


async def _not_ready(db: AsyncEngine, settings: Settings, principal: Any) -> dict[str, str]:
    """Source id → its state, for every Source that isn't Ready."""
    async with unit_of_work(db) as uow:
        listed = await knowledge.list_sources(
            uow,
            principal,
            product=None,
            integration_type_id=None,
            owner_id=None,
            stale=None,
            include_retired=True,
            stale_months=settings.knowledge_stale_months,
        )
    states: dict[str, str] = {}
    for source in listed.items:
        if source.embed is None or source.embed.status != knowledge.EmbedStatus.READY:
            parse = source.parse.status.value
            embed = "none" if source.embed is None else source.embed.status.value
            code = (source.embed and source.embed.error_code) or source.parse.error_code
            states[source.id] = f"parse {parse}, embed {embed}" + (
                f" ({code.value})" if code else ""
            )
    return states


async def _score(
    db: AsyncEngine,
    settings: Settings,
    cases: Cases,
    ids: Mapping[str, str],
    gateway: ModelGatewayPort,
    principal: Any,
) -> tuple[list[dict[str, Any]], int, int, dict[str, str]]:
    store = BlobStore(settings.storage_dir)
    per_query: list[dict[str, Any]] = []
    citations = valid = 0
    errors: dict[str, str] = {}
    texts: dict[tuple[str, int], str] = {}
    for case in cases.queries:
        async with unit_of_work(db) as uow:
            try:
                result = await knowledge.search(
                    uow,
                    principal,
                    case.query,
                    gateway=gateway,
                    embed_profile=settings.model_profile_embed,
                    stale_months=settings.knowledge_stale_months,
                    k=cases.k,
                    priority="background",
                )
            except Exception as exc:  # a failed query counts as a miss
                errors[case.id] = type(exc).__name__
                per_query.append({"id": case.id, "hit": False, "rank": None, "returned": 0})
                continue
            hits = [Hit(i.source_id, i.text) for i in result.items]
            refs = [
                _Ref(
                    kind=i.evidence.kind,
                    id=UUID(i.evidence.id),
                    version=i.evidence.version,
                    span=_Span(i.evidence.span.start, i.evidence.span.end),
                )
                for i in result.items
            ]
            reasons = await knowledge.check_chunk_refs(uow, refs)
            for item, reason in zip(result.items, reasons, strict=True):
                citations += 1
                key = (item.source_id, item.version)
                if key not in texts:
                    stored = await knowledge.read_text(
                        uow, principal, UUID(item.source_id), item.version, store=store
                    )
                    texts[key] = stored.text
                span = item.evidence.span
                if reason is None and texts[key][span.start : span.end] == item.text:
                    valid += 1
        rank = first_hit_rank(hits, ids[case.source], case.contains)
        per_query.append(
            {"id": case.id, "hit": rank is not None, "rank": rank, "returned": len(hits)}
        )
    return per_query, citations, valid, errors


async def _run(
    settings: Settings,
    cases: Cases,
    url: str,
    owner_url: str,
    gateway: ModelGatewayPort | None,
    poll_s: float,
) -> dict[str, Any]:
    await asyncio.to_thread(harness.reset_eval_database, url, owner_url)
    eval_settings = settings.model_copy(update={"database_url": url, "worker_alive_file": None})
    db = create_engine(eval_settings)
    live: ModelGateway | None = None
    principal = harness.harness_principal()
    try:
        ids = await _register(db, eval_settings, cases, principal)
        await harness.drain(db, eval_settings, gateway, poll_s, job_types=JOB_TYPES)
        not_ready = await _not_ready(db, eval_settings, principal)
        if gateway is None:
            live = ModelGateway(eval_settings, db)
            gateway = live
        per_query, citations, valid, errors = await _score(
            db, eval_settings, cases, ids, gateway, principal
        )
    finally:
        if live is not None:
            await live.aclose()
        await db.dispose()
    hits = sum(1 for q in per_query if q["hit"])
    by_file = {v: k for k, v in ids.items()}
    return {
        "kind": "retrieval",
        "created_at": datetime.now(UTC).isoformat(),
        "profile": settings.model_profile_embed,
        "k": cases.k,
        "chunk_chars": settings.knowledge_chunk_chars,
        "chunk_overlap_chars": settings.knowledge_chunk_overlap_chars,
        "source_count": len(cases.sources),
        "query_count": len(cases.queries),
        "hits": hits,
        "hit_rate_at_k": ratio(hits, len(cases.queries)),
        "citations": citations,
        "valid_citations": valid,
        "citation_validity": ratio(valid, citations),
        "queries": per_query,
        "sources_not_ready": {by_file.get(i, i): state for i, state in not_ready.items()},
        "errors": errors,
    }


async def run_retrieval_eval(
    settings: Settings,
    *,
    gateway: ModelGatewayPort | None = None,
    cases_dir: Path = CASES_DIR,
    out_dir: Path = OUT_DIR,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    poll_s: float = 0.5,
) -> RetrievalOutcome:
    """Run the cases and write the report (module docstring). `gateway` replaces the live one
    (tests). Raises `harness.EvalRefusedError`, `CaseError` or `harness.EvalTimedOutError`."""
    url, owner_url = harness.eval_urls(settings)
    cases = load_cases(cases_dir)
    with harness.temporary_storage() as storage:
        settings = settings.model_copy(update={"storage_dir": storage})
        try:
            report = await asyncio.wait_for(
                _run(settings, cases, url, owner_url, gateway, poll_s), timeout=timeout_s
            )
        except TimeoutError:
            raise harness.EvalTimedOutError(harness.TIMED_OUT_MESSAGE) from None
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    out = out_dir / f"retrieval-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _log.info(
        "evals.retrieval_completed",
        extra={"query_count": report["query_count"], "hits": report["hits"]},
    )
    return RetrievalOutcome(report=report, out_dir=out)


def _percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def render(report: Mapping[str, Any]) -> str:
    """The report as a few lines for the console."""
    lines = [
        f"Retrieval eval: {report['query_count']} question(s) over {report['source_count']} "
        f"Source(s), {report['profile']}, k={report['k']}",
        f"  hit rate at {report['k']}:    {_percent(report['hit_rate_at_k'])} "
        f"({report['hits']}/{report['query_count']})",
        f"  citation validity: {_percent(report['citation_validity'])} "
        f"({report['valid_citations']}/{report['citations']})",
    ]
    for query in report["queries"]:
        if not query["hit"]:
            lines.append(f"  miss: {query['id']}")
    for name, state in report["sources_not_ready"].items():
        lines.append(f"  not ready: {name}: {state}")
    for name, error in report["errors"].items():
        lines.append(f"  {name}: search failed ({error})")
    return "\n".join(lines)
