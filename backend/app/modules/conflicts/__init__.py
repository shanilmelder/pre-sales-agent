"""The `conflicts` module (Epic 6): Conflicts between the specialist Assessments.

Demo scope (Story 6.1): every time an assessment run finishes, `detect_for_run` runs the
deterministic rules in `domain/rules/` over each agent's current Assessment and the current
Estimate draft, and stores each disagreement as a Conflict (`raise_conflict`, the single
write, idempotent per run and fingerprint) with one position per side. On a later run a
Conflict that no longer holds is resolved by the system; one that still holds is raised
again, linking the earlier one. The Conflicts tab lists them read-only.

No resolving or escalating by people, no semantic detection. Other modules use it only
through `application/public.py`.
"""
