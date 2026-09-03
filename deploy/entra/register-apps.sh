#!/usr/bin/env bash
# deploy/entra/register-apps.sh

set -euo pipefail

GRAPH_APP_ID="00000003-0000-0000-c000-000000000000"
REDIRECT_URI=""
MULTI_TENANT=false
SECRET_MONTHS=12
SELECTED_PROVIDERS=()

usage() {
  cat <<'EOF'
Usage: deploy/entra/register-apps.sh --redirect-uri URI [providers] [options]

Providers:
  --outlook-mail
  --outlook-calendar
  --sharepoint

Options:
  --multi-tenant       Accept accounts from any Microsoft Entra organization.
  --secret-months N    Set a new secret lifetime when no active secret exists (default: 12; maximum: 24).
  --help               Show this help.
EOF
}

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

confirm() {
  local response
  printf '\nChange: %s\n' "$1"
  read -r -p 'Type yes to continue: ' response
  [[ "$response" == "yes" ]] || fail "confirmation declined"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}

while (($#)); do
  case "$1" in
    --redirect-uri)
      (($# >= 2)) || fail "--redirect-uri requires a value"
      REDIRECT_URI="$2"
      shift 2
      ;;
    --outlook-mail)
      SELECTED_PROVIDERS+=("outlook_mail")
      shift
      ;;
    --outlook-calendar)
      SELECTED_PROVIDERS+=("outlook_calendar")
      shift
      ;;
    --sharepoint)
      SELECTED_PROVIDERS+=("sharepoint")
      shift
      ;;
    --multi-tenant)
      MULTI_TENANT=true
      shift
      ;;
    --secret-months)
      (($# >= 2)) || fail "--secret-months requires a value"
      SECRET_MONTHS="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

[[ -n "$REDIRECT_URI" ]] || fail "--redirect-uri is required"
((${#SELECTED_PROVIDERS[@]} > 0)) || fail "select at least one provider"
[[ "$SECRET_MONTHS" =~ ^[0-9]+$ ]] || fail "--secret-months must be an integer"
((SECRET_MONTHS >= 1 && SECRET_MONTHS <= 24)) || fail "--secret-months must be between 1 and 24"

require_command az
require_command python3
az account show >/dev/null || fail "sign in with az login before running this script"

if [[ "$MULTI_TENANT" == true ]]; then
  SIGN_IN_AUDIENCE="AzureADMultipleOrgs"
  TENANT_SETTING="organizations"
else
  SIGN_IN_AUDIENCE="AzureADMyOrg"
  TENANT_SETTING="$(az account show --query tenantId --output tsv)"
fi

GRAPH_SCOPES="$(az ad sp show --id "$GRAPH_APP_ID" --query oauth2PermissionScopes --output json)"

provider_display_name() {
  case "$1" in
    outlook_mail) printf 'Outlook Mail' ;;
    outlook_calendar) printf 'Outlook Calendar' ;;
    sharepoint) printf 'SharePoint' ;;
  esac
}

provider_prefix() {
  case "$1" in
    outlook_mail) printf 'OUTLOOK_MAIL' ;;
    outlook_calendar) printf 'OUTLOOK_CALENDAR' ;;
    sharepoint) printf 'SHAREPOINT' ;;
  esac
}

provider_scopes() {
  case "$1" in
    outlook_mail)
      printf '%s\n' openid profile email offline_access User.Read Mail.ReadWrite Mail.Send MailboxSettings.Read People.Read
      ;;
    outlook_calendar)
      printf '%s\n' openid profile email offline_access User.Read Calendars.ReadWrite Calendars.Read.Shared MailboxSettings.Read People.Read
      ;;
    sharepoint)
      printf '%s\n' openid profile email offline_access User.Read Files.Read.All Sites.Read.All
      ;;
  esac
}

required_resource_access() {
  local requested_scopes=()
  while IFS= read -r scope; do
    requested_scopes+=("$scope")
  done < <(provider_scopes "$1")
  python3 -c 'import json, sys; available = {item["value"]: item["id"] for item in json.loads(sys.argv[2])}; missing = [name for name in sys.argv[3:] if name not in available]; missing and sys.exit("Microsoft Graph permission lookup failed for " + ", ".join(missing)); access = [{"id": available[name], "type": "Scope"} for name in sys.argv[3:]]; print(json.dumps([{"resourceAppId": sys.argv[1], "resourceAccess": sorted(access, key=lambda item: item["id"])}], separators=(",", ":")))' \
    "$GRAPH_APP_ID" "$GRAPH_SCOPES" "${requested_scopes[@]}"
}

application_id_for_name() {
  local matches
  matches="$(az ad app list --filter "displayName eq '$1'" --query '[].appId' --output tsv)"
  [[ "$(printf '%s\n' "$matches" | sed '/^$/d' | wc -l | tr -d ' ')" -le 1 ]] || \
    fail "more than one application is named $1"
  printf '%s' "$matches"
}

ensure_service_principal() {
  local app_id="$1"
  if [[ -z "$(az ad sp list --filter "appId eq '$app_id'" --query '[0].id' --output tsv)" ]]; then
    confirm "Create the enterprise application for $app_id."
    az ad sp create --id "$app_id" --only-show-errors >/dev/null
  fi
}

grant_is_current() {
  local app_id="$1"
  local provider="$2"
  local grants
  grants="$(az ad app permission list-grants --id "$app_id" --output json)"
  while IFS= read -r scope; do
    python3 -c 'import json, sys; granted = {scope for item in json.loads(sys.argv[1]) for scope in (item.get("scope") or "").split()}; raise SystemExit(sys.argv[2] not in granted)' \
      "$grants" "$scope" || return 1
  done < <(provider_scopes "$provider")
}

for provider in "${SELECTED_PROVIDERS[@]}"; do
  service_name="$(provider_display_name "$provider")"
  prefix="$(provider_prefix "$provider")"
  display_name="Praxis Agents — $service_name"
  required_access="$(required_resource_access "$provider")"
  app_id="$(application_id_for_name "$display_name")"

  if [[ -z "$app_id" ]]; then
    confirm "Create $display_name with a Web redirect URI and its exact delegated permissions."
    app_id="$(az ad app create \
      --display-name "$display_name" \
      --sign-in-audience "$SIGN_IN_AUDIENCE" \
      --web-redirect-uris "$REDIRECT_URI" \
      --required-resource-accesses "$required_access" \
      --query appId \
      --output tsv \
      --only-show-errors)"
  else
    current="$(az ad app show --id "$app_id" --output json)"
    if ! python3 -c 'import json, sys; current = json.loads(sys.argv[1]); expected_access = json.loads(sys.argv[4]); actual_access = current.get("requiredResourceAccess") or []; normalize = lambda values: sorted((item.get("resourceAppId"), tuple(sorted((entry.get("id"), entry.get("type")) for entry in item.get("resourceAccess", [])))) for item in values); matches = current.get("signInAudience") == sys.argv[2] and sorted((current.get("web") or {}).get("redirectUris") or []) == [sys.argv[3]] and normalize(actual_access) == normalize(expected_access); raise SystemExit(not matches)' \
      "$current" "$SIGN_IN_AUDIENCE" "$REDIRECT_URI" "$required_access"; then
      confirm "Update $display_name to the requested audience, Web redirect URI, and exact delegated permissions."
      az ad app update \
        --id "$app_id" \
        --sign-in-audience "$SIGN_IN_AUDIENCE" \
        --web-redirect-uris "$REDIRECT_URI" \
        --required-resource-accesses "$required_access" \
        --only-show-errors >/dev/null
    else
      printf '\nNo application changes: %s\n' "$display_name"
    fi
  fi

  ensure_service_principal "$app_id"
  if [[ "$MULTI_TENANT" == false ]] && ! grant_is_current "$app_id" "$provider"; then
    confirm "Grant tenant-wide administrator consent for $display_name."
    az ad app permission admin-consent --id "$app_id" --only-show-errors
  elif [[ "$MULTI_TENANT" == false ]]; then
    printf 'No consent changes: %s\n' "$display_name"
  fi

  credentials="$(az ad app credential list --id "$app_id" --output json)"
  active_secrets="$(python3 -c 'import datetime, json, sys; now = datetime.datetime.now(datetime.UTC); parse = lambda value: datetime.datetime.fromisoformat(value.replace("Z", "+00:00")); print(sum(parse(item["endDateTime"]) > now for item in json.loads(sys.argv[1]) if item.get("endDateTime")))' "$credentials")"
  client_secret=""
  if [[ "$active_secrets" == "0" ]]; then
    confirm "Create a client secret for $display_name that expires in $SECRET_MONTHS months."
    end_date="$(python3 -c 'import calendar, datetime, sys; now = datetime.datetime.now(datetime.UTC); months = int(sys.argv[1]); year, month = divmod(now.month - 1 + months, 12); target_year = now.year + year; target_month = month + 1; day = min(now.day, calendar.monthrange(target_year, target_month)[1]); print(now.replace(year=target_year, month=target_month, day=day, microsecond=0).isoformat())' "$SECRET_MONTHS")"
    client_secret="$(az ad app credential reset \
      --id "$app_id" \
      --append \
      --display-name "Praxis Agents" \
      --end-date "$end_date" \
      --query password \
      --output tsv \
      --only-show-errors)"
  fi

  printf '\n# %s\n%s_OAUTH_CLIENT_ID=%s\n' "$service_name" "$prefix" "$app_id"
  if [[ -n "$client_secret" ]]; then
    printf '%s_OAUTH_CLIENT_SECRET=%s\n' "$prefix" "$client_secret"
  else
    printf '# Keep the existing %s_OAUTH_CLIENT_SECRET value.\n' "$prefix"
  fi
  printf '%s_OAUTH_TENANT=\nMICROSOFT_GRAPH_TENANT=%s\n' "$prefix" "$TENANT_SETTING"
done

printf '\nAdd the selected provider keys to INTEGRATIONS_ENABLED_PROVIDERS.\n'
