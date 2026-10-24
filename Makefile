# Repository tasks. `make eval ARGS="--only <slug> --config pm_agent=2"` (Story 7.6, evals/README.md).
# `make eval-conflicts ARGS="--only <case>"` (Story 6.2): semantic Conflict detection baseline.
# `make eval-critic ARGS="--only <case>"` (Story 6.4): share of seeded defects the Critic finds;
# fails unless every case's uncovered Requirement is reported.
# `make eval-retrieval` (Story 3.3): Knowledge search hit rate at k and citation validity
# (needs the eval database and `ollama pull bge-m3`).
.PHONY: eval eval-conflicts eval-critic eval-retrieval

eval:
	cd backend && uv run python -m app.evals run $(ARGS)

eval-conflicts:
	cd backend && uv run python -m app.evals conflicts $(ARGS)

eval-critic:
	cd backend && uv run python -m app.evals critic $(ARGS)

eval-retrieval:
	cd backend && uv run python -m app.evals retrieval $(ARGS)
