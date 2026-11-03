#!/usr/bin/env bash
set -euo pipefail

: "${SECRET_KEY:?GitHub Actions secret SECRET_KEY must be configured}"

resource_group="${AZURE_RESOURCE_GROUP:-work}"
webapp_name="${AZURE_WEBAPP_NAME:-sms-student-management-20261103}"
plan_name="${AZURE_APPSERVICE_PLAN_NAME:-sikalumbit30_asp_8006}"
identity_name="${AZURE_IDENTITY_NAME:-sms-github-deploy}"
image_prefix="DOCKER|ghcr.io/xipasha/monolithic-student-management-system:"

plan_sku="$(az appservice plan show \
  --name "$plan_name" \
  --resource-group "$resource_group" \
  --query sku.name --output tsv)"
plan_kind="$(az appservice plan show \
  --name "$plan_name" \
  --resource-group "$resource_group" \
  --query kind --output tsv)"
plan_reserved="$(az appservice plan show \
  --name "$plan_name" \
  --resource-group "$resource_group" \
  --query properties.reserved --output tsv)"
if [[ "$plan_sku" != "B1" || "$plan_kind" != "linux" || "$plan_reserved" != "true" ]]; then
  echo "The live App Service plan does not match the expected Linux B1 configuration." >&2
  exit 1
fi

current_runtime="$(az webapp config show \
  --name "$webapp_name" \
  --resource-group "$resource_group" \
  --query linuxFxVersion --output tsv)"
if [[ "$current_runtime" != "$image_prefix"* ]]; then
  echo "The live web app is not running a supported GHCR image: $current_runtime" >&2
  exit 1
fi

webapp_state="$(az webapp show \
  --name "$webapp_name" \
  --resource-group "$resource_group" \
  --query '{httpsOnly:httpsOnly,healthCheckPath:siteConfig.healthCheckPath,linuxFxVersion:siteConfig.linuxFxVersion,localMySqlEnabled:siteConfig.localMySqlEnabled,netFrameworkVersion:siteConfig.netFrameworkVersion}' \
  --output json)"
live_settings="$(az webapp config appsettings list \
  --name "$webapp_name" \
  --resource-group "$resource_group" \
  --output json)"
APP_SETTINGS_JSON="$live_settings" WEBAPP_STATE_JSON="$webapp_state" \
  CURRENT_RUNTIME="$current_runtime" WEBAPP_NAME="$webapp_name" python - <<'PY'
import json
import os
import sys

expected = {
    "SCM_DO_BUILD_DURING_DEPLOYMENT": "true",
    "WEBSITE_HTTPLOGGING_RETENTION_DAYS": "3",
    "DOCKER_REGISTRY_SERVER_URL": "https://ghcr.io",
    "WEBSITES_ENABLE_APP_SERVICE_STORAGE": "false",
    "WEBSITES_PORT": "8000",
    "PORT": "8000",
    "SECRET_KEY": os.environ["SECRET_KEY"],
}
actual = {item["name"]: item["value"] for item in json.loads(os.environ["APP_SETTINGS_JSON"])}
missing = expected.keys() - actual.keys()
extra = actual.keys() - expected.keys()
mismatched = {name for name in expected.keys() & actual.keys() if actual[name] != expected[name]}
if missing or extra or mismatched:
    print(
        "App Service setting names or values differ (values are hidden): "
        f"missing={sorted(missing)}, extra={sorted(extra)}, mismatched={sorted(mismatched)}",
        file=sys.stderr,
    )
    sys.exit(1)

webapp = json.loads(os.environ["WEBAPP_STATE_JSON"])
if not webapp["httpsOnly"] or webapp["healthCheckPath"] != "/health":
    print("The live web app HTTPS or health-check configuration differs from the template.", file=sys.stderr)
    sys.exit(1)
if webapp["localMySqlEnabled"] is not False or webapp["netFrameworkVersion"] != "v4.0":
    print("The live web app platform defaults differ from the values Azure adds during what-if.", file=sys.stderr)
    sys.exit(1)
if webapp["linuxFxVersion"] != os.environ["CURRENT_RUNTIME"]:
    print("The live container image differs between Azure web app queries.", file=sys.stderr)
    sys.exit(1)
PY

container_image="${current_runtime#DOCKER|}"
identity_principal_id="$(az identity show \
  --name "$identity_name" \
  --resource-group "$resource_group" \
  --query principalId --output tsv)"

what_if_file="$(mktemp)"
trap 'rm -f "$what_if_file"' EXIT
az deployment group what-if \
  --resource-group "$resource_group" \
  --template-file infra/main.bicep \
  --parameters infra/main.bicepparam \
  --parameters createAppServicePlan=false \
    deploymentIdentityPrincipalId="$identity_principal_id" \
    containerImage="$container_image" \
  --result-format FullResourcePayloads \
  --no-pretty-print \
  --output json > "$what_if_file"

WEBAPP_NAME="$webapp_name" python - "$what_if_file" <<'PY'
import json
import os
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text()
start = text.find("{")
if start < 0:
    raise SystemExit("Azure what-if did not return JSON.")
changes = json.loads(text[start:])["changes"]
unexpected = []
webapp_name = os.environ["WEBAPP_NAME"].lower()
for change in changes:
    kind = change["changeType"]
    resource_id = change["resourceId"]
    if kind in {"NoChange", "Ignore"}:
        continue
    normalized_id = resource_id.lower()
    if kind == "Modify" and normalized_id.endswith(f"/sites/{webapp_name}/config/appsettings"):
        continue
    if kind == "Modify" and normalized_id.endswith(f"/sites/{webapp_name}"):
        continue
    unexpected.append(f"{kind} {resource_id}")

if unexpected:
    print("Bicep what-if found unexpected infrastructure changes:", file=sys.stderr)
    print("\n".join(unexpected), file=sys.stderr)
    sys.exit(1)
print("Bicep what-if passed; no unexpected infrastructure changes were proposed.")
PY
