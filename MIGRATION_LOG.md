# Migration Log

## Step 0: Baseline deployment (Azure App Service)

**Date:** 2026-11-03  
**Commit/tag:** [`step-0-baseline`](https://github.com/xipasha/monolithic-student-management-system/releases/tag/step-0-baseline)  
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

## Step 1: Baseline hardening and characterisation coverage

**Date:** 2026-11-03  
**Commit:** `64cdf97`  
**Author:** Project team

### What changed

- Removed the insecure fallback Flask `SECRET_KEY`; the application now fails
  during startup when `SECRET_KEY` is not configured.
- Added a full-history Gitleaks scan to the CI workflow.
- Added characterisation tests for authentication, student lifecycle actions,
  password reset and change flows, course management, enrolments, and student
  profile/course viewing.
- Added pytest coverage reporting with a 60% minimum CI threshold.
- Added README instructions for the Azure baseline deployment.

### Risk

The application now intentionally refuses to start without `SECRET_KEY`.
Deployments must provide that setting through the platform environment or
secret configuration. The tests assert existing behavior and do not change
the application flow.

### Verification

Local validation completed:

```text
14 passed
81.01% coverage
```

Gitleaks scanned all 12 commits and found no secrets. Importing the
application without `SECRET_KEY` fails with the expected runtime error.

### Rollback

Revert commit `64cdf97` or redeploy the `step-0-baseline` tag. Any deployment
rollback must continue to provide the configured App Service `SECRET_KEY`.

## Step 2: Containerise the Flask monolith

**Date:** 2026-11-03

**Commits:** `dc3e959`, `3833872`, `6fe0ebe`, `1cace51`

**Author:** Project team

### What changed

- Pinned the container base to `python:3.13.7-slim-bookworm`.
- Runs Gunicorn as a non-root user and binds to the `PORT` environment variable
  (defaulting to port 8000).
- Keeps dependencies in a separate Docker build layer and excludes tests,
  environment files, Git metadata, and local database state from the image
  context.
- Added CI that builds the image, starts it with a test `SECRET_KEY`, and
  checks `/health`.
- Added a main-branch-only GHCR publish job, gated on tests and the container
  smoke test. Images are tagged with the full commit SHA; no `latest` tag is
  published.
- No application behavior or business logic was changed.

### Risk

The SQLite database remains local to the container's writable filesystem.
Replacing the container can discard its data, and this image is not suitable
for persistent production data until SQLite is replaced by a managed database.
The application also requires `SECRET_KEY` to be supplied at runtime.

### Verification

The CI workflow runs the test and coverage gate before building the image,
starts the container with a test secret, and requires `/health` to return
success before the image can be published to GHCR. The publish job only runs
for pushes to `main`.

### Rollback

Deploy the previous image using its commit-SHA tag. Do not rely on a mutable
`latest` tag.
