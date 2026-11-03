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

GitHub Actions run [41616403244](https://github.com/xipasha/monolithic-student-management-system/actions/runs/41616403244)
passed the secret scan, unit tests and coverage gate, container build, and
container health check. The GHCR publish job succeeded with the image tag
`ghcr.io/xipasha/monolithic-student-management-system:26d8bd6e7081bcdb8a40201c8887926d2edef9cd`.
Publishing is gated on successful tests and the container smoke test, and only
runs for pushes to `main`.

### Rollback

Deploy the previous image using its commit-SHA tag. Do not rely on a mutable
`latest` tag.

## Step 3: Run the GHCR image on Azure App Service

**Date:** 2026-11-03

**Commits:** `c8165a6`, `c8a831c`, `133a71e`, `71c320b`, `2590a48`

**Author:** Project team

### What changed

- Added `scripts/deploy-container.sh` to deploy a validated full-SHA GHCR image
  to the existing App Service. It requires the existing `SECRET_KEY` to be
  present, preserves it, sets `WEBSITES_PORT=8000`, and configures `/health`.
- Added a main-branch CI deployment job gated on successful image publishing.
  GitHub Actions authenticates to Azure using OIDC through a dedicated
  user-assigned managed identity scoped to this App Service.
- The deploy job records the configured runtime before changing it, polls the
  public health endpoint, and restores and checks the prior runtime if health
  verification fails. It fails the workflow after attempting recovery.
- Added a manually triggered rollback workflow that deploys a selected
  commit-SHA image and restores the previous runtime if the selected image
  does not become healthy.
- Captured the deployed login page in
  [docs/evidence/app-service-login.png](docs/evidence/app-service-login.png).
- No application behavior or `app.py` business logic changed.

### Risk

- App Service may have brief downtime while the container restarts.
- SQLite is stored in the container filesystem and is not persistent; replacing
  the container can reset application data.

### Verification

GitHub Actions run
[41623886088](https://github.com/xipasha/monolithic-student-management-system/actions/runs/41623886088)
passed tests, coverage, secret scanning, container build and smoke test, image
publication, OIDC authentication, and App Service deployment.

The deployed image is
`ghcr.io/xipasha/monolithic-student-management-system:2590a4853d9d612be2f5c2cc84ff7c2313f87e66`.
The App Service reports `/health` as its health-check path and
`WEBSITES_PORT=8000`; the live
[health endpoint](https://sms-student-management-20261103.azurewebsites.net/health)
returned HTTP 200 with `{"application":"Student Management System","status":"ok"}`.

### Rollback

Run the **Rollback** GitHub Actions workflow on `main` with the full commit SHA
of a known-good GHCR image. If an automated deployment fails its health check,
the deployment job restores the previously configured App Service runtime,
checks its health, and then fails so the pipeline remains red.
