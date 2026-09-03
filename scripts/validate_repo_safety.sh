#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

declare -a FILES=()
declare -a SCANNABLE_FILES=()
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  while IFS= read -r -d '' file; do
    FILES+=("$file")
  done < <(git ls-files --cached --others --exclude-standard -z)
else
  while IFS= read -r -d '' file; do
    FILES+=("${file#./}")
  done < <(find . -type f \
    -not -path './.git/*' \
    -not -path './.venv/*' \
    -not -path '*/__pycache__/*' -print0)
fi

for file in "${FILES[@]}"; do
  case "$file" in
    *.png|*.jpg|*.jpeg|*.gif|*.bmp|*.tif|*.tiff|*.ico|*.webp|*.woff|*.woff2|*.ttf)
      ;;
    *)
      SCANNABLE_FILES+=("$file")
      ;;
  esac
done

failed=0
forbidden_path_count=0

for file in "${FILES[@]}"; do
  case "$file" in
    .env.example|*/.env.example|reports/public/*.pdf|evaluation/templates/*.example.jsonl)
      ;;
    data/*|*/data/*|private/*|*/private/*|resources/*|artifacts/*|*/artifacts/*|evaluation/private/*|*/evaluation/private/*|vector_store/*|*/vector_store/*|vectorstore/*|*/vectorstore/*|chroma/*|*/chroma/*|faiss/*|*/faiss/*|.env|.env.*|*/.env|*/.env.*|*.pem|*.key|*.hwp|*.hwpx|*.pdf|*.jsonl|*/data_list.csv|*/refined_data_list.csv|*extracted*.txt|*corpus*.txt|*/environment.txt)
      failed=1
      forbidden_path_count=$((forbidden_path_count + 1))
      ;;
  esac
done

if ((forbidden_path_count)); then
  printf 'FORBIDDEN_TRACKED_PATHS_FOUND count=%d\n' "$forbidden_path_count"
fi

if ((${#SCANNABLE_FILES[@]})); then
  if rg --quiet --no-messages --pcre2 \
    '((?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{25,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----)' \
    "${SCANNABLE_FILES[@]}"; then
    printf 'SECRET_PATTERN_FOUND\n'
    failed=1
  fi

  if rg --quiet --no-messages --pcre2 \
    '(?i)(?<!git@)([A-Z0-9._%+-]+@(?!example\.(com|org|net)|github\.com|localhost)[A-Z0-9.-]+\.[A-Z]{2,}|(?<![0-9.])(?:01[016789]-?[0-9]{3,4}-?[0-9]{4}|0(?:2|[3-6][1-5])-?[0-9]{3,4}-?[0-9]{4})(?![0-9.]))' \
    "${SCANNABLE_FILES[@]}"; then
    printf 'PII_PATTERN_FOUND\n'
    failed=1
  fi
fi

if ((failed)); then
  printf 'Repository safety check: FAIL\n'
  exit 1
fi

printf 'Repository safety check: PASS (%d files scanned)\n' "${#FILES[@]}"
