# monolithic-student-management-system

A poorly designed student management system

## Baseline Azure deployment

The Step 0 baseline was deployed to Azure App Service in the `work` resource
group using Python 3.13 on the B1 tier in South Africa North:

<https://sms-student-management-20261103.azurewebsites.net>

The deployment was performed with:

```powershell
az webapp up --name sms-student-management-20261103 `
  --resource-group work --location southafricanorth `
  --runtime "PYTHON:3.13" --sku B1 --os-type Linux
```

HTTPS-only access is enabled, and `SECRET_KEY` is configured as an App Service
application setting. See [MIGRATION_LOG.md](MIGRATION_LOG.md) for the baseline
state, verification, risks, and rollback procedure.

## Bicep infrastructure

The Azure resources are described in [infra/main.bicep](infra/main.bicep), with
the current deployment values in [infra/main.bicepparam](infra/main.bicepparam).
The template defines the Linux B1 App Service plan, container web app, HTTPS
and health-check settings, GHCR app settings, and the GitHub OIDC identity.
`SECRET_KEY` is a secure Bicep parameter read from the process environment; it
must never be added to a parameter file or committed.

### GitHub Actions secret

Before enabling the Azure what-if CI check, add a repository Actions secret
named `SECRET_KEY` in **Settings → Secrets and variables → Actions**. Use the
same value as the deployed app, obtained from your approved secret manager.
Do not paste the value into chat, a command line, or the repository.

### Deploying to a new resource group

Use an account permitted to create subscription role definitions and resource
group role assignments. The custom what-if role is subscription-scoped; the
app and its deployment identity are resource-group-scoped.

```powershell
az account set --subscription 74577974-a069-4c7e-90ea-9f06a0aaa0f5
az group create --name <new-resource-group> --location southafricanorth

az deployment sub what-if --location southafricanorth `
  --template-file infra/what-if-role.bicep
az deployment sub create --location southafricanorth `
  --template-file infra/what-if-role.bicep

# Set SECRET_KEY in this process from an approved secret manager, without
# echoing it or putting it in shell history.
if ([string]::IsNullOrWhiteSpace($env:SECRET_KEY)) {
  throw 'Set SECRET_KEY from your approved secret manager before deploying.'
}
$image = 'ghcr.io/xipasha/monolithic-student-management-system:<full-commit-sha>'
$assignmentId = [guid]::NewGuid().ToString()

az deployment group what-if --resource-group <new-resource-group> `
  --template-file infra/main.bicep --parameters infra/main.bicepparam `
  --parameters appName='<globally-unique-app-name>' `
    websiteContributorAssignmentName=$assignmentId containerImage=$image
az deployment group create --resource-group <new-resource-group> `
  --template-file infra/main.bicep --parameters infra/main.bicepparam `
  --parameters appName='<globally-unique-app-name>' `
    websiteContributorAssignmentName=$assignmentId containerImage=$image

Remove-Item Env:\SECRET_KEY
```

Review the what-if output before creating resources; a new resource group is
expected to show the resources being created. The template grants the GitHub
identity Website Contributor on the web app, and read-only access plus the
custom what-if action on the resource group. In a shared resource group,
Reader access exposes resource metadata for all resources in that group.
For a new deployment, update the workflow's resource group, web app, plan, and
identity client ID to match the parameter values and the identity created by
the template.
