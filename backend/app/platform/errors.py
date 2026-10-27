"""RFC 9457 problem+json errors, mapped in one place (AD-16).

Body: `{type, title, status, code, detail, instance}`. `code` is stable and machine-readable.
An error may add extension members (RFC 9457 §3.2), e.g. `blockers` on
`estimate_version_blocked` (Story 8.6).
"""

from collections.abc import Mapping
from http import HTTPStatus
from types import MappingProxyType
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.platform.logging import get_logger

PROBLEM_JSON = "application/problem+json"
_log = get_logger(__name__)

_HTTP_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    409: "conflict",
    412: "precondition_failed",
    415: "unsupported_media_type",
    422: "validation_error",
    428: "precondition_required",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


class Problem(BaseModel):
    """problem+json body, published in OpenAPI so the generated client is typed."""

    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    instance: str | None = None


class ProblemError(Exception):
    """Base for typed errors that map to a problem+json response."""

    status: int = 500
    code: str = "internal_error"
    title: str | None = None
    headers: Mapping[str, str] | None = None
    extensions: Mapping[str, Any] | None = None
    """Extension members added to the body (JSON-ready values); they never replace the
    standard members."""

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(detail or self.code)
        self.detail = detail


class DbUnavailableError(ProblemError):
    status = 503
    code = "db_unavailable"
    title = "Database unavailable"


class AuthenticationError(ProblemError):
    """Base for 401s: the request carries no valid bearer token. Always sends
    `WWW-Authenticate: Bearer` (RFC 6750). Details never echo the token or its claims."""

    status = 401
    code = "unauthenticated"
    title = "Unauthenticated"
    headers: Mapping[str, str] | None = MappingProxyType(
        {"WWW-Authenticate": 'Bearer error="invalid_token"'}
    )


class TokenMissingError(AuthenticationError):
    code = "token_missing"
    headers = MappingProxyType({"WWW-Authenticate": "Bearer"})


class TokenExpiredError(AuthenticationError):
    code = "token_expired"


class TokenInvalidError(AuthenticationError):
    code = "token_invalid"


class AuthUnavailableError(ProblemError):
    """The identity provider's signing keys (JWKS) could not be fetched."""

    status = 503
    code = "auth_unavailable"
    title = "Authentication unavailable"


class ForbiddenError(ProblemError):
    """`identity.authorize` denied the action (AD-15)."""

    status = 403
    code = "forbidden"
    title = "Forbidden"


class ReviewerNotAuthorizedError(ForbiddenError):
    """The caller is not the Review Request's current reviewer, or no longer holds the role
    its review type needs (Story 9.3); nothing was written."""

    code = "reviewer_not_authorized"
    title = "Reviewer not authorized"


class SelfApprovalForbiddenError(ForbiddenError):
    """The author of an Estimate Version tried to approve a review of it (Story 9.3);
    nothing was written."""

    code = "self_approval_forbidden"
    title = "Self-approval forbidden"


class NotFoundError(ProblemError):
    """The resource does not exist (or the caller may not know that it does)."""

    status = 404
    code = "not_found"
    title = "Not found"


class ConflictError(ProblemError):
    """The request conflicts with a domain rule. Subclasses set a stable `code`."""

    status = 409
    code = "conflict"
    title = "Conflict"


class ParseNotFailedError(ConflictError):
    """A Source parse retry asked for a version whose parse has not failed."""

    code = "parse_not_failed"
    title = "Parse not failed"


class NoPendingChangeError(ConflictError):
    """A pending Requirement change was accepted or rejected, but the Requirement has no
    open one (Story 2.7)."""

    code = "no_pending_change"
    title = "No pending change"


class ExtractionInProgressError(ConflictError):
    """A Requirement extraction was asked for while one is queued or running."""

    code = "extraction_in_progress"
    title = "Extraction in progress"


class GapDetectionInProgressError(ConflictError):
    """A Gap detection was asked for while one is queued or running."""

    code = "gap_detection_in_progress"
    title = "Gap detection in progress"


class EstimateDraftInProgressError(ConflictError):
    """An Estimate draft was asked for while one is queued or running."""

    code = "estimate_draft_in_progress"
    title = "Estimate draft in progress"


class RedTeamReviewInProgressError(ConflictError):
    """A Red Team Review was asked for while one is queued or running (Story 6.5)."""

    code = "red_team_review_in_progress"
    title = "Red Team review in progress"


class AssessmentInProgressError(ConflictError):
    """An assessment run (or a task retry) was asked for while one of the Opportunity's runs
    is queued or running (Epic 5 slice 5A)."""

    code = "assessment_in_progress"
    title = "Assessment in progress"


class AssessmentNotInProgressError(ConflictError):
    """A cancel was asked for a run that is not the Opportunity's latest, or is no longer
    queued or running (Story 5.5)."""

    code = "assessment_not_in_progress"
    title = "Assessment not in progress"


class AssessmentTaskNotFailedError(ConflictError):
    """A task retry was asked for a task that is not `failed`, or not of the Opportunity's
    latest run (Epic 5 slice 5A)."""

    code = "assessment_task_not_failed"
    title = "Assessment task not failed"


class DecisionNotOpenError(ConflictError):
    """A run's decision was resolved that is no longer open, or whose run is cancelled or not
    waiting for a person (Story 5.5)."""

    code = "decision_not_open"
    title = "Decision not open"


class EstimateNotFoundError(ConflictError):
    """An Estimate export was asked for while the Opportunity has no Estimate Version yet
    (Story 8.8)."""

    code = "estimate_not_found"
    title = "No Estimate yet"


class EstimateVersionNotDraftError(ConflictError):
    """An Estimate line was edited whose version is no longer the Opportunity's `draft`: a
    re-draft replaced it (Story 8.2)."""

    code = "estimate_version_not_draft"
    title = "Estimate Version not draft"


class EstimateVersionBlockedError(ConflictError):
    """A submission was asked for while the version still has submission blockers (Story
    8.6). The body's `blockers` extension member lists them; nothing changed."""

    code = "estimate_version_blocked"
    title = "Estimate Version blocked"

    def __init__(self, detail: str | None = None, *, blockers: Mapping[str, Any]) -> None:
        super().__init__(detail)
        self.extensions = {"blockers": blockers}


class BaselineBlockedError(ConflictError):
    """A Baseline was asked for a version that isn't approved or still has blockers to
    Baseline (Story 9.7). The body's `blockers` extension member lists each one with its kind;
    nothing changed."""

    code = "baseline_blocked"
    title = "Baseline blocked"

    def __init__(self, detail: str | None = None, *, blockers: list[Mapping[str, Any]]) -> None:
        super().__init__(detail)
        self.extensions = {"blockers": blockers}


class BaselineNotNewerError(ConflictError):
    """A Baseline was asked for a version that isn't a newer approved version than the
    current Baseline (Story 9.7); nothing changed."""

    code = "baseline_not_newer"
    title = "Baseline not newer"


class EstimateVersionNotSubmittedError(ConflictError):
    """A Review Request was asked for an Estimate Version that is still a draft (Story 9.1)."""

    code = "estimate_version_not_submitted"
    title = "Estimate Version not submitted"


class EstimateVersionSupersededError(ConflictError):
    """A Review Request was asked for an Estimate Version a newer one superseded (Story
    9.1)."""

    code = "estimate_version_superseded"
    title = "Estimate Version superseded"


class EstimateVersionRejectedError(ConflictError):
    """A Review Request was asked for a rejected Estimate Version (Story 9.1; the status
    arrived with Story 9.3)."""

    code = "estimate_version_rejected"
    title = "Estimate Version rejected"


class ReviewRequestDuplicateError(ConflictError):
    """A reviewer already has a pending Review Request of that type on the same target
    (Story 9.1); nothing was written."""

    code = "review_request_duplicate"
    title = "Review Request already pending"


class ReviewRequestNotPendingError(ConflictError):
    """A Review Request that is no longer `pending` was cancelled (Story 9.1) or decided
    (Story 9.3)."""

    code = "review_request_not_pending"
    title = "Review Request not pending"


class ReviewReplyNotExpectedError(ConflictError):
    """A reply was sent on a pending Review Request whose latest decision asks for neither
    evidence nor an alternative (Story 9.4); nothing was written."""

    code = "review_reply_not_expected"
    title = "No reply expected"


class EstimateVersionNotDecidedError(ConflictError):
    """A new Estimate Version was asked for from a base that is neither `rejected` nor
    `approved` (Story 9.4)."""

    code = "estimate_version_not_decided"
    title = "Estimate Version not decided"


class EstimateDraftExistsError(ConflictError):
    """A new Estimate Version was asked for while the Opportunity already has a draft (Story
    9.4)."""

    code = "estimate_draft_exists"
    title = "Draft Estimate exists"


class ChallengeNeedsEstimateError(ConflictError):
    """A Challenge was raised on an Opportunity with no Estimate Version to put it in
    context of (Story 9.5)."""

    code = "challenge_needs_estimate"
    title = "Challenge needs an Estimate"


class ChallengeVersionSupersededError(ConflictError):
    """A Challenge was raised or confirmed while the Estimate Version in its context is
    superseded (Story 9.5); nothing was written."""

    code = "challenge_version_superseded"
    title = "Challenge version superseded"


class ChallengeNotAwaitingConfirmationError(ConflictError):
    """A Challenge that is no longer `awaiting_confirmation` was confirmed or declined
    (Story 9.5)."""

    code = "challenge_not_awaiting_confirmation"
    title = "Challenge not awaiting confirmation"


class NoDraftEstimateError(ConflictError):
    """A Gap was converted to a Risk while the Opportunity has no draft Estimate Version
    (Story 8.5)."""

    code = "no_draft_estimate"
    title = "No draft Estimate"


class GapNotOpenError(ConflictError):
    """An Assumption was accepted, or a Gap converted to a Risk, whose Gap is no longer `open`
    (Stories 8.4 and 8.5)."""

    code = "gap_not_open"
    title = "Gap not open"


class GapMandatoryError(ConflictError):
    """A dismissal was asked for on a mandatory Gap whose Checklist still applies (Story
    4.2)."""

    code = "gap_mandatory"
    title = "Gap mandatory"


class GapNotReopenableError(ConflictError):
    """A Gap reopen was asked for on a Gap that is neither `dismissed` (Story 4.4) nor
    `answered` (Story 4.7)."""

    code = "gap_not_reopenable"
    title = "Gap not reopenable"


class QuestionNotApprovedError(ConflictError):
    """A question was marked sent that is not `approved` (Story 4.6)."""

    code = "question_not_approved"
    title = "Clarification Question not approved"


class QuestionNotSentError(ConflictError):
    """A question was marked "No answer" that is not `sent` (Story 4.6), or answered that is
    not `sent` or `unanswered` (Story 4.7)."""

    code = "question_not_sent"
    title = "Clarification Question not sent"


class QuestionNotEditableError(ConflictError):
    """A `sent` or `unanswered` question was edited or approved (Story 4.6)."""

    code = "question_not_editable"
    title = "Clarification Question not editable"


class NoApprovedQuestionsError(ConflictError):
    """An export of Clarification Questions found no approved question of an open Gap
    (Story 4.6)."""

    code = "no_approved_questions"
    title = "No approved Clarification Questions"


class CatalogueDuplicateError(ConflictError):
    """A catalogue entry's code or name equals that of an active entry of the same kind
    (Story 3.1)."""

    code = "catalogue_duplicate"
    title = "Catalogue entry already exists"


class SourceRetiredError(ConflictError):
    """A write targeted a retired Knowledge Source (Story 3.2)."""

    code = "knowledge_source_retired"
    title = "Knowledge Source retired"


class ChecklistRetiredError(ConflictError):
    """A write targeted a retired Checklist (Story 3.4)."""

    code = "knowledge_checklist_retired"
    title = "Checklist retired"


class ChecklistDraftExistsError(ConflictError):
    """A new draft was asked for while the Checklist already has one (Story 3.4)."""

    code = "checklist_draft_exists"
    title = "Draft already exists"


class ChecklistNoDraftError(ConflictError):
    """A draft was saved or published while the Checklist has none (Story 3.4)."""

    code = "checklist_no_draft"
    title = "No draft"


class EmbedNotRetryableError(ConflictError):
    """An embedding retry asked for a Knowledge Source version whose embedding hasn't failed
    and isn't missing, or that isn't parsed (Story 3.3)."""

    code = "embed_not_failed"
    title = "Embedding not failed"


class ConflictAlreadyResolvedError(ConflictError):
    """A Conflict was resolved or escalated after it was already resolved (Story 6.3)."""

    code = "conflict_already_resolved"
    title = "Conflict already resolved"


class ConflictNotOpenError(ConflictError):
    """A Conflict was escalated that is no longer `open`: it is already escalated (Story
    6.3)."""

    code = "conflict_not_open"
    title = "Conflict not open"


class FindingNotOpenError(ConflictError):
    """A Critic or Red Team Finding was resolved or overridden that is no longer `open`, or
    belongs to a superseded Review (Story 6.6)."""

    code = "finding_not_open"
    title = "Finding not open"


class ImportConsumedError(ConflictError):
    """An Opportunity import was already used to create an Opportunity (Story 1.7 import)."""

    code = "import_consumed"
    title = "Import already used"


class RegistryAgentDisabledError(ConflictError):
    """An agent step was triggered while its Agent is `disabled` or `eval_only` in the Agent
    Registry (Story 7.1). The `detail` is the sentence to show: "<Agent> is disabled"."""

    code = "registry_agent_disabled"
    title = "Agent disabled"


class RegistryAgentDuplicateError(ConflictError):
    """An Agent was registered with an id that is already registered (Story 7.1)."""

    code = "registry_agent_duplicate"
    title = "Agent already registered"


class GoneError(ProblemError):
    """The resource existed but no longer can be used (410)."""

    status = 410
    code = "gone"
    title = "Gone"


class ImportExpiredError(GoneError):
    """An Opportunity import is older than its 24-hour lifetime (Story 1.7 import)."""

    code = "import_expired"
    title = "Import expired"


class UploadTooLargeError(ProblemError):
    """An Opportunity import file is larger than `upload_max_bytes` (413). Same `code` and
    sentence as a Source upload's 422 `file_too_large`."""

    status = 413
    code = "file_too_large"
    title = "File too large"


class UploadTypeNotAllowedError(ProblemError):
    """An Opportunity import file's extension is not on the allowlist (415). Same `code`
    and sentence as a Source upload's 422 `file_type_not_allowed`."""

    status = 415
    code = "file_type_not_allowed"
    title = "File type not allowed"


class UnprocessableError(ProblemError):
    """The request is well-formed but breaks a domain rule checked after parsing (422).
    Subclasses set a stable `code`."""

    status = 422
    code = "validation_error"
    title = "Unprocessable content"


class InvalidCollaboratorError(UnprocessableError):
    """The user can't be a collaborator: the owner, an unknown user or one with no role."""

    code = "invalid_collaborator"
    title = "Invalid collaborator"


class FileTooLargeError(UnprocessableError):
    """An upload is larger than `upload_max_bytes`."""

    code = "file_too_large"
    title = "File too large"


class FileTypeNotAllowedError(UnprocessableError):
    """An upload's extension is not on the allowlist."""

    code = "file_type_not_allowed"
    title = "File type not allowed"


class FileContentMismatchError(UnprocessableError):
    """An upload's bytes don't match its extension (magic bytes, UTF-8 text)."""

    code = "file_content_mismatch"
    title = "File content mismatch"


class FileEmptyError(UnprocessableError):
    """An upload has no bytes."""

    code = "file_empty"
    title = "File empty"


class EvidenceUnresolvableError(UnprocessableError):
    """An Evidence reference doesn't resolve: unknown kind or id, wrong version, or a span
    outside the cited text (AD-13, Story 3.3). The detail names the reference."""

    code = "evidence_unresolvable"
    title = "Evidence does not resolve"


class FindingNotOverridableError(UnprocessableError):
    """A Finding tied to a mandatory security Checklist item can't be overridden, by any role
    (Story 6.6)."""

    code = "finding_not_overridable"
    title = "Finding not overridable"


class ReviewerNotAuthorizedForTypeError(UnprocessableError):
    """A named reviewer doesn't hold the role the review type needs (Story 9.1)."""

    code = "reviewer_not_authorized_for_type"
    title = "Reviewer not authorized for type"


class AuthorCannotReviewError(UnprocessableError):
    """The author of the Estimate Version was named as one of its reviewers (Story 9.1)."""

    code = "author_cannot_review"
    title = "Author can't review"


class ModelUnavailableProblem(ProblemError):
    """A request needed a model call (e.g. embedding a search query) and the model server
    failed or timed out."""

    status = 503
    code = "model_unavailable"
    title = "Model unavailable"


class RegistryConfigNotDeployedError(UnprocessableError):
    """A config version references a prompt, schema or model profile that is not in the
    deployed manifest (Story 7.1)."""

    code = "registry_config_not_deployed"
    title = "Config not deployed"


class RegistryPermissionForbiddenForAgentsError(UnprocessableError):
    """A config version grants a tool permission that is not a `read` action that is also a
    ToolGateway tool (Story 7.4; replaces Story 5.4's `tool_permission_not_read_only`):
    Agents can never be granted a write, delete, send or approve."""

    code = "registry_permission_forbidden_for_agents"
    title = "Permission forbidden for Agents"


class RegistryConfigIncompatibleContractError(UnprocessableError):
    """A config version's output schema was written for another `AgentResult` contract
    version than the one deployed (Story 7.1)."""

    code = "registry_config_incompatible_contract"
    title = "Incompatible contract version"


class IfMatchRequiredError(ProblemError):
    """A write arrived without an `If-Match` header (AD-11)."""

    status = 428
    code = "if_match_required"
    title = "If-Match required"


class RowVersionMismatchError(ProblemError):
    """The row changed since the client read it (AD-11)."""

    status = 412
    code = "row_version_mismatch"
    title = "Row version mismatch"


def problem_response(
    request: Request,
    status: int,
    code: str,
    *,
    title: str | None = None,
    detail: str | None = None,
    headers: Mapping[str, str] | None = None,
    extensions: Mapping[str, Any] | None = None,
) -> JSONResponse:
    body = Problem(
        type=f"https://errors.pre-sales-agent/{code}",
        title=title or HTTPStatus(status).phrase,
        status=status,
        code=code,
        detail=detail,
        instance=request.url.path,
    ).model_dump()
    for name, value in (extensions or {}).items():
        body.setdefault(name, value)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


async def _problem_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemError)
    return problem_response(
        request,
        exc.status,
        exc.code,
        title=exc.title,
        detail=exc.detail,
        headers=exc.headers,
        extensions=exc.extensions,
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    detail: str | None = exc.detail if isinstance(exc.detail, str) else None
    if detail == HTTPStatus(exc.status_code).phrase:
        detail = None
    headers = dict(exc.headers) if exc.headers else None
    return problem_response(request, exc.status_code, code, detail=detail, headers=headers)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields = sorted({".".join(str(p) for p in err.get("loc", ())) for err in exc.errors()})
    detail = "Invalid fields: " + ", ".join(fields)
    return problem_response(request, 422, "validation_error", detail=detail)


async def _stale_data_error(request: Request, exc: Exception) -> JSONResponse:
    """A concurrent update won the race: SQLAlchemy's versioned UPDATE matched no row."""
    assert isinstance(exc, StaleDataError)
    _log.info("db.stale_data", extra={"path": request.url.path})
    return problem_response(
        request,
        RowVersionMismatchError.status,
        RowVersionMismatchError.code,
        title=RowVersionMismatchError.title,
        detail="The resource was changed by someone else. Reload it and try again.",
    )


async def unhandled_error_response(request: Request, exc: Exception) -> JSONResponse:
    _log.error("request.unhandled_error", exc_info=exc, extra={"path": request.url.path})
    return problem_response(request, 500, "internal_error")


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemError, _problem_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StaleDataError, _stale_data_error)
    app.add_exception_handler(Exception, unhandled_error_response)
