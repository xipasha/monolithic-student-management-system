# Courses Service: Step 7 Design Proposal

**Status:** Approved. Step 7 implementation is in progress.

## Current behavior inventory

### Routes and database access

| Route | Current course/enrolment access | Behavior the adapter must preserve |
| --- | --- | --- |
| `GET /admin` (`app.py:362-388`) | Counts courses and enrolments; loads courses ordered by `course_code`; joins enrolments to local students and courses ordered by descending enrolment ID. It also loads active students for the enrolment form. | Keep the dashboard counts, course ordering, displayed student names, action IDs, empty states, and current template input data. Student names and active status remain in the monolith. |
| `POST /admin/courses/create` (`app.py:507-530`) | Inserts course code, name, and description. Code is stripped and uppercased; name and description are stripped. Empty required fields flash an error. A uniqueness error flashes “That course code already exists.” | Keep validation, flash text/category, and redirect to `/admin`. |
| `POST /admin/courses/<int:course_id>/delete` (`app.py:533-540`) | Deletes by integer course ID. A nonexistent ID is still treated as success. The current course foreign key cascades to enrolments. | Keep the integer ID in forms and the success flash. Course deletion must remove its enrolments as today. |
| `POST /admin/enrolments/create` (`app.py:543-575`) | Reads integer `student_id` and `course_id`. It checks that the local student exists and is active, checks that the local course exists, then inserts the enrolment. The unique constraint rejects duplicates. | Resolve the selected local student ID to `student_number`; the monolith still checks active status. Preserve the validation/duplicate messages and redirect. |
| `POST /admin/enrolments/<int:enrolment_id>/delete` (`app.py:578-585`) | Deletes by integer enrolment ID. A nonexistent ID is treated as success. | Keep the integer ID and current success flash. |
| `GET /student` (`app.py:612-630`) | Resolves the authenticated local student, then joins enrolments to courses by integer IDs, filters by local `student_id`, and sorts by course code. | Obtain that profile’s `student_number` locally, ask the service for its courses, and preserve the existing row fields/order. |

### Schema and queries outside route handlers

- `init_db()` creates `courses` and `enrolments` for both PostgreSQL and SQLite
  (`app.py:128-140`, `164-179`). The enrolment table currently has integer
  `student_id` and `course_id`, a unique pair constraint, a timestamp, and
  foreign keys to both local students and courses. Course deletion therefore
  cascades to enrolments.
- Schema compatibility code checks the course columns and adds a missing
  `description` column (`app.py:182-192`). It is part of the legacy schema
  initialization and should remain for the flag-off path.
- The admin route’s `students` query is also relevant to the course UI: the
  template uses local student IDs and active flags to populate the enrolment
  selector (`app.py:371-375`, `templates/admin.html:84-103`).

### Templates

- `templates/admin.html` displays course/enrolment counts, a create-course
  form, the ordered course table and delete form, the active-student/course
  enrolment selector, and the current enrolment table with student names and
  course code/name (`templates/admin.html:6-12`, `61-120`). It expects
  `course.id`, `course.course_code`, `course.course_name`,
  `course.description`, and enrolment `id`, `student_number`, `first_name`,
  `last_name`, `course_code`, and `course_name`.
- `templates/student.html` displays the signed-in student’s courses with
  `course_code`, `course_name`, and `enrolled_at`, plus the existing empty
  state (`templates/student.html:13-22`).
- `templates/base.html` has no direct course data access; it renders shared
  navigation and flashed messages.

## Proposed ownership boundary

- The courses service owns course records and enrolment records in a dedicated
  PostgreSQL schema, proposed name `courses`.
- The monolith continues to own users, student profiles, names, active status,
  and authentication. The service stores `student_number` as an opaque string
  on enrolments. There is no foreign key or direct database access to the
  students table.
- The service database login is separate from the monolith’s login. Grant it
  only `USAGE` on the `courses` schema and the required table/sequence
  privileges there. It receives no access to `public` or other schemas. The
  monolith does not receive grants on `courses`; it calls the service API.
- Keep integer course and enrolment IDs and copy the existing IDs during
  migration. This preserves the identifiers embedded in current admin forms.
  Re-seed schema-local sequences above the copied IDs.
- Proposed tables:
  - `courses(id, course_code, course_name, description)` with unique
    `course_code` and the current defaults.
  - `enrolments(id, course_id, student_number, enrolled_at)` with an internal
    course foreign key using `ON DELETE CASCADE`, unique
    `(course_id, student_number)`, and no student foreign key.
- The service owns course deletion behavior and cascading enrolment deletion.
  Deactivating a student does not remove enrolments today; retain that behavior.
  There is no student-delete route today. If one is added later, it will need
  explicit service cleanup because the old cross-table cascade will no longer
  exist.

## Proposed service API

All API routes except `/health` require the configured service token as a
server-to-server bearer token. The token is an app setting populated from a
GitHub secret, never stored in the repository or sent to a browser. It should
be moved to Key Vault in a later step. Require HTTPS and propagate
`X-Correlation-ID` from the monolith; include it in structured service logs.
Return JSON errors with stable `code` and human-readable `message` fields.

| Method and path | Purpose and proposed response |
| --- | --- |
| `GET /health` | Unauthenticated App Service health check. |
| `GET /ready` | Authenticated deployment readiness check that verifies PostgreSQL connectivity from the Container App. |
| `GET /api/courses` | List courses sorted by `course_code`. Return an array of course objects with integer `id`, `course_code`, `course_name`, and `description`. |
| `POST /api/courses` | Create from `course_code`, `course_name`, and optional `description`; return `201` and the created course. Apply the current trim/uppercase rules. Return `409` for duplicate code and `400` for invalid fields. |
| `DELETE /api/courses/{course_id}` | Delete a course and cascade its enrolments. Return `204` whether or not the ID existed, matching the existing route’s “deleted if it existed” behavior. |
| `GET /api/enrolments` | List records for the admin dashboard, ordered by descending enrolment ID. Return `id`, `course_id`, `student_number`, `enrolled_at`, and the service-owned course code/name. It does not return student PII. |
| `POST /api/enrolments` | Enrol with `{ "course_id": integer, "student_number": string }`; return `201` with the enrolment. Return `409` for a duplicate and `404` for an unknown course. The monolith validates that the local student is active before calling this endpoint. |
| `DELETE /api/enrolments/{enrolment_id}` | Remove an enrolment. Return `204` whether or not the ID existed, matching the current route. |
| `GET /api/students/{student_number}/courses` | List the student’s courses sorted by course code. Return course fields and the original `enrolled_at` value expected by the template. |
| `GET /api/courses/{course_id}/students` | List enrolments for a course using student numbers only, with enrolment IDs/timestamps. Do not expose student names or emails from this service. |

## Monolith integration when enabled

`COURSES_SERVICE_ENABLED` defaults to false. With it false, existing SQL paths
remain in use unchanged. With it true:

- The admin dashboard gets course/enrolment data from the API and continues
  loading local students. It enriches service enrolments with names from the
  monolith’s students table so the existing template contract stays intact.
- The create-enrolment route keeps the active-student check locally, resolves
  `student_number`, then asks the service to verify the course and create the
  enrolment. The service’s duplicate response maps to the existing flash.
- The student dashboard uses the local profile’s `student_number` to request
  that student’s course list.
- Course/enrolment mutations and reads use a short bounded timeout and send the
  request correlation ID. A service/network error renders a clear error page
  with HTTP 503; it must not silently fall back to stale legacy data when the
  flag is true. The flag-off path remains the rollback switch.

## Migration, cutover, and rollback concerns

- Copy courses and enrolments without modifying or deleting the original
  tables. Map legacy enrolment `student_id` to `students.student_number` by
  joining the legacy students table; preserve course/enrolment IDs and stored
  timestamps. Make the migration safe to inspect and rerun only if its
  idempotency rules are explicit.
- The comparison command should report counts and row-level mismatches for
  course fields and enrolment identity, course association, and timestamp.
- Required order: provision the service/schema, deploy the service, deploy the
  monolith with the flag off, pause course/enrolment writes for the final copy
  and comparison, enable the flag, then resume writes. A short write freeze is
  needed because the flag-off monolith still writes only to the original
  tables; a write between copy and switch would be missing from the service.
- Before the service accepts real writes, setting the flag false safely
  returns to the untouched legacy tables. After cutover, the legacy tables are
  stale; rollback requires a write freeze and manual reconciliation of records
  created or changed in the service. There is no reverse-copy path. This is a
  known limitation; no dual-write is proposed because it introduces
  partial-write and consistency failures.

## Infrastructure and capacity gate

The proposal adds a third Linux web app to the existing B1 plan. Before
provisioning it, inspect the plan’s recent CPU and memory metrics and confirm
headroom with the monolith and notifier running. The current Step 7 design has
not performed that capacity check and does not assume the third app will fit;
record the observed period, peak/average CPU and memory, and Azure result
before making the infrastructure change.

## Approved decisions

1. Preserve legacy integer course and enrolment IDs.
2. Freeze course and enrolment writes for the final copy, comparison, and
   feature-flag cutover; record the freeze in the migration log.
3. Do not build a reverse-copy. Rollback before service writes is safe by
   setting the feature flag false. After real service writes, rollback needs
   manual reconciliation; this is a known limitation.
4. Use one shared bearer token from GitHub Actions Secrets in both service and
   monolith app settings until a later Key Vault migration.
5. Make migration idempotent, fail comparison on any mismatch, reseed both
   identity sequences, and verify a new course can be created after migration.
6. Set the monolith HTTP timeout to three seconds and verify its HTTP 503
   service-unavailable page.
