#!/usr/bin/env bash
set -euo pipefail

resource_group="${AZURE_RESOURCE_GROUP:-work}"
webapp_name="${AZURE_WEBAPP_NAME:-sms-student-management-20261103}"
notifier_name="${AZURE_NOTIFIER_WEBAPP_NAME:-${webapp_name}-notifier}"
namespace_name="${AZURE_SERVICEBUS_NAMESPACE_NAME:-sms-student-events-20261104}"
identity_name="${AZURE_IDENTITY_NAME:-sms-github-deploy}"
read_setting() {
  az webapp config appsettings list --name "$webapp_name" --resource-group "$resource_group" \
    --query "[?name=='$1'].value | [0]" --output tsv
}
SECRET_KEY="${SECRET_KEY:-$(read_setting SECRET_KEY)}"
DATABASE_URL="${DATABASE_URL:-$(read_setting DATABASE_URL)}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(read_setting ADMIN_PASSWORD)}"
POSTGRES_ADMIN_PASSWORD="${POSTGRES_ADMIN_PASSWORD:-$(python -c 'import secrets; print(secrets.token_urlsafe(32))')}"
export SECRET_KEY DATABASE_URL ADMIN_PASSWORD POSTGRES_ADMIN_PASSWORD
for required_name in SECRET_KEY DATABASE_URL ADMIN_PASSWORD POSTGRES_ADMIN_PASSWORD; do
  if [[ -z "${!required_name}" || "${!required_name}" == "None" ]]; then
    echo "Could not retrieve the existing $required_name setting; set it in the environment." >&2
    exit 1
  fi
done
identity_principal_id="$(az identity show --name "$identity_name" \
  --resource-group "$resource_group" --query principalId --output tsv)"
current_runtime="$(az webapp config show --name "$webapp_name" --resource-group "$resource_group" \
  --query linuxFxVersion --output tsv)"
container_image="${current_runtime#DOCKER|}"
if [[ "$container_image" == "$current_runtime" ]]; then
  echo "The existing monolith is not running a Docker image; refusing to change its runtime." >&2
  exit 1
fi

deployment_parameters=(
  --parameters infra/main.bicepparam
    createAppServicePlan=false manageDeploymentIdentity=false managePostgres=false
    deploymentIdentityPrincipalId="$identity_principal_id"
    containerImage="$container_image"
    notifierContainerImage="ghcr.io/xipasha/monolithic-student-management-system-notifier:latest"
    notifierAppName="$notifier_name" serviceBusNamespaceName="$namespace_name"
    notificationsEnabled=false
    secretKey="$SECRET_KEY" postgresAdminPassword="$POSTGRES_ADMIN_PASSWORD"
    databaseUrl="$DATABASE_URL" adminPassword="$ADMIN_PASSWORD"
)

az deployment group validate \
  --resource-group "$resource_group" \
  --template-file infra/main.bicep \
  "${deployment_parameters[@]}" \
  --output none

az deployment group create \
  --name "step6-infrastructure-$(date -u +%Y%m%d%H%M%S)" \
  --resource-group "$resource_group" \
  --template-file infra/main.bicep \
  "${deployment_parameters[@]}" \
  --output none

worker_id="$(az webapp show --name "$notifier_name" --resource-group "$resource_group" --query id --output tsv)"
worker_role_count="$(az role assignment list --scope "$worker_id" --assignee "$identity_principal_id" \
  --query "[?roleDefinitionName=='Website Contributor'] | length(@)" --output tsv)"
if [[ "$worker_role_count" == "0" ]]; then
  az role assignment create \
    --assignee-object-id "$identity_principal_id" \
    --assignee-principal-type ServicePrincipal \
    --role "Website Contributor" \
    --scope "$worker_id" \
    --output none
fi

echo "Step 6 Service Bus, queue, worker app, identities and settings deployed with notifications disabled."
