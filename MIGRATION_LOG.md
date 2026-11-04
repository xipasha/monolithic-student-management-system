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

### Step 3b: Manual rollback rehearsal

**Date:** 2026-11-03

**Author:** Project team

#### What was done

Ran the manual **Rollback** workflow to deploy the Step 2 image
`67425979991db0b4784934cdaf6990394c9514c3`, then ran it again with the current
image `d6519729cfbb9768dbe6b539b4fa96051d23e0d7` to roll forward.

#### Risk

Low. Each image switch restarts the App Service and can cause brief downtime.
The SQLite database is in the container filesystem and is not persistent.

#### Verification

- [Short-SHA validation run 41626037620](https://github.com/xipasha/monolithic-student-management-system/actions/runs/41626037620)
  failed at the image-pull validation step because the abbreviated SHA was not
  a published tag. Azure login and deployment were skipped, so Azure was
  untouched. See the [failure screenshot](docs/evidence/error%20rollback.png).
- [Rollback run 41626466731](https://github.com/xipasha/monolithic-student-management-system/actions/runs/41626466731)
  deployed the full Step 2 SHA; image validation, Azure deployment, and the
  health-check step all passed.
- [Roll-forward run 41628331486](https://github.com/xipasha/monolithic-student-management-system/actions/runs/41628331486)
  deployed the full current SHA; image validation, Azure deployment, and the
  health-check step all passed. See the [success screenshot](docs/evidence/success%20rollback.png).
- The live App Service was subsequently confirmed to run
  `d6519729cfbb9768dbe6b539b4fa96051d23e0d7`; `/health` returned HTTP 200.
- Admin and student login checks are not confirmed by the workflow evidence
  and remain pending manual verification.

#### Rollback

Use the **Rollback** workflow with a full, previously published image SHA.
The abbreviated-SHA rehearsal demonstrates that invalid image tags fail
validation before making changes to Azure.

#### Known gap

This rehearsal verified manual rollback and roll-forward. Automatic rollback
after a health-check failure was subsequently exercised in Step 3c.

### Step 3c: Automatic rollback failure-path rehearsal

**Date:** 2026-11-03

**Workflow commit:** `0aeae07`

**Author:** Project team

#### What was done

Dispatched the **Test and Build** workflow with `simulate_failure=true`. The
workflow deployed the current GHCR image with `WEBSITES_PORT=9999`, verified
that setting, and explicitly restarted the App Service so the invalid port
was applied before probing health.

#### Risk

A few minutes of downtime occurred while the failed configuration was detected
and the previous image/runtime was restored. The rollback rehearsal did not
change `app.py` or application behavior.

#### Verification

- [Automatic rollback rehearsal run 41640158228](https://github.com/xipasha/monolithic-student-management-system/actions/runs/41640158228)
  passed tests, secret scanning, coverage, container build/smoke test, and
  image publication. The deploy job went red intentionally after recovery.
- The bad-port health probe observed HTTP status `000`, confirming the
  application was unreachable after the forced restart.
- The restore step confirmed the exact previously recorded image tag:
  `ghcr.io/xipasha/monolithic-student-management-system:0aeae07bc9073e3cb8984050f711d7f31603fc82`.
  The restored runtime passed its `/health` check.
- After the run, the live App Service reported that same image tag,
  `WEBSITES_PORT=8000`, and `/health` returned HTTP 200.

#### Rollback

No manual recovery was needed. The workflow restored the previously recorded
GHCR image tag and failed the run after verifying recovery, as designed.

## Step 4: Define Azure resources with Bicep

**Date:** 2026-11-03

**Commits:** `a02a7db`, `284640c`, `db9a153`, `9d28988`

**Author:** Project team

### What changed

- Added Bicep definitions for the Linux B1 App Service plan, container web app,
  HTTPS-only setting, `/health` endpoint, current app settings, user-assigned
  GitHub OIDC identity, and its federated credentials.
- Added a subscription-scoped custom role for ARM what-if and a resource-group
  Reader assignment for CI. Website Contributor remains scoped to the app.
- Added a CI Bicep build and a live what-if check. The check compares current
  app-setting values in memory without printing them; `SECRET_KEY` comes from
  the repository Actions secret and is a secure Bicep parameter.
- The live-resource CI what-if excludes identity and role-assignment writes,
  which are outside the deployment identity's permissions. Those resources
  remain defined in Bicep for authorized provisioning; the CI gate checks the
  web app and its settings.
- Added README instructions for setting the secret and deploying into a new
  resource group.
- No application code or behavior changed.

### Risk

A mistaken template could change the live app, image, settings, or access.
Review the what-if result before any Bicep deployment. The CI identity's
resource-group Reader role exposes metadata for all resources in the shared
`work` group; it has no resource-group Contributor permission.

### Verification

- `az bicep build` succeeded for both Bicep templates, and the parameter file
  compiled with a process-only validation value.
- The live Azure what-if check passed with no unexpected infrastructure
  changes. Existing settings matched the template; setting values, including
  `SECRET_KEY`, were not printed.
- GitHub Actions run
  [41654116689](https://github.com/xipasha/monolithic-student-management-system/actions/runs/41654116689)
  passed template builds, secret scanning, tests, coverage, container checks,
  live Azure what-if, deployment, and the health check.

### Rollback

No Bicep deployment was made to the App Service. The CI-only access grants can
be removed by deleting their resource-group role assignments and the custom
role definition if this what-if check is no longer needed.

## Step 5: Migrate application to PostgreSQL Flexible Server

**Date:** 2026-11-04

**Status:** Deployed and verified. The project owner confirmed the original
SQLite database has no records, so there was no production data to copy.

**Commits:** `4ef8f2d`, `e45928f`, `0ee7912`, `d663c25`, `9bd7835`,
`a7b4dea`, `37c6a29`, `7bee412`, `5cfad05`, `a565642`, `ac7fdbf`,
`8395cab`

### What changed

- Added an Azure Database for PostgreSQL Flexible Server (PostgreSQL 16,
  Burstable `Standard_B1ms`, 32 GB storage, seven-day backup) and `sms` database
  to Bicep. The administrator password and application connection URL are
  secure parameters. TLS is explicitly required. A firewall rule permits
  Azure-hosted clients so App Service can connect.
- Added a PostgreSQL adapter selected by `DATABASE_URL`; SQLite remains the
  fallback. Existing route SQL and characterisation assertions were retained.
- Added a PostgreSQL service-container test matrix alongside SQLite.
- Added `scripts/migrate-sqlite-to-postgres.py`, which refuses a nonempty target,
  checks schema columns, copies IDs and rows in foreign-key order, and resets
  serial sequences. Added migration and rollback instructions to the README.
- Generated the PostgreSQL administrator password and initial application
  administrator password locally, then stored both and the TLS connection URL
  as GitHub Actions secrets. No credential values were printed or committed.
- Provisioned the database before deploying the new app image. The existing
  SQLite data copy was not run because the owner confirmed that the original
  database has no records. The deployment workflow created a temporary student
  for login verification and deactivated it afterward.

### Risk

The main risks are losing the current container-local SQLite data when the
container is replaced and a schema mismatch during the one-off copy. The
migration script stops on schema mismatch or a nonempty PostgreSQL target.
The initial firewall rule allows Azure-hosted sources broadly; it should be
restricted to App Service outbound addresses or private networking when
available. Writes after cutover exist only in PostgreSQL and are not copied
back during rollback.

### Verification

- Azure subscription `Azure for Students` was enabled for
  `Microsoft.DBforPostgreSQL`. South Africa North lists `Standard_B1ms`; at
  provisioning time the quota endpoint reported 0 of 8 Burstable B-family
  servers and 0 of 16 cores in use.
- `az bicep build` succeeded for both Bicep templates, and
  `az bicep build-params` succeeded with process-only validation values.
- Reviewed what-if deployment `step5-postgres-20261104094625` proposed only the
  PostgreSQL server, database, TLS and Azure firewall resources, plus the
  expected App Service setting changes. The deployment succeeded.
- The server `sms-student-management-pg-20261103` is PostgreSQL 16 and reports
  `Ready`; the `sms` database exists and `require_secure_transport` is `ON`.
- GitHub Actions run
  [41797417187](https://github.com/xipasha/monolithic-student-management-system/actions/runs/41797417187)
  passed secret scanning, all 14 existing characterisation tests against both
  SQLite and PostgreSQL, coverage, container build and smoke test, GHCR image
  publication, live Bicep what-if, deployment, health check, and live login
  verification.
- The subsequent migration-log push also passed the complete pipeline and live
  login checks in run
  [41798303187](https://github.com/xipasha/monolithic-student-management-system/actions/runs/41798303187).
- Run [41800271781](https://github.com/xipasha/monolithic-student-management-system/actions/runs/41800271781)
  exercised automatic rollback after the verification cleanup hit a foreign-key
  ordering error. The new image was restored to the prior runtime and health
  returned; the login checks themselves had passed.
- After correcting the cleanup order, run
  [41800984793](https://github.com/xipasha/monolithic-student-management-system/actions/runs/41800984793)
  passed all test, deployment, health, and login gates. Its cleanup removed the
  verification student rows and confirmed the database has no student rows.
- The live `/health` endpoint returned HTTP 200 with
  `{"application":"Student Management System","status":"ok"}`. The workflow
  verified the admin login and dashboard, created a temporary student, verified
  first login, password change, and the student dashboard. The final verified
  workflow removed the temporary verification rows afterward.
- The first cutover run deployed image
  `ghcr.io/xipasha/monolithic-student-management-system:7bee412d98ad88954e670044ccfb8583750faabc`.
- `git diff --check` passed. The original SQLite migration script was not run
  because the owner confirmed that the source database was empty.

### Rollback

To return the app to SQLite, point `DATABASE_URL` at a retained SQLite file
(or unset it to use the default `instance/sms.db` path), then redeploy/restart a
SQLite-capable image. The original database was empty. Any records created in
PostgreSQL after this deployment are not copied back and must be exported or
reconciled before rollback. The container's SQLite directory is not persisted.
