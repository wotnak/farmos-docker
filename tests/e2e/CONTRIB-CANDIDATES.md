# Further contributed-module test candidates

Research date: 2026-09-26. Target fixture: farmOS 4.0.4, Drupal 11.3.14,
PostgreSQL, and the repository's PHP runtime.

Add Asset Termination, Weather, Custom Map Layers and REI next. They have stable
Drupal 11 releases, useful behavior beyond the current suite, and small dependency
sets. Asset Merge is also valuable, but deserves its own first run because it
rewrites relationships and its first stable release is only two weeks old.
Organic and Biodynamic are inexpensive additions with less new behavior to test.

This is a proposal. No candidates below were added to Composer, installed, or
run against this fixture during this research. Calendar, Ledger, Eggs, Bee,
Fungi, Crop Plan and Grazing Plan already have separate coverage and are excluded
from this shortlist. Discovery used both pages of the official
[farmOS ecosystem index](https://www.drupal.org/project/farm/ecosystem).

## Compatibility and evidence

The release dates below are maintenance signals, not a promise of ongoing
support. Drupal project-page update dates can change without a code release.
For the ranked candidates, I inspected the published release archives, including
`composer.json`, module metadata, and the relevant implementation. A declared
version range establishes eligibility for a Composer trial; it does not establish
that the module works with this exact lock or with the other modules.

| Priority | Candidate and release | Confirmed declarations and dependencies | Proposed first test and effort |
| --- | --- | --- | --- |
| 1 | [Asset Termination 2.1.1](https://www.drupal.org/project/farm_asset_termination), 2026-04-18 | Drupal `^11`; depends on bundled `farm_log`. Its Composer file has no farmOS version constraint, so farmOS 4 compatibility still needs installation proof. | Complete a termination log and verify asset state, links and revisions. Medium. |
| 2 | [Weather 3.0.0](https://www.drupal.org/project/farm_weather), 2026-02-14 | Drupal `^11`, farmOS `^4`; bundled Observation, Standard Quantity and Quick Form modules. | Record decimal precipitation in each measurement system and verify the generated log and quantity. Low. |
| 3 | [Custom Map Layers 1.3.0](https://www.drupal.org/project/farm_map_custom_layers), 2026-02-14 | Drupal `^9 \|\| ^10 \|\| ^11`, farmOS `^2 \|\| ^3 \|\| ^4`; bundled `farm_map`. | Configure XYZ and WMS layers in the browser, verify local tile requests, edit and disable them. Medium. |
| 4 | [REI 3.0.0](https://www.drupal.org/project/farm_rei), 2026-05-17 | Drupal `^11`, farmOS `^4`; bundled Input and Material Type modules. | Combine two material quantities and verify the input log receives the larger restricted-entry interval. Low to medium. |
| 5 | [Asset Merge 1.0.0](https://www.drupal.org/project/farm_asset_merge), 2026-09-11 | Drupal `^11`, farmOS `^4`; asset/entity/field modules, Views, Options and Entity Reference Integrity. The current fixture already locks the latter at `2.0.1`. | Merge duplicates with linked records; verify reassigned references, archived duplicates, revision messages and rejected invalid merges. Medium to high. |
| 6 | [Organic 3.0.0](https://www.drupal.org/project/farm_organic), 2026-01-25, plus [Biodynamic 2.2.0](https://www.drupal.org/project/farm_biodynamic), 2026-01-25 | Organic declares Drupal `^11`, farmOS `^4`; Biodynamic includes Drupal 11 and farmOS 4 in its ranges. Both depend on bundled `farm_flag`. | Apply and remove the supplied flags, filter records, and verify JSON:API and CSV output. Low. |
| 7 | [Project Plan 2.0.0-beta1](https://www.drupal.org/project/farm_project_plan), 2026-04-03 | Drupal `^11`, farmOS `^4`; bundled Plan and farmOS Entity modules. Still a beta release. | Create a general project with goal, dates and logs; edit it and exercise duplicate-reference validation. Medium; separate experimental job first. |

## Scenarios worth implementing

### Asset Termination

Create an asset and a pending termination log with a fixed date in the past.
Assert that pending does not archive the asset; complete the log, then verify
archival, the termination date/link, and the new revision message. Check the
configuration that disables automatic archival and one configured default log
type. Add Viewer read and write-denial checks, API assertions, and persistence.

The inspected save hook archives only completed termination logs dated at or
before the current time. It does not implement a general undo operation. Test
changing or deleting a termination log against the actual stored archive state;
do not assume that this automatically unarchives assets. Source:
[2.1.1 archive](https://ftp.drupal.org/files/projects/farm_asset_termination-2.1.1.tar.gz),
`src/Hook/EntityHooks.php` and `src/Field/AssetTerminationItemList.php`.

### Weather

Use `/quick/precipitation` with a fixed date and `1.25`. Verify a completed
Observation log, the precipitation quantity, notes, and timestamp through the
browser and API. Repeat after changing the measurement system, then restore it.
The implementation chooses **cm** for the default system and **inches** for US
units. Exercise zero, a negative value, and missing date according to form
validation, then verify Viewer denial. This module records observations; it does
not need a forecast service, sensor or external account. Source:
[3.0.0 archive](https://ftp.drupal.org/files/projects/farm_weather-3.0.0.tar.gz),
`src/Plugin/QuickForm/Precipitation.php`.

### Custom Map Layers

Run a tiny local tile service that records requests and returns fixed PNGs.
Create an XYZ overlay through the module UI, give it a group and opacity, and
verify its layer selector and tile requests on a real asset map. Edit the URL,
disable and re-enable the layer, then delete it. Add a WMS case checking request
parameters, plus invalid JSON in the advanced options and Viewer configuration
denial. Persist the configuration across container recreation.

The release README says only XYZ is supported, but the released form offers
both XYZ and WMS, including layer names, styles and version. Base the test on the
implementation and validate rendering before claiming both work. Source:
[1.3.0 archive](https://ftp.drupal.org/files/projects/farm_map_custom_layers-1.3.0.tar.gz),
`src/Form/CustomMapLayerForm.php` and `src/EventSubscriber/MapRenderSubscriber.php`.
Use local responses, without paid map keys or public tile-server availability.

### REI

Create Material Type terms with intervals of two and five days. Add corresponding
Material quantities to an Input log and assert the saved interval is five.
Verify a manual override, an edit, API serialization and persistence. Cover the
no-configured-interval case and reject unauthorized edits.

The released module stores integer **days** and copies the largest configured
interval from referenced material types. Its README still lists active-interval
warnings, dashboard display and map integration as TODO items. Do not promise
those workflows or interpret this test as validation of agricultural safety
rules. Source:
[3.0.0 archive](https://ftp.drupal.org/files/projects/farm_rei-3.0.0.tar.gz),
`README.md` and the module's hooks.

### Asset Merge

Create two compatible duplicate assets, each with distinct field values and
linked logs, and give one a child asset. Select a survivor through the merge UI.
Check preserved/combined field values, every reassigned reference, archived
duplicates and revision messages. Test candidate detection, dismissing and
reopening a candidate, and a merge rejected by an existing relationship
constraint. Snapshot all involved records before that rejection and verify
nothing changed. Confirm the merge permission is enforced independently of
ordinary asset editing.

The project promises transactional rollback and includes kernel tests for
validation, reference discovery and quantity-host revisions. Those tests are
useful guides for browser cases, not evidence that this release passes here.
Source: [1.0.0 archive](https://ftp.drupal.org/files/projects/farm_asset_merge-1.0.0.tar.gz),
`tests/src/Kernel/` and `src/Form/MergeAssetsForm.php`. Keep the first run separate
from the combined module fixture so failures in reference rewriting are easy to
attribute.

### Organic, Biodynamic and Project Plan

Organic installs `organic`, `notorganic` and `transitionalorganic` flag
configuration. Biodynamic supplies a flag too. Exercise one asset and one log,
including filters, bulk changes and serialization. Do not assume mutually
exclusive flags or certification validation; these modules supply labels.
Sources: [Organic archive](https://ftp.drupal.org/files/projects/farm_organic-3.0.0.tar.gz)
and [Biodynamic archive](https://ftp.drupal.org/files/projects/farm_biodynamic-2.2.0.tar.gz).

Project Plan supplies a general `project` plan with start/end timestamps, a goal
and log references, including a duplicate-reference constraint. Use two logs of
different types, edit the goal/dates, verify record navigation, archive it, and
check Viewer access. Do not assume automatic scheduling or dependencies between
jobs. Source: [2.0.0-beta1 archive](https://ftp.drupal.org/files/projects/farm_project_plan-2.0.0-beta1.tar.gz),
`src/Plugin/Plan/PlanType/Project.php` and its add-log action.

## Worth separate research or a dedicated fixture

| Candidate | Current evidence | Next decision |
| --- | --- | --- |
| [Multitenant 2.0.0-beta1](https://www.drupal.org/project/farm_multitenant) | Release declares Drupal 10/11 and farmOS 4. Archive requires `drupal/group:^3`, PHP `>=8.4` and farmOS `^3 \|\| ^4`. The project documents a PostgreSQL core-patch requirement and supplies an example-role recipe. | High test value, high setup cost. First resolve Group without changing the base lock and determine whether the reported PostgreSQL issue applies to Drupal 11.3.14. Then use two farms and separate users to test UI/API isolation, memberships and files. Do not assume the old patch is still required or already fixed. |
| [Conservation Planner 1.4.0](https://www.drupal.org/project/farm_rcd) | Stable Drupal 11/farmOS 4 release. Source requires Symfony Mailer Lite, Tagify, PHPWord and mbstring. Its README warns that it changes the farmOS model and UI for Resource Conservation District workflows. | Use a separate fixture, not the general combined matrix. Cover intake, site assessment, resource conservation/practice plans, document generation and email to a local SMTP sink. First confirm the fixture's PHP extensions and required libraries. |
| [Calculation 2.0.0-beta1](https://www.drupal.org/project/farm_calculation) | Drupal 11/farmOS 4 declared. Provides a calculation log; payload fields are hidden and normally populated by another module's calculation provider. | Add only with a real provider and a deterministic local service. Generic log CRUD would add little coverage on its own. |
| [Asset Link 1.0.0-alpha18](https://www.drupal.org/project/farmos_asset_link/releases/1.0.0-alpha18) | The March 2026 release declares Drupal 11 and explicitly describes farmOS 4 compatibility fixes. Drupal marks the release unsupported. Its source/dependencies were not inspected here. | Consider a separate mobile-client journey after inspecting its build, authentication and plugin requirements. Eligibility is confirmed by release metadata; fixture compatibility remains unknown. |

The dedicated-fixture recommendations are based on source scope and dependency
size, not test runs. Multitenant and Conservation Planner release sources are
available in the [Multitenant archive](https://ftp.drupal.org/files/projects/farm_multitenant-2.0.0-beta1.tar.gz)
and [Conservation Planner archive](https://ftp.drupal.org/files/projects/farm_rcd-1.4.0.tar.gz).

## Defer for compatibility or missing release evidence

- [Ecowitt 1.0.0-beta1](https://www.drupal.org/project/farm_ecowitt) declares
  Drupal `^10`. A future compatible release would be useful for recorded sensor
  POST payloads, units/timestamps and private-key denial, without real hardware.
- [MyFarmKey 1.1.0](https://www.drupal.org/project/farm_myfarmkey),
  [FarmLab 2.0.2](https://www.drupal.org/project/farm_farmlab),
  [Coffee 1.0.0](https://www.drupal.org/project/farm_coffee) and
  [Template 1.0.0-alpha3](https://www.drupal.org/project/farm_template) have listed
  releases whose Drupal ranges exclude 11. Check maintained branches separately;
  a project-page update does not establish a port.
- [Animal Weight](https://www.drupal.org/project/farm_animal_weight),
  [Forest](https://www.drupal.org/project/farm_forest) and
  [Product Inventory](https://www.drupal.org/project/farm_product_inventory) had
  no listed tagged releases on their project pages. Establish an upstream commit,
  declared compatibility and documented workflow before writing a fixture.
- [FarmData2 1.3.0](https://www.drupal.org/project/farmdata2) lists Drupal `>=10`,
  which includes 11 numerically, but that alone does not confirm farmOS 4 support.
  Its Drupal page is marked minimally maintained. Inspect the current upstream
  application and dependency constraints before treating it as an installable
  farmOS 4 module.
- [farmOS Profile](https://www.drupal.org/project/farm_profile) is explicitly
  obsolete and unsupported. Do not add it; the existing core Farm Organization
  workflows already cover the current farm-level entity model.
- [Integrations 1.0.0](https://www.drupal.org/project/farm_integration) declares
  Drupal 11 but only adds a menu entry for other integrations. Test it through
  a useful integration dependency rather than giving it a standalone E2E job.

## Proposed implementation order

1. Start with exact pins for `farm_asset_termination:2.1.1`,
   `farm_weather:3.0.0`, `farm_map_custom_layers:1.3.0` and `farm_rei:3.0.0`.
   Resolve each against a copy of the current fixture lock and inspect the diff.
   Keep farmOS 4.0.4 and Drupal 11.3.14 fixed. Record conflicts as findings instead
   of silently upgrading the baseline or bypassing dependency constraints.
2. Install each on a fresh PostgreSQL site and implement the browser scenarios
   above, with negative permissions, API checks and post-recreation assertions.
   Use deterministic dates and local tile responses. Add them to the combined
   fixture only after individual runs pass.
3. Give Asset Merge its own initial job, then test its interaction with Ledger
   quantities, organization boundaries and termination state. Add the flag
   modules in a small combined job. Keep Project Plan beta explicitly selected.
4. Treat Multitenant and Conservation Planner as separate deployment profiles.
   They change permissions or workflows substantially enough that success in the
   general module matrix would not validate their intended use.

The ecosystem list also includes projects already shipped inside farmOS, such
as Log entity and Google map support. Those belong to core coverage. A project
being listed as related to farmOS is not sufficient reason to add another
Composer dependency.
