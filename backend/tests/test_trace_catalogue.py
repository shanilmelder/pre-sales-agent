"""The trace catalogue's CI guard (Story 9.8): every event type the app appends has a
registered payload model, and no payload model can carry model reasoning or prompt text.

Two independent checks find the payloads the app uses: importing every `app` module and
collecting each `TracePayload` subclass defined there, and scanning the source for
`trace.append(...)` calls and the payload classes their `payload=` argument builds. The
checks are plain functions so the failure cases are tested too.
"""

import ast
import importlib
import pkgutil
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import ClassVar

import app
from app.platform.trace.catalogue import CATALOGUE, TracePayload

APP_DIR = Path(app.__file__).parent
FORBIDDEN_WORDS = ("prompt", "reasoning", "thought", "chain")


# --- the checks ------------------------------------------------------------------------------


def import_every_app_module() -> None:
    for module in pkgutil.walk_packages([str(APP_DIR)], prefix="app."):
        importlib.import_module(module.name)


def _subclasses(cls: type) -> Iterator[type]:
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)


def app_payload_classes() -> list[type[TracePayload]]:
    """Every `TracePayload` subclass defined under `app` (after importing it all)."""
    return [cls for cls in _subclasses(TracePayload) if cls.__module__.startswith("app.")]


def unregistered(classes: Iterable[type[TracePayload]]) -> list[str]:
    """The classes that aren't the catalogue's model for their `event_type`."""
    return sorted(
        cls.__qualname__
        for cls in classes
        if CATALOGUE.get(getattr(cls, "event_type", "")) is not cls
    )


def forbidden_fields(classes: Iterable[type[TracePayload]]) -> list[str]:
    """`Model.field` for every payload field whose name contains a forbidden word."""
    return sorted(
        f"{cls.__qualname__}.{name}"
        for cls in classes
        for name in cls.model_fields
        if any(word in name.lower() for word in FORBIDDEN_WORDS)
    )


def _is_trace_append(call: ast.Call) -> bool:
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "append"
        and isinstance(func.value, ast.Name)
        and func.value.id == "trace"
    )


def _class_names(node: ast.AST) -> set[str]:
    """The capitalised names the expression's outermost call calls, e.g. `Foo(...)` or
    `(A if x else B)(...)`, or either branch's for `A(...) if x else B(...)`. Calls inside
    the arguments don't count."""
    if isinstance(node, ast.IfExp):
        return _class_names(node.body) | _class_names(node.orelse)
    if not isinstance(node, ast.Call):
        return set()
    return {
        inner.id
        for inner in ast.walk(node.func)
        if isinstance(inner, ast.Name) and inner.id[:1].isupper()
    }


def appended_payload_classes(source: str) -> list[tuple[int, set[str]]]:
    """For each `trace.append(...)` call in `source`: its line and the payload class names
    its `payload=` argument builds, directly or through a variable assigned in the same
    function, or a parameter annotated with it. An empty set means the payload couldn't be
    traced to a class."""
    tree = ast.parse(source)
    # Keyed by line: a nested function's calls are also inside its parent's walk, and the
    # innermost scope (walked last) resolves them best.
    found: dict[int, set[str]] = {}
    scopes: list[ast.AST] = [
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ] or [tree]
    for scope in scopes:
        assigned: dict[str, set[str]] = {}
        if isinstance(scope, ast.FunctionDef | ast.AsyncFunctionDef):
            # A payload handed in as a parameter: its annotation names the class.
            for arg in (*scope.args.posonlyargs, *scope.args.args, *scope.args.kwonlyargs):
                if isinstance(arg.annotation, ast.Name) and arg.annotation.id[:1].isupper():
                    assigned[arg.arg] = {arg.annotation.id}
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assigned.setdefault(target.id, set()).update(_class_names(node.value))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    assigned.setdefault(node.target.id, set()).update(_class_names(node.value))
        for node in ast.walk(scope):
            if not (isinstance(node, ast.Call) and _is_trace_append(node)):
                continue
            payload = next((kw.value for kw in node.keywords if kw.arg == "payload"), None)
            if payload is None:
                found[node.lineno] = set()
            elif isinstance(payload, ast.Name):
                found[node.lineno] = assigned.get(payload.id, set())
            else:
                found[node.lineno] = _class_names(payload)
    return sorted(found.items())


def untraceable_appends(sources: Iterable[tuple[str, str]]) -> list[str]:
    """`path:line` for every `trace.append` whose payload isn't built from registered
    payload classes only."""
    registered = {cls.__name__ for cls in CATALOGUE.values()}
    problems: list[str] = []
    for path, source in sources:
        for line, names in appended_payload_classes(source):
            if not names or not names <= registered:
                problems.append(f"{path}:{line} {sorted(names)}")
    return problems


def app_sources() -> list[tuple[str, str]]:
    return [
        (str(path.relative_to(APP_DIR)), path.read_text(encoding="utf-8"))
        for path in sorted(APP_DIR.rglob("*.py"))
    ]


# --- against the app ---------------------------------------------------------------------------


def test_every_payload_model_in_the_app_is_registered() -> None:
    import_every_app_module()
    classes = app_payload_classes()
    assert len(classes) >= len(CATALOGUE)
    assert unregistered(classes) == []


def test_every_appended_event_type_has_a_registered_payload_model() -> None:
    sources = app_sources()
    calls = [call for _, source in sources for call in appended_payload_classes(source)]
    assert len(calls) >= 19, "the scan should find the app's trace.append calls"
    assert untraceable_appends(sources) == []


def test_no_payload_field_carries_prompts_or_reasoning() -> None:
    import_every_app_module()
    assert forbidden_fields(app_payload_classes()) == []
    assert forbidden_fields(CATALOGUE.values()) == []


# --- the checks catch what they should ---------------------------------------------------------


def test_a_prompt_or_reasoning_field_fails_the_check() -> None:
    class Leaky(TracePayload):
        event_type: ClassVar[str] = "intake.extraction.leaked"

        prompt_text: str
        model_reasoning: str
        thoughts: int
        chain_of_steps: int
        version: int

    assert forbidden_fields([Leaky]) == [
        "test_a_prompt_or_reasoning_field_fails_the_check.<locals>.Leaky.chain_of_steps",
        "test_a_prompt_or_reasoning_field_fails_the_check.<locals>.Leaky.model_reasoning",
        "test_a_prompt_or_reasoning_field_fails_the_check.<locals>.Leaky.prompt_text",
        "test_a_prompt_or_reasoning_field_fails_the_check.<locals>.Leaky.thoughts",
    ]


def test_an_unregistered_payload_model_fails_the_check() -> None:
    class Unlisted(TracePayload):
        event_type: ClassVar[str] = "intake.extraction.unlisted"

    assert unregistered([Unlisted]) == [
        "test_an_unregistered_payload_model_fails_the_check.<locals>.Unlisted"
    ]


def test_an_append_of_an_unregistered_payload_fails_the_check() -> None:
    source = """
async def direct(uow):
    await trace.append(uow, actor=a, payload=IntakeSourceParsed(version=1, char_count=2))
    await trace.append(uow, actor=a, payload=NotInTheCatalogue(x=1))

async def via_variable(uow, flag):
    event = (GapsGapRaised if flag else AlsoMissing)(detection_id="d")
    await trace.append(uow, actor=a, payload=event)

async def untraceable(uow, made):
    await trace.append(uow, actor=a, payload=made)

async def parameter(uow, done: GapsDetectionCompleted, other: Unknown):
    await trace.append(uow, actor=a, payload=done)
    await trace.append(uow, actor=a, payload=other)
"""
    assert untraceable_appends([("x.py", source)]) == [
        "x.py:4 ['NotInTheCatalogue']",
        "x.py:8 ['AlsoMissing', 'GapsGapRaised']",
        "x.py:11 []",
        "x.py:15 ['Unknown']",
    ]
