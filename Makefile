# Repository tasks. `make eval ARGS="--only <slug> --config pm_agent=2"` (Story 7.6, evals/README.md).
# `make eval-conflicts ARGS="--only <case>"` (Story 6.2): semantic Conflict detection baseline.
.PHONY: eval eval-conflicts

eval:
	cd backend && uv run python -m app.evals run $(ARGS)

eval-conflicts:
	cd backend && uv run python -m app.evals conflicts $(ARGS)
