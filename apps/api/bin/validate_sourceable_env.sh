#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 ENV_FILE" >&2
  exit 64
fi

# These files are sourced as shell, so reject content that would fail cryptically.
awk '
  index($0, "\r") {
    name = $0
    sub(/=.*/, "", name)
    if (name ~ /^[A-Za-z_][A-Za-z0-9_]*$/) {
      printf "%s:%d: %s: save the file with Unix (LF) line endings\n", FILENAME, FNR, name
    } else {
      printf "%s:%d: save the file with Unix (LF) line endings\n", FILENAME, FNR
    }
    invalid = 1
    next
  }
  /^[A-Za-z_][A-Za-z0-9_]*=[^\"\047#[:space:]]*[[:space:]]+[^#[:space:]]/ {
    name = $0
    sub(/=.*/, "", name)
    printf "%s:%d: %s: quote values that contain spaces\n", FILENAME, FNR, name
    invalid = 1
  }
  END { exit invalid ? 1 : 0 }
' "$1" >&2 || exit 65
