"""Business modules.

Each module lives in `app/modules/<module>/` with four layers (architecture spine, Design Paradigm):

- `api/`          HTTP adapters; may depend on its own `application`.
- `application/`  commands and queries; `public.py` is the only cross-module entry point.
- `domain/`       entities, state machines, rules and ports; depends on nothing outside itself.
- `adapters/`     DB repositories and external systems; implements its own `domain` ports.

A module never imports another module's `domain` or `adapters` (AD-2), and never imports
`langgraph` (AD-5). Both rules are enforced by `tests/test_architecture.py`.
Modules: `identity` (users, roles, the action catalogue and policy), `opportunities`
(Opportunities and collaborators), `intake` (Opportunity Sources and Requirements), `gaps`
(Gaps and Clarification Questions), `estimates` (Estimate Versions and their lines) and
`assessments` (Red Team Reviews and their Findings).
"""
