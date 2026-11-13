# Issues found during contributed module testing

Test target: farmOS 4.0.4 / Drupal 11.3.14, with the exact dependencies in
the Composer lock saved with the original test artifacts. Findings below distinguish
reproduced application failures from test implementation mistakes. No upstream
reports are submitted automatically.

## Base farmOS CSV import rejects an omitted farm column

Status: reproduced in the base suite, unresolved upstream in the tested version.

With the Farms module enabled, import an equipment CSV containing `name`,
`notes`, `manufacturer` and `model`, but no `farm` column. The import batch returns
HTTP 500 because `OrganizationLookup::query()` calls `trim(null)`. A CSV using
the full downloaded template, including an empty `farm` column, succeeds.

The related [upstream fix #1054](https://github.com/farmOS/farmOS/pull/1054)
handles a missing taxonomy parent column. It does not fix this organization
lookup. Searches of GitHub and Drupal.org found no exact report for this case.
See [base coverage](COVERAGE.md) for the original observation.

## Contributed module findings

### Calendar View emits PHP 8.4 deprecations during module installation

Status: reproduced, non-fatal compatibility warning.

Enabling `farm_calendar` with `calendar_view` 2.1.10 on PHP 8.4.25 emits implicit
nullable parameter deprecations for `CalendarViewBase::getTimezone($field)` and
`CalendarViewBase::getCalendarCaption($string, $timestamp)`. Installation succeeds.
These come from the contributed Calendar View dependency, not the image wrapper.
Evidence: `modules-install.log` in contrib run artifacts. The suite retains those
logs rather than suppressing the warnings.

## Contrib CI compatibility warnings

Contrib CI validation also found non-fatal Drupal/dependency and PHPUnit
deprecations while running the fixture module and Crop Plan's upstream Kernel
test. Details and retained log names are in the
[contrib CI compatibility notes](../../examples/contrib-ci/README.md#validation-and-compatibility-findings).
These tests pass their assertions; that does not establish compatibility with
future Drupal or PHPUnit versions that remove the deprecated APIs.

## Test infrastructure findings fixed during implementation

- PHPCS can consume a shell script streamed into a CI container, skipping later
  commands while returning success. The CI examples redirect PHPCS stdin from
  `/dev/null`; validation checks that the later tool reports exist.
- Relative project/cache overrides could resolve differently in the shell and
  Compose. Runners now normalize them before passing paths to Docker.
- A reused Composer directory can retain locally edited installed modules.
  Normal acceptance runs now install into a fresh temporary project and remove
  it afterward. Reuse requires an explicit `FARMOS_PROJECT_PATH` override.
- `mktemp` creates directories with mode `0700`. On Linux, the runtime UID may
  differ from the Composer builder UID. Preparation now sets the generated
  project root to `0755` before starting the non-root runtime.

Initial selector and AJAX synchronization mistakes in the new specs were fixed
against the released forms. They did not demonstrate application defects.

## Isolated-network cron warning

The final contrib run's cron command returned success but logged a DNS failure
while fetching `https://updates.drupal.org/psa.json`. The application and database
deliberately use an internal Docker network. This prevents Drupal's advisory
check from reaching its external service. It is an environment limitation, not
a failure of the contributed workflows. See `cron.log`; do not interpret passing
browser tests as confirmation that Drupal's online update checks work in this
network configuration.
