#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  printf 'Usage: bash scripts/install-codex.sh\n' >&2
  exit 2
fi

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd -- "$repo_root"

targets=(.codex/agents)
sources=(../codex/agents)
canonical_sources=(codex/agents)

while IFS= read -r skill || [[ -n "$skill" ]]; do
  [[ -z "$skill" || "$skill" == \#* ]] && continue
  if [[ ! "$skill" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
    printf 'Invalid skill name in codex/skills.list: %s\n' "$skill" >&2
    exit 1
  fi
  targets+=(".agents/skills/$skill")
  sources+=("../../shared/skills/$skill")
  canonical_sources+=("shared/skills/$skill")
done < codex/skills.list

# Migrate only the exact broad connection made by the first installer revision.
migrate_skills=false
if [[ -L .agents/skills ]]; then
  if [[ "$(readlink .agents/skills)" == ../shared/skills ]]; then
    migrate_skills=true
  else
    printf 'Conflict: .agents/skills points elsewhere. Nothing was replaced.\n' >&2
    exit 1
  fi
elif [[ -e .agents/skills && ! -d .agents/skills ]]; then
  printf 'Conflict: .agents/skills must be a directory. Nothing was replaced.\n' >&2
  exit 1
fi

# Check every destination before making any changes.
for parent in .codex .agents; do
  if [[ -L "$parent" || ( -e "$parent" && ! -d "$parent" ) ]]; then
    printf 'Conflict: %s must be a real directory. Nothing was replaced.\n' "$parent" >&2
    exit 1
  fi
done

for i in "${!targets[@]}"; do
  target="${targets[$i]}"
  canonical_source="${canonical_sources[$i]}"
  if [[ ! -d "$canonical_source" ]]; then
    printf 'Missing source: %s\n' "$canonical_source" >&2
    exit 1
  fi
  if [[ "$migrate_skills" == true && "$target" == .agents/skills/* ]]; then
    continue
  fi
  if [[ -L "$target" ]]; then
    if [[ "$(readlink "$target")" != "${sources[$i]}" ]]; then
      printf 'Conflict: %s points elsewhere. Nothing was replaced.\n' "$target" >&2
      exit 1
    fi
  elif [[ -e "$target" ]]; then
    printf 'Conflict: %s already exists. Nothing was replaced.\n' "$target" >&2
    exit 1
  fi
done

if [[ "$migrate_skills" == true ]]; then
  unlink .agents/skills
  printf 'Replaced the broad discovery link; all shared skill sources are preserved.\n'
fi
mkdir -p .codex .agents/skills
for i in "${!targets[@]}"; do
  if [[ ! -L "${targets[$i]}" ]]; then
    ln -s "${sources[$i]}" "${targets[$i]}"
  fi
  printf '%s -> %s\n' "${targets[$i]}" "${sources[$i]}"
done
printf 'Repository connections ready. Run: python3 scripts/doctor.py\n'
