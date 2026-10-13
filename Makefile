# Repository tasks. `make eval ARGS="--only <slug> --config pm_agent=2"` (Story 7.6, evals/README.md).
.PHONY: eval

eval:
	cd backend && uv run python -m app.evals run $(ARGS)
