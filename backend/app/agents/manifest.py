"""The deploy manifest (Story 7.1): what this image can run, with content hashes.

- **Prompts:** every `agents/<agent_id>/prompts/v<N>.md` and `v<N>-<name>.md`, grouped by
  agent and prompt version N, each with its sha256 (line endings normalised to `\\n`, so a
  Windows checkout hashes the same as CI).
- **Schemas:** every registered `SchemaVersion(agent, kind, version, model, contract_version)`:
  an agent's input (its task) or output (its extension) at a version, hashed from
  `TypeAdapter(model).json_schema()`. The Pydantic models (and task dataclasses) are the
  source of truth; the JSON Schema is generated from them.
- **Profiles:** every ModelGateway profile, with its provider and model.

`manifest.json` next to this file is generated (`uv run python -m app.agents.manifest`) and
committed; CI regenerates it and fails on any `git diff` (locally, `--check` exits 1 on
drift). The Agent Registry loads it at
runtime (`load()`) and refuses a config version that references anything outside it
(`registry_config_not_deployed`) or whose output schema's contract version is not
`CONTRACT_VERSION` (`registry_config_incompatible_contract`).

Adding a prompt or changing a schema: bump the version here (a new `SchemaVersion` row), then
regenerate the manifest; an existing version's hash must not change once a config pins it.
"""

import hashlib
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import TypeAdapter

from app.agents.clarification_agent.agent import AnswersTask, ClarificationTask
from app.agents.clarification_agent.schema import AnswerMatchOutput, ClarificationOutput
from app.agents.conflict_agent.agent import ConflictTask
from app.agents.conflict_agent.schema import ConflictOutput
from app.agents.contract import CONTRACT_VERSION
from app.agents.critic_agent.agent import CriticTask
from app.agents.critic_agent.schema import CriticOutput
from app.agents.engineering_agent.schema import EngineeringOutput
from app.agents.estimating_agent.agent import AssumptionsTask, EstimatingTask
from app.agents.estimating_agent.schema import AssumptionsOutput, EstimatingOutput
from app.agents.intake_agent.agent import IntakeTask
from app.agents.intake_agent.schema import IntakeOutput
from app.agents.opportunity_intake_agent.agent import OpportunityIntakeTask
from app.agents.opportunity_intake_agent.schema import OpportunityIntakeOutput
from app.agents.pm_agent.schema import PmOutput
from app.agents.red_team_agent.agent import RedTeamTask
from app.agents.red_team_agent.schema import RedTeamOutput
from app.agents.security_agent.schema import SecurityOutput
from app.agents.specialist.agent import SpecialistTask
from app.platform.model_gateway.profiles import MODEL_PROFILES

AGENTS_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = AGENTS_DIR / "manifest.json"
PROMPT_FILE_RE = re.compile(r"^v([1-9]\d*)(?:-[a-z0-9][a-z0-9_-]*)?\.md$")

SchemaKind = Literal["input", "output"]

REQUIRED_PROMPTS: dict[str, tuple[str, ...]] = {
    "clarification_agent": ("answers",),
    "estimating_agent": ("assumptions",),
}
"""Named prompt files an agent reads besides `v<N>.md`: prompt version N is deployed only
when `v<N>-<name>.md` is too (`clarification_agent` reads `v<N>-answers.md`,
`estimating_agent` reads `v<N>-assumptions.md`)."""


@dataclass(frozen=True, slots=True)
class SchemaVersion:
    """One version of an agent's input or output schema."""

    agent: str
    kind: SchemaKind
    version: int
    model: Any
    """A Pydantic model, a dataclass or a union of them: anything `TypeAdapter` takes."""
    contract_version: str
    """The `AgentResult.contract_version` the schema was written for."""


SCHEMA_VERSIONS: tuple[SchemaVersion, ...] = (
    SchemaVersion("clarification_agent", "input", 1, ClarificationTask | AnswersTask, "1"),
    SchemaVersion("clarification_agent", "output", 1, ClarificationOutput | AnswerMatchOutput, "1"),
    SchemaVersion("conflict_agent", "input", 1, ConflictTask, "1"),
    SchemaVersion("conflict_agent", "output", 1, ConflictOutput, "1"),
    SchemaVersion("critic_agent", "input", 1, CriticTask, "1"),
    SchemaVersion("critic_agent", "output", 1, CriticOutput, "1"),
    SchemaVersion("engineering_agent", "input", 1, SpecialistTask, "1"),
    SchemaVersion("engineering_agent", "output", 1, EngineeringOutput, "1"),
    SchemaVersion("estimating_agent", "input", 1, EstimatingTask | AssumptionsTask, "1"),
    SchemaVersion("estimating_agent", "output", 1, EstimatingOutput | AssumptionsOutput, "1"),
    SchemaVersion("intake_agent", "input", 1, IntakeTask, "1"),
    SchemaVersion("intake_agent", "output", 1, IntakeOutput, "1"),
    SchemaVersion("opportunity_intake_agent", "input", 1, OpportunityIntakeTask, "1"),
    SchemaVersion("opportunity_intake_agent", "output", 1, OpportunityIntakeOutput, "1"),
    SchemaVersion("pm_agent", "input", 1, SpecialistTask, "1"),
    SchemaVersion("pm_agent", "output", 1, PmOutput, "1"),
    SchemaVersion("red_team_agent", "input", 1, RedTeamTask, "1"),
    SchemaVersion("red_team_agent", "output", 1, RedTeamOutput, "1"),
    SchemaVersion("security_agent", "input", 1, SpecialistTask, "1"),
    SchemaVersion("security_agent", "output", 1, SecurityOutput, "1"),
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prompt_hash(path: Path) -> str:
    """The prompt file's sha256, with CRLF normalised to LF."""
    return _sha256(path.read_bytes().replace(b"\r\n", b"\n"))


def schema_hash(model: Any) -> str:
    schema = TypeAdapter(model).json_schema()
    return _sha256(json.dumps(schema, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _prompts(agents_dir: Path) -> dict[str, dict[str, dict[str, str]]]:
    found: dict[str, dict[str, dict[str, str]]] = {}
    for path in sorted(agents_dir.glob("*/prompts/*.md")):
        match = PROMPT_FILE_RE.match(path.name)
        if match is None:
            continue
        agent = path.parent.parent.name
        version = found.setdefault(agent, {}).setdefault(match.group(1), {})
        version[path.name] = prompt_hash(path)
    return found


def build(agents_dir: Path = AGENTS_DIR) -> dict[str, Any]:
    """The manifest computed from the code: prompts, schemas and profiles."""
    schemas: dict[str, dict[str, dict[str, dict[str, str]]]] = {}
    for item in SCHEMA_VERSIONS:
        kinds = schemas.setdefault(item.agent, {"input": {}, "output": {}})
        key = str(item.version)
        if key in kinds[item.kind]:
            raise ValueError(f"{item.agent} {item.kind} schema v{key} is registered twice")
        kinds[item.kind][key] = {
            "sha256": schema_hash(item.model),
            "contract_version": item.contract_version,
        }
    return {
        "contract_version": CONTRACT_VERSION,
        "prompts": _prompts(agents_dir),
        "schemas": schemas,
        "profiles": {
            name: {"provider": profile.provider, "model": profile.model}
            for name, profile in sorted(MODEL_PROFILES.items())
        },
    }


def render(manifest: Mapping[str, Any]) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True, slots=True)
class Manifest:
    """The deployed manifest, as loaded. Lookups take an agent id and version numbers."""

    data: Mapping[str, Any]

    def has_prompt(self, agent: str, version: int) -> bool:
        """`v<version>.md` and every named prompt the agent reads at that version."""
        files = self.data.get("prompts", {}).get(agent, {}).get(str(version))
        if not isinstance(files, Mapping):
            return False
        needed = [f"v{version}.md"] + [
            f"v{version}-{name}.md" for name in REQUIRED_PROMPTS.get(agent, ())
        ]
        return all(name in files for name in needed)

    def schema(self, agent: str, kind: SchemaKind, version: int) -> Mapping[str, str] | None:
        """The schema entry (`sha256`, `contract_version`), or None if not deployed."""
        entry = self.data.get("schemas", {}).get(agent, {}).get(kind, {}).get(str(version))
        return entry if isinstance(entry, Mapping) else None

    def has_profile(self, name: str) -> bool:
        return name in self.data.get("profiles", {})

    def prompt_versions(self, agent: str) -> list[int]:
        """The agent's deployed prompt versions (each passing `has_prompt`), ascending."""
        listed = self.data.get("prompts", {}).get(agent, {})
        found = [int(key) for key in listed if str(key).isdigit()]
        return sorted(v for v in found if self.has_prompt(agent, v))

    def schemas(self, agent: str, kind: SchemaKind) -> dict[int, Mapping[str, str]]:
        """The agent's deployed schema versions of this kind, by version, ascending."""
        listed = self.data.get("schemas", {}).get(agent, {}).get(kind, {})
        found = {
            int(key): entry
            for key, entry in listed.items()
            if str(key).isdigit() and isinstance(entry, Mapping)
        }
        return dict(sorted(found.items()))

    def profiles(self) -> list[str]:
        """Every deployed model profile name, sorted."""
        return sorted(self.data.get("profiles", {}))


@cache
def load() -> Manifest:
    """The committed `manifest.json` (read once per process)."""
    return Manifest(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def main(argv: list[str]) -> int:
    """Write `manifest.json`; with `--check`, exit 1 instead if it is out of date."""
    rendered = render(build())
    if "--check" in argv:
        current = MANIFEST_PATH.read_text(encoding="utf-8") if MANIFEST_PATH.exists() else ""
        if current.replace("\r\n", "\n") != rendered:
            print("app/agents/manifest.json is out of date: run `python -m app.agents.manifest`")
            return 1
        return 0
    MANIFEST_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
