# Contributed module coverage and remaining work

Original coverage was verified on 2026-09-26 against farmOS 4.0.4 and Drupal
11.3.14. Current runs resolve fresh compatible dependencies and save their exact
Composer lock with the reports. The default run includes all seven modules below,
including Crop Plan and Grazing Plan. Alpha releases are allowed and tested normally.

## Implemented coverage

| Module | Previously tested release | Browser and API assertions |
| --- | --- | --- |
| [Calendar](https://www.drupal.org/project/farm_calendar) | 2.0.0, with Calendar View 2.1.10 | Pending/completed event markers, record links, month navigation, California timezone across a UTC month boundary, moving an event by editing its date, Viewer read-only access. |
| [Ledger](https://www.drupal.org/project/farm_ledger) | 3.0.0 | Purchase and sale logs linked to assets, decimal count/unit price/total calculations in all three directions, invalid totals, edits, unit terms, CSV and JSON:API output, Viewer UI/API write denial. |
| [Eggs](https://www.drupal.org/project/farm_eggs) | 3.0.0 | Egg-producing flock, two dated harvests, inherited location and asset links, count/units, editing quantities, missing/negative/fractional count validation, archived flock exclusion, Viewer denial. |
| [Beekeeping](https://www.drupal.org/project/farm_bee) | 3.0.0 | Colony lineage and apiary location, inspection, honey harvest and weight, private attachment, edits, archive, CSV/API and Viewer restrictions. This version supplies a colony bundle rather than additional bee-specific fields. |
| [Fungi](https://www.drupal.org/project/farm_fungi) | 3.0.0 | Required species, substrate terms, lineage, location, inoculation activity, harvest and weight, substrate edit, archive, module-specific CSV columns, API and Viewer restrictions. |
| [Crop Plan](https://www.drupal.org/project/farm_crop_plan) | 3.0.0-alpha4 | Season and two plantings, plan relationships, rendered timeline, seeding/transplant/maturity dates, maturity edit, duplicate rejection, Viewer access, archive. These tests attach existing plants. |
| [Grazing Plan](https://www.drupal.org/project/farm_grazing_plan) | 1.0.0-alpha2 | Animal and paddock, movement quick form and plan event, pending location semantics, rendered timeline, grazing/recovery duration, edits, duplicate rejection, completed movement updates location, Viewer access. |

Each module saves records for a second phase after application and database
containers are recreated. That phase verifies browser pages, API fields and
relationships, quantity values and uploaded bytes where present. Tests use
unique names and create content through browser/API workflows. No content recipe
or prefilled database is needed. Module installation is explicit via Drush.

The suite has ten workflow tests, seven module persistence tests and a shared
browser installation test. Specs live in `tests/contrib/`. See [README.md](README.md)
for commands and extraction instructions, and [CONTRIB-ISSUES.md](CONTRIB-ISSUES.md)
for findings. There are no unconditional skips or expected-failure exemptions.

## Dependency and runtime boundaries

`fixtures/contrib/composer.json` defines an independent test
project. Each run resolves the latest compatible farmOS and module dependencies
and records its Composer lock with the test artifacts. Composer excludes
development dependencies. It runs in the development
runtime during preparation. The production runtime serves the result read-only,
with public and private data volumes writable. Playwright uses its stock image
and mounted test project.

All seven modules run together by default. `CONTRIB_MODULES` can select one or
more modules; only those modules and their dependencies are enabled on that fresh
site. The complete fixture remains installed on disk. This allows isolated
module debugging without maintaining eight overlapping Composer locks.

## Remaining work

- Run each selected module configuration in a broader CI matrix if module
  interactions warrant it. The current CI acceptance job exercises the default
  combined configuration.
- Crop and grazing tests cover two-plant and single-animal workflows. Large
  seasons, grazing groups, multiple paddocks and performance are future cases.
- Crop Plan also integrates with the planting quick form. The suite currently
  covers attaching existing plants; the plan-specific quick-form integration
  remains an additional case.
- Ledger uses ordinary unit terms to label prices. Currency conversion and
  automatic inventory effects are not features of the tested release.
- [Ecowitt](https://www.drupal.org/project/farm_ecowitt): the researched beta
  requires Drupal 10. Establish a compatible release before adding deterministic
  sensor-payload tests. Do not bypass Composer compatibility constraints.
- [Animal Weight](https://www.drupal.org/project/farm_animal_weight): establish
  maintained source and farmOS 4 compatibility before adding visualization tests.
- External vendor integrations should use local response fixtures and separate
  contract tests instead of live accounts or credentials.

The [farmOS ecosystem index](https://www.drupal.org/project/farm/ecosystem)
provides further candidates. The release observations here describe the pinned
fixture rather than guaranteeing compatibility with later releases.
