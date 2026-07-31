#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 ENV_FILE VARIABLE_NAME" >&2
  exit 64
fi

env_file=$1
variable_name=$2
case "$variable_name" in
  [A-Za-z_]* ) ;;
  * ) echo "Invalid environment variable name." >&2; exit 64 ;;
esac
case "$variable_name" in
  *[!A-Za-z0-9_]* ) echo "Invalid environment variable name." >&2; exit 64 ;;
esac

IFS= read -r replacement

umask 077
temporary_file="$(mktemp "${env_file}.tmp.XXXXXX")"
cleanup() {
  [ -z "$temporary_file" ] || rm -f -- "$temporary_file"
}
trap cleanup 0
trap 'exit 130' HUP INT TERM
chmod 600 "$temporary_file"

replaced=false
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    "$variable_name="*)
      if [ "$replaced" = false ]; then
        printf '%s=%s\n' "$variable_name" "$replacement"
        replaced=true
      fi
      ;;
    *) printf '%s\n' "$line" ;;
  esac
done < "$env_file" > "$temporary_file"

if [ "$replaced" = false ]; then
  printf '%s=%s\n' "$variable_name" "$replacement" >> "$temporary_file"
fi

mv "$temporary_file" "$env_file"
temporary_file=
