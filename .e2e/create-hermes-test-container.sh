#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

BASE="${HERMES_BASE_DIR:-$ROOT/.e2e/hermes-base}"
TEST="${HERMES_TEST_DIR:-$ROOT/.e2e/hermes-test}"
CONTAINER="${HERMES_TEST_CONTAINER:-hermes-clawchat-skills-test}"
IMAGE="${HERMES_TEST_IMAGE:-nousresearch/hermes-agent:v2026.7.7.2}"
API_PORT="${HERMES_TEST_API_PORT:-}"
SHM_SIZE="${HERMES_TEST_SHM_SIZE:-1g}"
BOOT_WAIT="${HERMES_TEST_BOOT_WAIT:-3}"

usage() {
  cat <<EOF
Usage: $0 [--no-skills | SKILL_PATH ...]

Mount only the selected repository skills into the Hermes test container.
Paths may be relative to the repository root or absolute paths within it.
When no path is provided, all repository skills are mounted.
Use --no-skills to start from the Hermes base without mounting any skills.

Examples:
  $0 --no-skills
  $0 creative/tarot-arcana
  $0 productivity/clawchat-officecli creative/tarot-arcana
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

if [ ! -d "$BASE" ]; then
  echo "ERROR: missing Hermes base directory: $BASE" >&2
  exit 1
fi

skill_dirs=()
no_skills=false
if [ "${1:-}" = "--no-skills" ]; then
  if [ "$#" -ne 1 ]; then
    echo "ERROR: --no-skills cannot be combined with skill paths" >&2
    exit 1
  fi
  no_skills=true
elif [ "$#" -gt 0 ]; then
  for skill_path in "$@"; do
    if [[ "$skill_path" = /* ]]; then
      candidate="$skill_path"
    else
      candidate="$ROOT/$skill_path"
    fi

    if [ ! -d "$candidate" ]; then
      echo "ERROR: skill directory does not exist: $skill_path" >&2
      exit 1
    fi

    skill_dir="$(cd "$candidate" && pwd -P)"
    case "$skill_dir" in
      "$ROOT"/*) ;;
      *)
        echo "ERROR: skill directory must be inside the repository: $skill_path" >&2
        exit 1
        ;;
    esac

    if [ ! -f "$skill_dir/SKILL.md" ]; then
      echo "ERROR: skill directory does not contain SKILL.md: $skill_path" >&2
      exit 1
    fi

    skill_dirs+=("$skill_dir")
  done
else
  while IFS= read -r skill_file; do
    skill_dirs+=("$(dirname "$skill_file")")
  done < <(find "$ROOT" -mindepth 3 -maxdepth 3 -type f -name SKILL.md \
    -not -path "$ROOT/.e2e/*" -print | sort)
fi

if [ "$no_skills" = false ] && [ "${#skill_dirs[@]}" -eq 0 ]; then
  echo "ERROR: no skill directories found under: $ROOT" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is not available in PATH" >&2
  exit 1
fi

echo "Removing existing test container if present: $CONTAINER"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

echo "Recreating test data directory: $TEST"
if [ -e "$TEST" ]; then
  chmod -R u+rwX "$TEST" 2>/dev/null || true
  rm -rf "$TEST"
fi
mkdir -p "$(dirname "$TEST")"
cp -a "$BASE" "$TEST"

# Runtime output and the skill prompt cache must be fresh for every run. The
# source skills are mounted below, so a snapshot copied from the base would be
# stale as soon as a skill changes.
chmod -R u+rwX "$TEST/logs" 2>/dev/null || true
rm -rf "$TEST/logs"
rm -f "$TEST/.skills_prompt_snapshot.json"
mkdir -p "$TEST/logs"

run_args=(
  -d
  --name "$CONTAINER"
  --restart no
  --shm-size "$SHM_SIZE"
  -e "HERMES_UID=$(id -u)"
  -e "HERMES_GID=$(id -g)"
  -v "$TEST:/opt/data"
)

# Mount the selected repository skills over their matching Hermes directories.
# This keeps one editable source of truth while the running container
# immediately sees local changes.
if [ "$no_skills" = false ]; then
  for skill_dir in "${skill_dirs[@]}"; do
    relative_path="${skill_dir#"$ROOT/"}"
    container_path="/opt/data/skills/$relative_path"
    echo "Skill under test: $skill_dir -> $container_path"
    run_args+=( -v "$skill_dir:$container_path" )
  done
fi

# Publishing the API server is opt-in to avoid colliding with a developer's
# normal Hermes gateway. Example: HERMES_TEST_API_PORT=8642 ./.e2e/create-...
if [ -n "$API_PORT" ]; then
  run_args+=( -p "$API_PORT:8642" )
fi

echo "Starting Hermes test container: $CONTAINER"
docker run "${run_args[@]}" "$IMAGE" gateway run >/dev/null

sleep "$BOOT_WAIT"

if ! docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null | grep -qx true; then
  echo "ERROR: Hermes test container failed to stay running: $CONTAINER" >&2
  docker logs "$CONTAINER" >&2 || true
  exit 1
fi

echo "Container status:"
docker ps --filter "name=^/${CONTAINER}$" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'

echo
echo "Hermes test directory: $TEST"
echo "Container mount: $CONTAINER:/opt/data"
echo
echo "To inspect:"
echo "docker exec -it $CONTAINER hermes config"
