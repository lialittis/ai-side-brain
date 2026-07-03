#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

PERSONAL_ROOT="${PERSONAL_RADAR_ROOT:-$ROOT_DIR}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET_SPEC="${PERSONAL_RADAR_BACKUP_TARGETS:-}"
DRY_RUN="${PERSONAL_RADAR_BACKUP_DRY_RUN:-0}"
INCLUDE_PDF_CACHE="${PERSONAL_RADAR_BACKUP_INCLUDE_PDF_CACHE:-0}"
INDEX_DIR="${PERSONAL_RADAR_BACKUP_INDEX_DIR:-$PERSONAL_ROOT/indexes}"
LOG_DIR="${PERSONAL_RADAR_BACKUP_LOG_DIR:-${PERSONAL_RADAR_OUTPUT_DIR:-$PERSONAL_ROOT/memory/06_Logs}}"
PDF_CACHE_DIR="${PERSONAL_RADAR_PDF_CACHE_DIR:-$PERSONAL_ROOT/memory/06_Logs/literature-radar-pdfs}"
EVIDENCE_DIR="${PERSONAL_RADAR_BACKUP_EVIDENCE_DIR:-${PERSONAL_RADAR_OUTPUT_DIR:-$PERSONAL_ROOT/memory/06_Logs}/backup}"
DRY_RUN_MANIFEST_PATH="$EVIDENCE_DIR/personal-literature-radar-backup-dry-run-$STAMP.manifest.txt"
LATEST_DRY_RUN_MANIFEST_PATH="$EVIDENCE_DIR/personal-literature-radar-backup-dry-run-latest.manifest.txt"

if [[ -z "$TARGET_SPEC" ]]; then
  if [[ "$DRY_RUN" == "1" ]]; then
    TARGET_SPEC="dry-run-target-not-configured"
  else
    echo "PERSONAL_RADAR_BACKUP_TARGETS is required. Set PERSONAL_RADAR_BACKUP_DRY_RUN=1 to inspect inputs without writing a backup." >&2
    exit 2
  fi
fi

IFS=$' \t\n,' read -r -a BACKUP_TARGETS <<< "$TARGET_SPEC"

declare -a CANDIDATE_LABELS=()
declare -a CANDIDATE_PATHS=()
declare -a EXISTING_RELATIVE_PATHS=()
declare -a MISSING_PATHS=()
declare -a EXTERNAL_PATHS=()

add_candidate() {
  local label="$1"
  local path="$2"
  CANDIDATE_LABELS+=("$label")
  CANDIDATE_PATHS+=("$path")
}

absolute_path() {
  local path="$1"
  if [[ "$path" == /* ]]; then
    printf '%s\n' "$path"
  else
    printf '%s\n' "$ROOT_DIR/$path"
  fi
}

relative_to_root() {
  local path="$1"
  local absolute
  absolute="$(absolute_path "$path")"
  if [[ "$absolute" == "$ROOT_DIR" ]]; then
    printf '.\n'
  elif [[ "$absolute" == "$ROOT_DIR/"* ]]; then
    printf '%s\n' "${absolute#"$ROOT_DIR/"}"
  else
    return 1
  fi
}

collect_candidate() {
  local path="$1"
  local absolute
  local relative
  absolute="$(absolute_path "$path")"
  if [[ ! -e "$absolute" ]]; then
    MISSING_PATHS+=("$path")
    return
  fi
  if relative="$(relative_to_root "$path")"; then
    EXISTING_RELATIVE_PATHS+=("$relative")
  else
    EXTERNAL_PATHS+=("$path")
  fi
}

write_manifest() {
  local manifest_path="$1"
  {
    echo "product=personal"
    echo "created_at=$STAMP"
    echo "personal_root=$PERSONAL_ROOT"
    echo "index_dir=$INDEX_DIR"
    echo "log_dir=$LOG_DIR"
    echo "pdf_cache_included=$INCLUDE_PDF_CACHE"
    echo "pdf_cache_dir=$PDF_CACHE_DIR"
    echo "credentials_included=no"
    echo "private_project_memory_included=no"
    echo "included_paths:"
    for path in "${EXISTING_RELATIVE_PATHS[@]}"; do
      echo "- $path"
    done
    if [[ "${#MISSING_PATHS[@]}" -gt 0 ]]; then
      echo "missing_paths:"
      for path in "${MISSING_PATHS[@]}"; do
        echo "- $path"
      done
    fi
    if [[ "${#EXTERNAL_PATHS[@]}" -gt 0 ]]; then
      echo "external_paths_not_archived:"
      for path in "${EXTERNAL_PATHS[@]}"; do
        echo "- $path"
      done
    fi
  } > "$manifest_path"
}

add_candidate "Radar indexes" "$INDEX_DIR"
add_candidate "Radar logs and readiness snapshots" "$LOG_DIR"
if [[ "$INCLUDE_PDF_CACHE" == "1" ]]; then
  add_candidate "Legal PDF cache" "$PDF_CACHE_DIR"
fi

for index in "${!CANDIDATE_PATHS[@]}"; do
  collect_candidate "${CANDIDATE_PATHS[$index]}"
done

if [[ "$DRY_RUN" == "1" ]]; then
  mkdir -p "$EVIDENCE_DIR"
  write_manifest "$DRY_RUN_MANIFEST_PATH"
  if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    cp "$DRY_RUN_MANIFEST_PATH" "$LATEST_DRY_RUN_MANIFEST_PATH"
  fi
  echo "Personal Literature Radar backup dry run"
  for target in "${BACKUP_TARGETS[@]}"; do
    [[ -n "$target" ]] || continue
    echo "Target: $target"
  done
  for index in "${!CANDIDATE_PATHS[@]}"; do
    echo "Candidate: ${CANDIDATE_LABELS[$index]} -> ${CANDIDATE_PATHS[$index]}"
  done
  echo "PDF cache included: $INCLUDE_PDF_CACHE"
  echo "Credentials included: no"
  echo "Private project memory included: no"
  if [[ "${#MISSING_PATHS[@]}" -gt 0 ]]; then
    echo "Missing inputs:"
    for path in "${MISSING_PATHS[@]}"; do
      echo "- $path"
    done
  fi
  echo "Personal Literature Radar backup dry-run manifest: $DRY_RUN_MANIFEST_PATH"
  if [[ "${PERSONAL_RADAR_WRITE_LATEST:-1}" == "1" ]]; then
    echo "Personal Literature Radar latest backup dry-run manifest: $LATEST_DRY_RUN_MANIFEST_PATH"
  fi
  exit 0
fi

if [[ "${#EXISTING_RELATIVE_PATHS[@]}" -eq 0 ]]; then
  echo "No existing Personal Literature Radar paths found to back up." >&2
  exit 3
fi

for target in "${BACKUP_TARGETS[@]}"; do
  [[ -n "$target" ]] || continue
  if [[ "$target" != /* ]]; then
    echo "PERSONAL_RADAR_BACKUP_TARGETS entries must be absolute paths for live backups: $target" >&2
    exit 2
  fi
  mkdir -p "$target"
  ARCHIVE_PATH="$target/personal-literature-radar-$STAMP.tar.gz"
  MANIFEST_PATH="$target/personal-literature-radar-$STAMP.manifest.txt"
  write_manifest "$MANIFEST_PATH"
  tar -czf "$ARCHIVE_PATH" -C "$ROOT_DIR" "${EXISTING_RELATIVE_PATHS[@]}"
  echo "Personal Literature Radar backup: $ARCHIVE_PATH"
  echo "Personal Literature Radar backup manifest: $MANIFEST_PATH"
done
