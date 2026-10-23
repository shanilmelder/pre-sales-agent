#!/usr/bin/env bash
# Pull the current branch, rebuild and recreate the local Docker stack, apply any pending
# Alembic migrations, then smoke-check it. Run from anywhere inside the repo (Git Bash).
#
#   redeploy.sh                 pull + rebuild + migrate + smoke
#   redeploy.sh --no-pull       skip the git pull (deploy the working tree as it is)
#   redeploy.sh --migrate       only the migration step (stack already up)
#   redeploy.sh --smoke         only the health checks and the screenshot
#
# MIGRATE_DB=psa_test migrates another database on the same server instead of .env's
# POSTGRES_DB (used to exercise the upgrade path without touching the dev data).
#
# Exit codes: 0 ok, 1 pull failed, 2 compose failed, 3 migration failed, 4 smoke failed.
set -uo pipefail

ROOT=$(git rev-parse --show-toplevel) || exit 1
cd "$ROOT"
SHOT_DIR="${SHOT_DIR:-$ROOT/.claude/skills/run-pre-sales-agent/shots}"
CHROME="${CHROME:-/c/Program Files/Google/Chrome/Application/chrome.exe}"
COMPOSE=(docker compose --profile local)

PULL=1
SMOKE_ONLY=0
MIGRATE_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --no-pull) PULL=0 ;;
    --smoke) SMOKE_ONLY=1 ;;
    --migrate) MIGRATE_ONLY=1 ;;
    *) echo "unknown option: $arg" >&2; exit 64 ;;
  esac
done

step() { printf '\n==> %s\n' "$*"; }

# One value from .env, without sourcing it (sourcing exports the model-profile variables
# into this shell too).
env_value() { grep -E "^$1=" .env | head -1 | cut -d= -f2-; }

pull() {
  local branch
  branch=$(git branch --show-current)
  step "git pull --ff-only origin $branch"
  # A branch that was never pushed has nothing to pull: deploy it as it is.
  if [ "$(git ls-remote --heads origin "$branch" 2>/dev/null | wc -l)" -eq 0 ] &&
    git ls-remote origin HEAD >/dev/null 2>&1; then
    echo "origin has no branch '$branch'; skipping the pull"
    return 0
  fi
  git fetch origin "$branch" && git merge --ff-only "origin/$branch" && return 0
  # The default credential (shanil-melder) can't read or write this repo; retry as
  # shanilmelder through gh, without changing gh's active account.
  if command -v gh >/dev/null && gh auth token -u shanilmelder >/dev/null 2>&1; then
    echo "retrying with the shanilmelder gh token"
    GH_TOKEN=$(gh auth token -u shanilmelder) git -c credential.helper= \
      -c "credential.helper=!gh auth git-credential" fetch origin "$branch" &&
      git merge --ff-only "origin/$branch" && return 0
  fi
  echo "pull failed: resolve it by hand (diverged branch or local changes in the way)" >&2
  return 1
}

rebuild() {
  step "docker compose up --build --force-recreate --wait"
  "${COMPOSE[@]}" up --build --force-recreate --wait -d
}

# Alembic as the owner role; the api container itself runs as psa_app.
alembic() {
  local url
  url="postgresql+psycopg://$(env_value POSTGRES_USER):$(env_value POSTGRES_PASSWORD)@postgres:5432/${MIGRATE_DB:-$(env_value POSTGRES_DB)}"
  "${COMPOSE[@]}" exec -T -e PSA_MIGRATIONS_DATABASE_URL="$url" api alembic "$@" 2>&1 |
    grep -v '^INFO  \[alembic.runtime.migration\] \(Context impl\|Will assume\)'
}

migrate() {
  step "database migrations"
  local current head
  current=$(alembic current | tail -1 | awk '{print $1}')
  head=$(alembic heads | tail -1 | awk '{print $1}')
  echo "current: ${current:-<none>}  head: ${head:-<unknown>}"
  [ -n "$head" ] || { echo "could not read the Alembic head" >&2; return 1; }
  if [ "$current" = "$head" ]; then
    echo "already at head; nothing to upgrade"
    return 0
  fi
  alembic upgrade head || return 1
  echo "now: $(alembic current | tail -1)"
  # The api and worker started against the old schema; restart them on the new one.
  [ -n "${MIGRATE_DB:-}" ] && return 0
  echo "restarting api and worker"
  "${COMPOSE[@]}" restart api worker >/dev/null && "${COMPOSE[@]}" up --wait -d >/dev/null
}

smoke() {
  step "smoke checks"
  local ok=0 api web
  api=$(curl -fsS http://localhost:8000/api/v1/health) || ok=1
  web=$(curl -fsS http://localhost:3000/healthz) || ok=1
  echo "api: ${api:-DOWN}"
  echo "web: ${web:-DOWN}"
  "${COMPOSE[@]}" ps --format '{{.Service}}: {{.Status}}'
  # The web root redirects to /auth/login, then to the Auth0 hosted sign-in page.
  local login
  login=$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' http://localhost:3000/)
  echo "web /: $login"
  if [ -x "$CHROME" ]; then
    mkdir -p "$SHOT_DIR"
    local shot="$SHOT_DIR/signin.png"
    "$CHROME" --headless=new --disable-gpu --hide-scrollbars --window-size=1440,900 \
      --virtual-time-budget=8000 --screenshot="$(cygpath -w "$shot")" \
      http://localhost:3000/ >/dev/null 2>&1
    [ -s "$shot" ] && echo "screenshot: $shot" || { echo "screenshot failed" >&2; ok=1; }
  fi
  return $ok
}

if [ "$SMOKE_ONLY" = 1 ]; then smoke || exit 4; exit 0; fi
if [ "$MIGRATE_ONLY" = 1 ]; then migrate || exit 3; exit 0; fi
if [ "$PULL" = 1 ]; then pull || exit 1; fi
rebuild || exit 2
migrate || exit 3
smoke || exit 4
step "done: $(git branch --show-current) @ $(git rev-parse --short HEAD)"
