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
