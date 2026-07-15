#!/usr/bin/env bash
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
OFFICE_BIN="${OFFICE_BIN:-$(command -v officecli || true)}"
OFFICE_BIN="${OFFICE_BIN:-${HOME}/.local/bin/officecli}"
if [ ! -x "$OFFICE_BIN" ] && [ -x "${HERMES_HOME}/home/.local/bin/officecli" ]; then
  OFFICE_BIN="${HERMES_HOME}/home/.local/bin/officecli"
fi

changed=0
if [ ! -x "$OFFICE_BIN" ] || ! DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" --help >/dev/null 2>&1; then
  scratch="${HERMES_HOME}/workspace/office-live/.state/scratch"
  installer="${scratch}/officecli-install.sh"
  mkdir -p "$scratch"
  curl -fsSL https://d.officecli.ai/install.sh -o "$installer"
  bash "$installer"
  OFFICE_BIN="$(command -v officecli || true)"
  OFFICE_BIN="${OFFICE_BIN:-${HOME}/.local/bin/officecli}"
  changed=1
fi

DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" --help >/dev/null
skills_text="$(hermes skills list 2>/dev/null || true)"

ensure_skill() {
  local skill_id="$1" install_id="$2"
  case "$skills_text" in *"$skill_id"*) return 0;; esac
  if [ -f "${HERMES_HOME}/skills/${skill_id}/SKILL.md" ] || [ -f "${HERMES_HOME}/skills/productivity/${skill_id}/SKILL.md" ]; then
    return 0
  fi
  DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills install "$install_id" hermes
  changed=1
}

DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1 "$OFFICE_BIN" skills hermes >/dev/null
ensure_skill officecli-docx word
ensure_skill officecli-pptx pptx
ensure_skill officecli-xlsx excel
ensure_skill officecli-word-form word-form
ensure_skill morph-ppt morph-ppt
ensure_skill morph-ppt-3d morph-ppt-3d
ensure_skill officecli-pitch-deck pitch-deck
ensure_skill officecli-academic-paper academic-paper
ensure_skill officecli-data-dashboard data-dashboard
ensure_skill officecli-financial-model financial-model

if [ "$changed" -eq 1 ]; then
  echo "OFFICECLI_RESULT=installed"
else
  echo "OFFICECLI_RESULT=ready"
fi
