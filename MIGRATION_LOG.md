# Migration Log

## Step 0: Baseline deployment (Azure App Service)

**Date:** 2026-11-03  
**Commit/tag:** Not created yet  
**Author:** Project team

### What changed

The unmodified Flask monolith was deployed directly from source to Azure App
Service using Python 3.13 on the B1 tier in South Africa North. HTTPS-only
access was enabled, and `SECRET_KEY` was configured as an App Service setting.

The deployed application is available at:

<https://sms-student-management-20261103.azurewebsites.net>

### State of the system

- Single deployable application and process
- SQLite database stored on local disk
- Flask session cookies
- No infrastructure as code
- No managed database
- No distributed tracing
- No autoscaling configuration
- No asynchronous messaging

Azure Container Apps was also attempted, but Azure for Students blocked the
required Azure Container Registry Tasks operation
(`TasksOperationsNotAllowed`). The temporary resources from that attempt were
removed.

### Risk

This step made no application-code changes, so functional risk was low. The
system still has known architectural limitations:

- Data can be lost during redeployment or scale-out because SQLite is local.
- A single instance limits availability and throughput.
- The application remains a monolith.
- The original source fallback for `SECRET_KEY` is not suitable for production
  if the App Service setting is absent.

### Verification

The health endpoint was verified successfully:

```text
GET /health
HTTP 200
```

Response:

```json
{"application":"Student Management System","status":"ok"}
```

Manual login and course-management flow verification is still pending.

### Rollback

Rollback can be performed by redeploying the previous application source or
removing the Azure App Service deployment.
