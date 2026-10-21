"""The eval harness (Story 7.6): runs the reference set through the real job chain in an
isolated evaluation database, scores it and stores the result.

1. **Refuse** (`EvalRefusedError`, exit 2) unless `PSA_EVAL_DATABASE_URL` and
   `PSA_EVAL_MIGRATIONS_DATABASE_URL` are set and name a database other than
   `PSA_DATABASE_URL`'s, and unless every `--config <agent_id>=<version>` exists.
2. **Main database, read**: each Agent's chosen config version (default: current).
3. **Reset** the eval database: `alembic downgrade base`, then `upgrade head`.
4. **Install** each chosen version there as its Agent's newest, so the job chain uses it.
5. **Run**: one Opportunity per reference Opportunity, its Sources added as uploads; the
   worker loop (`app.main_worker.run`) drains parse → extraction → Gap detection →
   Specialists → Estimate → Red Team through the ModelGateway (Agents send `background`
   priority). Assumption proposals are not run. There is no Critic Agent yet.
6. **Score** what the chain stored (`scoring`), with the model calls' tokens and wall time.
7. **Main database, write**: `registry.record_eval_result` inserts the result row and its
   `registry.eval.completed` trace event in one Unit of Work.

The whole run (steps 3-6) has a timeout; past it nothing is stored (`EvalTimedOutError`).
The harness touches the main database only in steps 2 and 7 (and to read the last accepted
result). It imports business modules only through their `application.public` APIs.
"""

import asyncio
import contextlib
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from app import main_worker
from app.evals import report as reports
from app.evals.annotations import (
    REFERENCE_DIR,
    ReferenceOpportunity,
    load_reference_set,
    reference_set_digest,
)
from app.evals.scoring import (
    DetectedGap,
    ExtractedRequirement,
    Finding,
    ModelCallStats,
    OpportunityOutput,
    SetScores,
    Span,
    StageFailure,
    aggregate,
    cost,
    score_opportunity,
)
from app.modules.identity.application.public import Action, Principal, Role
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.modules.registry.application import public as registry
from app.platform.actor import Actor
from app.platform.config import Settings, get_settings
from app.platform.db import create_engine
from app.platform.logging import get_logger
from app.platform.model_gateway.port import ModelGatewayPort
from app.platform.storage import BlobStore
from app.platform.uow import unit_of_work

_log = get_logger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]
OUT_DIR = BACKEND_DIR.parent / "evals" / "out"
HARNESS_ACTOR = Actor(type="system", id="eval_harness")
TIMED_OUT_MESSAGE = "Eval timed out — GPU busy"
DEFAULT_TIMEOUT_S = 3600.0

EVAL_JOB_TYPES = frozenset(
    {
        "intake.parse_source",
        "intake.extract_requirements",
        "gaps.detect_gaps",
        "workflows.execute",
        "estimates.draft_estimate",
        "assessments.red_team_review",
    }
)
"""The job chain the harness drains. Not `estimates.propose_assumptions` (not evaluated)."""
_OPEN_JOB_STATUSES = ("queued", "running", "failed_retrying")
_STAGE_OF_JOB = {
    "intake.parse_source": "parse",
    "intake.extract_requirements": "extraction",
    "gaps.detect_gaps": "gap_detection",
    "workflows.execute": "specialists",
    "estimates.draft_estimate": "estimate",
    "assessments.red_team_review": "red_team",
}


class EvalRefusedError(Exception):
    """Nothing ran: a configuration problem (exit 2)."""


class EvalTimedOutError(Exception):
    """The eval passed its timeout: nothing is stored (exit 3)."""


@dataclass(frozen=True, slots=True)
class EvalOptions:
    configs: Mapping[str, int] = field(default_factory=dict)
    """agent id → config version number (default: the current version)."""
    only: Sequence[str] = ()
    timeout_s: float = DEFAULT_TIMEOUT_S
    reference_dir: Path = REFERENCE_DIR
    out_dir: Path = OUT_DIR
    poll_s: float = 0.5


@dataclass(frozen=True, slots=True)
class EvalOutcome:
    report: dict[str, Any]
    result: registry.EvalResult | None
    out_dir: Path

    @property
    def passed(self) -> bool:
        return bool(self.report["passed"])


# --- 1. refusals ------------------------------------------------------------------------------


_LOOPBACK = frozenset({"", "localhost", "127.0.0.1", "::1", "[::1]"})


def _host(host: str | None) -> str:
    """Loopback spellings are one host: `localhost` and `127.0.0.1` reach the same server."""
    name = (host or "").strip().lower()
    return "localhost" if name in _LOOPBACK or name.startswith("127.") else name


def _same_database(a: str, b: str) -> bool:
    left, right = make_url(a), make_url(b)
    return (_host(left.host), left.port or 5432, left.database) == (
        _host(right.host),
        right.port or 5432,
        right.database,
    )


def eval_urls(settings: Settings) -> tuple[str, str]:
    """The eval database's app and owner URLs, or `EvalRefusedError`."""
    url, owner = settings.eval_database_url, settings.eval_migrations_database_url
    if not url or not owner:
        raise EvalRefusedError(
            "PSA_EVAL_DATABASE_URL and PSA_EVAL_MIGRATIONS_DATABASE_URL must both be set."
        )
    main = settings.database_url
    main_owner = settings.migrations_database_url or main
    if (
        _same_database(url, main)
        or _same_database(owner, main)
        or _same_database(owner, main_owner)
    ):
        raise EvalRefusedError(
            "The eval database must differ from PSA_DATABASE_URL's: refusing to reset it."
        )
    if not _same_database(url, owner):
        raise EvalRefusedError(
            "PSA_EVAL_DATABASE_URL and PSA_EVAL_MIGRATIONS_DATABASE_URL name different databases."
        )
    return url, owner


def parse_configs(values: Sequence[str]) -> dict[str, int]:
    """`--config <agent_id>=<version>` values; `EvalRefusedError` when one is malformed."""
    configs: dict[str, int] = {}
    for value in values:
        agent_id, sep, version = value.partition("=")
        if not sep or not agent_id.strip() or not re.fullmatch(r"[0-9]+", version.strip()):
            raise EvalRefusedError(f"--config {value!r}: expected <agent_id>=<version>.")
        configs[agent_id.strip()] = int(version)
    return configs


# --- 2. config versions from the main database ----------------------------------------------


Chosen = list[tuple[registry.RegisteredAgent, registry.ConfigVersion]]


async def choose_configs(main: AsyncEngine, configs: Mapping[str, int]) -> Chosen:
    """Each Agent's chosen config version; `EvalRefusedError` for an unknown one."""
    async with unit_of_work(main) as uow:
        agents = await registry.list_agents(uow)
        known = {a.agent_id for a in agents}
        unknown = sorted(set(configs) - known)
        if unknown:
            raise EvalRefusedError(f"Unknown Agent in --config: {', '.join(unknown)}.")
        chosen: Chosen = []
        for agent in agents:
            wanted = configs.get(agent.agent_id)
            if wanted is None:
                chosen.append((agent, agent.current))
                continue
            versions = await registry.config_versions_of(uow, agent.agent_id)
            version = next((v for v in versions if v.version == wanted), None)
            if version is None:
                raise EvalRefusedError(
                    f"Unknown config: {agent.agent_id} has no config version {wanted}."
                )
            chosen.append((agent, version))
    return chosen


# --- 3. reset ---------------------------------------------------------------------------------


def reset_eval_database(url: str, owner_url: str) -> None:
    """`alembic downgrade base`, then `upgrade head`, against the eval database only."""
    env = {**os.environ, "PSA_DATABASE_URL": url, "PSA_MIGRATIONS_DATABASE_URL": owner_url}
    for args in (("downgrade", "base"), ("upgrade", "head")):
        done = subprocess.run(  # noqa: S603 - fixed arguments, our own alembic
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0:
            tail = " | ".join(done.stderr.strip().splitlines()[-5:])
            raise RuntimeError(f"alembic {' '.join(args)} failed on the eval database: {tail}")


# --- 5. run -----------------------------------------------------------------------------------


class Upload:
    """An uploaded file (`intake` or `knowledge` `IncomingFile`) over bytes in memory."""

    def __init__(self, name: str, data: bytes) -> None:
        self._name, self._data = name, data

    async def filename(self) -> str:
        return self._name

    async def chunks(self) -> AsyncIterator[bytes]:
        yield self._data


def harness_principal() -> Principal:
    """The presales engineer who owns the eval Opportunities (eval database only)."""
    return Principal(
        actor=Actor(type="user", id=str(uuid4())),
        roles=frozenset({Role.PRESALES_ENGINEER}),
        permissions=frozenset(Action),
    )


async def create_opportunities(
    db: AsyncEngine, reference: Sequence[ReferenceOpportunity], settings: Settings
) -> dict[str, UUID]:
    """One Opportunity per reference Opportunity, with its Sources (which queue parsing)."""
    owner = harness_principal()
    store = BlobStore(settings.storage_dir)
    created: dict[str, UUID] = {}
    for ref in reference:
        a = ref.annotations
        async with unit_of_work(db) as uow:
            opportunity = await opportunities.create(
                uow,
                owner,
                opportunities.NewOpportunity(
                    title=a.title,
                    customer_name=a.customer,
                    products=list(a.products),
                    industry=a.industry,
                    target_proposal_date=date.today() + timedelta(days=60),
                ),
            )
        opportunity_id = UUID(opportunity.id)
        for source in ref.sources:
            async with unit_of_work(db) as uow:
                await intake.add_file(
                    uow,
                    owner,
                    opportunity_id,
                    Upload(source.name, source.data),
                    store=store,
                    max_bytes=settings.upload_max_bytes,
                )
        created[ref.slug] = opportunity_id
    return created


async def open_job_count(db: AsyncEngine, job_types: frozenset[str] = EVAL_JOB_TYPES) -> int:
    async with db.connect() as conn:
        found = await conn.execute(
            sa.text(
                "SELECT count(*) FROM platform_jobs WHERE job_type = ANY(:t) AND status = ANY(:s)"
            ),
            {"t": sorted(job_types), "s": list(_OPEN_JOB_STATUSES)},
        )
        return int(found.scalar_one())


async def drain(
    db: AsyncEngine,
    settings: Settings,
    gateway: ModelGatewayPort | None,
    poll_s: float,
    job_types: frozenset[str] = EVAL_JOB_TYPES,
) -> None:
    """Run the worker loop on the eval database until no job of `job_types` (default: the
    chain) is left."""
    main_worker.load_job_types()
    stop = asyncio.Event()
    worker = asyncio.create_task(
        main_worker.run(
            stop,
            settings=settings,
            engine=db,
            poll_s=poll_s,
            job_types=job_types,
            gateway=gateway,
        )
    )
    try:
        idle = 0
        while idle < 2:  # twice in a row: a finishing job queues the next in its own commit
            await asyncio.sleep(poll_s)
            if worker.done():
                worker.result()
                raise RuntimeError("the worker loop stopped early")
            idle = idle + 1 if await open_job_count(db, job_types) == 0 else 0
    finally:
        stop.set()
        with contextlib.suppress(asyncio.CancelledError):
            await worker


# --- 6. collect what the chain stored ---------------------------------------------------------


async def _rows(db: AsyncEngine, sql: str, **params: Any) -> list[sa.Row[Any]]:
    async with db.connect() as conn:
        return list((await conn.execute(sa.text(sql), params)).all())


async def _latest(db: AsyncEngine, table: str, opportunity_id: UUID) -> sa.Row[Any] | None:
    rows = await _rows(
        db,
        f"SELECT * FROM {table} WHERE opportunity_id = :o "  # noqa: S608 - table names are ours
        "ORDER BY created_at DESC LIMIT 1",
        o=opportunity_id,
    )
    return rows[0] if rows else None


async def _failures(db: AsyncEngine, opportunity_id: UUID) -> list[StageFailure]:
    failures: list[StageFailure] = []
    parses = await _rows(
        db,
        "SELECT p.status, p.error_code FROM intake_source_parses p "
        "JOIN intake_sources s ON s.id = p.source_id WHERE s.opportunity_id = :o",
        o=opportunity_id,
    )
    failed_parse = next((r for r in parses if r.status == "failed"), None)
    if failed_parse is not None:  # one failure per stage, however many Sources failed
        failures.append(StageFailure("parse", failed_parse.error_code or "failed"))
    for stage, table in (
        ("extraction", "intake_extractions"),
        ("gap_detection", "gaps_detections"),
        ("red_team", "assessments_red_team_runs"),
    ):
        latest = await _latest(db, table, opportunity_id)
        if latest is not None and latest.status == "failed":
            failures.append(StageFailure(stage, latest.error_code or "failed"))
    run = await _latest(db, "workflows_runs", opportunity_id)
    if run is not None and run.status in ("failed", "partially_failed", "cancelled"):
        failures.append(StageFailure("specialists", run.status))
    if run is not None and run.status == "succeeded":
        versions = await _rows(
            db,
            "SELECT 1 FROM estimates_estimate_versions WHERE opportunity_id = :o LIMIT 1",
            o=opportunity_id,
        )
        if not versions:
            failures.append(StageFailure("estimate", "no_estimate_version"))
    dead = await _rows(
        db,
        "SELECT DISTINCT job_type FROM platform_jobs WHERE opportunity_id = :o "
        "AND status = 'dead' AND job_type = ANY(:t)",
        o=opportunity_id,
        t=sorted(EVAL_JOB_TYPES),
    )
    seen = {f.stage for f in failures}
    for row in dead:
        stage = _STAGE_OF_JOB[row.job_type]
        if stage not in seen:
            failures.append(StageFailure(stage, "job_dead"))
            seen.add(stage)
    return failures


async def collect(
    db: AsyncEngine, slug: str, opportunity_id: UUID, store: BlobStore
) -> OpportunityOutput:
    """What the job chain stored for one Opportunity."""
    versions = await _rows(
        db,
        "SELECT v.source_id, v.version, v.filename FROM intake_source_versions v "
        "JOIN intake_sources s ON s.id = v.source_id WHERE s.opportunity_id = :o",
        o=opportunity_id,
    )
    names = {(r.source_id, r.version): r.filename for r in versions}
    texts: dict[str, str] = {}
    async with unit_of_work(db) as uow:
        for r in versions:
            text = await intake.extracted_text(uow, r.source_id, r.version, store=store)
            if text is not None:
                texts[r.filename] = text
    requirements = await _rows(
        db,
        "SELECT id, text FROM intake_requirements WHERE opportunity_id = :o "
        "AND status = 'active' AND origin = 'extracted'",
        o=opportunity_id,
    )
    evidence = await _rows(
        db,
        'SELECT e.requirement_id, p.source_id, p.source_version, p.start, p."end" '
        "FROM intake_requirement_evidence e "
        "JOIN intake_source_passages p ON p.id = e.passage_id "
        "JOIN intake_requirements r ON r.id = e.requirement_id "
        "WHERE r.opportunity_id = :o AND r.status = 'active' AND r.origin = 'extracted'",
        o=opportunity_id,
    )
    spans: dict[UUID, list[Span]] = defaultdict(list)
    for e in evidence:
        name = names.get((e.source_id, e.source_version))
        if name is not None:
            spans[e.requirement_id].append(Span(name, e.start, e.end))
    extraction = await _rows(
        db,
        "SELECT dropped_count FROM intake_extractions WHERE opportunity_id = :o "
        "AND status = 'succeeded' ORDER BY created_at DESC LIMIT 1",
        o=opportunity_id,
    )
    gaps = await _rows(
        db,
        "SELECT id, title, why_it_matters FROM gaps_gaps WHERE opportunity_id = :o "
        "AND status IN ('open', 'converted')",
        o=opportunity_id,
    )
    specialist = await _rows(
        db,
        "SELECT f.id, a.agent, f.kind, f.title, f.detail, "
        "array_remove(array_agg(fr.requirement_id), NULL) AS requirement_ids "
        "FROM assessments_assessment_findings f "
        "JOIN assessments_assessments a ON a.id = f.assessment_id "
        "LEFT JOIN assessments_assessment_finding_requirements fr ON fr.finding_id = f.id "
        "WHERE a.opportunity_id = :o AND a.status = 'current' "
        "GROUP BY f.id, a.agent, f.kind, f.title, f.detail",
        o=opportunity_id,
    )
    red_team = await _rows(
        db,
        "SELECT f.id, f.category, f.title, f.argument, "
        "array_remove(array_agg(fr.requirement_id), NULL) AS requirement_ids "
        "FROM assessments_findings f JOIN assessments_reviews r ON r.id = f.review_id "
        "LEFT JOIN assessments_finding_requirements fr ON fr.finding_id = f.id "
        "WHERE r.opportunity_id = :o AND r.status = 'current' "
        "GROUP BY f.id, f.category, f.title, f.argument",
        o=opportunity_id,
    )
    findings = [
        Finding(
            str(f.id), f.agent, f.kind, f.title, f.detail, tuple(str(i) for i in f.requirement_ids)
        )
        for f in specialist
    ] + [
        Finding(
            str(f.id),
            "red_team_agent",
            f.category,
            f.title,
            f.argument,
            tuple(str(i) for i in f.requirement_ids),
        )
        for f in red_team
    ]
    return OpportunityOutput(
        slug=slug,
        source_texts=texts,
        requirements=[
            ExtractedRequirement(str(r.id), r.text, tuple(spans.get(r.id, ())))
            for r in requirements
        ],
        valid_citations=len(evidence),
        dropped_citations=int(extraction[0].dropped_count or 0) if extraction else 0,
        gaps=[DetectedGap(str(g.id), g.title, g.why_it_matters) for g in gaps],
        findings=findings,
        failures=await _failures(db, opportunity_id),
    )


async def model_call_stats(db: AsyncEngine) -> list[ModelCallStats]:
    rows = await _rows(
        db,
        "SELECT agent_id, count(*) AS calls, "
        "count(*) FILTER (WHERE outcome = 'invalid_output') AS invalid, "
        "coalesce(sum(input_tokens + output_tokens), 0) AS tokens, "
        "coalesce(sum(latency_ms), 0) AS latency_ms, "
        "array_agg(DISTINCT model_digest) AS digests "
        "FROM platform_model_calls GROUP BY agent_id ORDER BY agent_id",
    )
    return [
        ModelCallStats(
            agent_id=r.agent_id,
            calls=int(r.calls),
            invalid_output=int(r.invalid),
            tokens=int(r.tokens),
            latency_ms=int(r.latency_ms),
            digests=tuple(sorted(r.digests)),
        )
        for r in rows
    ]


# --- the whole run ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Scored:
    scores: SetScores
    calls: list[ModelCallStats]


async def _run_in_eval_db(
    eval_db: AsyncEngine,
    settings: Settings,
    eval_settings: Settings,
    url: str,
    owner_url: str,
    chosen: Chosen,
    reference: Sequence[ReferenceOpportunity],
    gateway: ModelGatewayPort | None,
    poll_s: float,
) -> _Scored:
    await asyncio.to_thread(reset_eval_database, url, owner_url)
    async with unit_of_work(eval_db) as uow:
        for agent, version in chosen:
            await registry.install_eval_config(uow, agent, version)
    created = await create_opportunities(eval_db, reference, settings)
    await drain(eval_db, eval_settings, gateway, poll_s)
    by_slug = {r.slug: r for r in reference}
    scores = []
    for slug, opportunity_id in created.items():
        output = await collect(eval_db, slug, opportunity_id, BlobStore(settings.storage_dir))
        scores.append(score_opportunity(by_slug[slug].annotations, output))
    calls = await model_call_stats(eval_db)
    return _Scored(aggregate(scores, calls), calls)


async def run_eval(
    options: EvalOptions,
    *,
    settings: Settings | None = None,
    gateway: ModelGatewayPort | None = None,
) -> EvalOutcome:
    """Run the eval (module docstring). Raises `EvalRefusedError` before anything runs and
    `EvalTimedOutError` when it passes `options.timeout_s` (nothing stored then)."""
    settings = settings or get_settings()
    url, owner_url = eval_urls(settings)
    reference = load_reference_set(options.reference_dir, options.only)
    if not reference:
        raise EvalRefusedError(f"No reference Opportunities under {options.reference_dir}.")
    digest = reference_set_digest(options.reference_dir, [r.slug for r in reference])
    version = registry.reference_set_version(digest)
    with temporary_storage() as storage:
        settings = settings.model_copy(update={"storage_dir": storage})
        return await _run(options, settings, url, owner_url, reference, version, gateway)


@contextlib.contextmanager
def temporary_storage() -> Iterator[Path]:
    """A file store for the eval's Sources, removed afterwards: never the main one. Job
    handlers read `get_settings().storage_dir`, so `PSA_STORAGE_DIR` points there meanwhile."""
    previous = os.environ.get("PSA_STORAGE_DIR")
    with tempfile.TemporaryDirectory(prefix="psa-eval-files-") as folder:
        os.environ["PSA_STORAGE_DIR"] = folder
        get_settings.cache_clear()
        try:
            yield Path(folder)
        finally:
            if previous is None:
                os.environ.pop("PSA_STORAGE_DIR", None)
            else:
                os.environ["PSA_STORAGE_DIR"] = previous
            get_settings.cache_clear()


async def _run(
    options: EvalOptions,
    settings: Settings,
    url: str,
    owner_url: str,
    reference: Sequence[ReferenceOpportunity],
    version: str,
    gateway: ModelGatewayPort | None,
) -> EvalOutcome:
    main_db = create_engine(settings)
    eval_settings = settings.model_copy(update={"database_url": url, "worker_alive_file": None})
    eval_db = create_engine(eval_settings)
    try:
        chosen = await choose_configs(main_db, options.configs)
        try:
            scored = await asyncio.wait_for(
                _run_in_eval_db(
                    eval_db,
                    settings,
                    eval_settings,
                    url,
                    owner_url,
                    chosen,
                    reference,
                    gateway,
                    options.poll_s,
                ),
                timeout=options.timeout_s,
            )
        except TimeoutError:
            raise EvalTimedOutError(TIMED_OUT_MESSAGE) from None
        return await _store(main_db, settings, options, reference, version, chosen, scored)
    finally:
        await eval_db.dispose()
        await main_db.dispose()


async def _store(
    main_db: AsyncEngine,
    settings: Settings,
    options: EvalOptions,
    reference: Sequence[ReferenceOpportunity],
    version: str,
    chosen: Chosen,
    scored: _Scored,
) -> EvalOutcome:
    scores = scored.scores
    digests = {s.agent_id: list(s.digests) for s in scored.calls}
    spent = cost(
        scored.calls,
        per_gpu_second_minor=settings.cost_per_gpu_second_minor,
        per_1k_tokens_minor=settings.cost_per_1k_tokens_minor,
        currency=settings.cost_currency,
    )
    failures = [
        registry.EvalFailure.model_validate({"slug": s.slug, "stage": f.stage, "code": f.code})
        for s in scores.opportunities
        for f in s.failures
    ]
    new = registry.NewEvalResult(
        reference_set_version=version,
        config_version_ids={agent.agent_id: str(v.id) for agent, v in chosen},
        model_digests={agent.agent_id: digests.get(agent.agent_id, []) for agent, _ in chosen},
        prompt_versions={agent.agent_id: v.prompt_version for agent, v in chosen},
        scores=registry.EvalScores(overall=scores.overall, per_agent=scores.per_agent),
        failures=failures,
        opportunity_count=len(reference),
        draft_count=sum(1 for r in reference if r.annotations.is_draft),
        pending_count=len(scores.pending),
        tokens=spent.tokens,
        gpu_seconds=spent.gpu_seconds,
        cost=registry.EvalCost(amount_minor=spent.amount_minor, currency=spent.currency),
    )
    async with unit_of_work(main_db) as uow:
        result = await registry.record_eval_result(uow, HARNESS_ACTOR, new)
    meta = {
        "reference_set_version": version,
        "opportunity_count": new.opportunity_count,
        "draft_count": new.draft_count,
        "config_version_ids": new.config_version_ids,
        "model_digests": new.model_digests,
        "prompt_versions": new.prompt_versions,
        "tokens": new.tokens,
        "gpu_seconds": new.gpu_seconds,
        "cost": new.cost.model_dump(),
    }
    built = reports.build_report(
        result=result, bars=result.bars, passed=result.passed, scores=scores, meta=meta
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    out = options.out_dir / stamp
    reports.write(out, built, scores.pending)
    _log.info("evals.completed", extra={"result_id": result.id, "passed": result.passed})
    return EvalOutcome(report=built, result=result, out_dir=out)
