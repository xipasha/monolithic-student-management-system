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
## PostgreSQL migration and rollback

The app uses SQLite locally when `DATABASE_URL` is unset. In Azure, set it to
an encoded PostgreSQL connection URL ending in `sslmode=require`; keep both the
server administrator password and the full URL in GitHub Actions secrets or an
approved secret manager. Never place either value in a parameter file or Git.
The Bicep parameters read `POSTGRES_ADMIN_PASSWORD` and `DATABASE_URL` from the
process environment and mark both parameters secure.

The PostgreSQL server is created in South Africa North with a 32 GB Burstable
`Standard_B1ms` SKU, seven-day backups, TLS required, and public networking. The
firewall rule `AllowAzureServices` is needed for App Service connectivity; it
allows Azure-hosted sources broadly. Restrict this to App Service outbound IPs
or private networking if the deployment later moves to a supported networked
configuration.

For a one-time data copy, first take a consistent copy of the source SQLite
file and stop application writes. Set `DATABASE_URL` in the environment from a
secure source, then run:

```powershell
python scripts/migrate-sqlite-to-postgres.py path\to\sms.db
```

The script creates the current schema if needed, refuses to merge into a
PostgreSQL database that already contains users, verifies table columns, copies
all rows and IDs in foreign-key order, and resets the serial sequences. Keep
the SQLite file unchanged as the rollback copy. Do not point the app at
PostgreSQL until the migration completes and the copied row counts have been
reviewed.

To roll back the application, point `DATABASE_URL` at a restored SQLite file,
for example `sqlite:////app/instance/sms.db`, then restart/redeploy the prior
container. Unsetting `DATABASE_URL` uses the default `instance/sms.db` path.
This only restores data present in the SQLite copy. Writes made after cutover
exist only in PostgreSQL and must be exported or reconciled before rollback.
The current container configuration does not persist its SQLite directory, so
retain the migration source file outside the container before switching.
