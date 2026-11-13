# Farm user journeys: E2E implementation plan

Research date: 2026-09-26. This is a proposed test plan; it does not add tests or
change the installed modules. Start with the existing locked farmOS 4.0.4
project and its seven contributed modules. Keep the current feature tests as
focused diagnostics, and add journeys that follow the same records through
planning, field work, stock accounting and review.

The main gap is the handoff between modules and people. For example, the suite
already tests a crop plan and a harvest separately. It does not yet prove that
a worker can find an assigned planting task, record its completion, and leave
the manager with consistent plan, calendar, inventory and sale records. Existing
coverage is recorded in [COVERAGE.md](COVERAGE.md) and
[CONTRIB-TEST-PLAN.md](CONTRIB-TEST-PLAN.md).

## Supported behavior to build on

These boundaries come from current official guides and the exact release
sources in the fixture. Proposed farm names, quantities and sequences below
are test scenarios, not claims about automatic integrations.

| Combination | What the software provides | What the user must do explicitly |
| --- | --- | --- |
| Core logs + Calendar | Pending logs support task planning; owners identify responsible users; Calendar displays logs. | Create or reschedule the log and mark work complete. A date on a plan timeline is not, by itself, an assigned task. [Log guide](https://farmos.org/guide/logs/), [Calendar](https://www.drupal.org/project/farm_calendar). |
| Crop Plan + Planting quick form | `?plan=<id>` preselects the plan's season. Submitting the quick form creates its selected plant/log records and opens the plan's Add planting form. | Finish that second form. Crop planning stages and operational log timestamps are separate records; do not assume editing either updates the other. [Crop Plan alpha4 source](https://ftp.drupal.org/files/projects/farm_crop_plan-3.0.0-alpha4.tar.gz), `src/Hook/FormHooks.php`, `src/Form/CropPlanAddPlantingForm.php`, `src/CropPlan.php`. |
| Grazing Plan + Movement quick form | `?plan=<id>` redirects a newly created movement to the Add grazing event form. Plan events reference movement logs and add duration/recovery values. | Save the event form and complete the movement log when animals actually move. Editing the event start is not evidence that the log timestamp changed. [Grazing Plan alpha2 source](https://ftp.drupal.org/files/projects/farm_grazing_plan-1.0.0-alpha2.tar.gz), `src/Hook/FormHooks.php`, `src/Form/GrazingPlanAddEventForm.php`. |
| Groups + movements | Members can inherit a group's location; a more recent individual movement can take precedence. | Record group membership changes, particularly when removing an animal for separate care. [Group logic](https://farmos.org/model/logic/group/), [location logic](https://farmos.org/model/logic/location/). |
| Quantities + inventory | Explicit reset, increment and decrement quantities determine stock, separately for each measure/unit pair. | Select the inventory asset and adjustment. A harvest or purchase label alone does not adjust stock. [Inventory guide](https://farmos.org/guide/inventory/), [calculation rules](https://farmos.org/model/logic/inventory/). |
| Ledger + inventory | Price quantities calculate the missing value in `quantity × unit price = total`. | Add physical stock adjustments separately. No automatic currency conversion, purchase-to-stock, sale-to-stock or invoice/payment workflow is assumed. [Ledger 3.0.0 source](https://ftp.drupal.org/files/projects/farm_ledger-3.0.0.tar.gz), `README.md`, `src/EventSubscriber/QuantityEventSubscriber.php`. |
| Eggs + groups/animals | Eligible active egg producers appear in the quick form; it creates a completed harvest with count, `egg(s)` units, asset references and copied locations. | Apply inventory adjustments and record sales separately. The pinned form reads the producers' current locations when submitted, even when the entered harvest date is older. [Eggs 3.0.0 source](https://ftp.drupal.org/files/projects/farm_eggs-3.0.0.tar.gz), `src/Plugin/QuickForm/Eggs.php`. |
| Bee/Fungi + core records | Bee supplies `bee_colony`; Fungi supplies `fungi`, required species/variety and optional substrate terms. Both use normal asset relationships and logs. | Describe inspections, splits, inoculations, flushes and product lots with the available records. Do not invent queen-management fields or an automatic mushroom production state machine. [Bee 3.0.0 source](https://ftp.drupal.org/files/projects/farm_bee-3.0.0.tar.gz), [Fungi 3.0.0 source](https://ftp.drupal.org/files/projects/farm_fungi-3.0.0.tar.gz), `src/Plugin/Asset/AssetType/`. |

The locked planning releases remain Crop Plan `3.0.0-alpha4` and Grazing Plan
`1.0.0-alpha2`. The [Grazing Plan project page](https://www.drupal.org/project/farm_grazing_plan)
now advertises `1.0.0-alpha3`; evaluate that as a separate dependency update.
Do not silently change the baseline while implementing these journeys.

## People and working rhythm

Use separate browser contexts and named accounts throughout each journey.
The administrator installs modules, configures the site and creates accounts.
The administrator must then leave the operational workflow.

| Persona | Work to exercise | Permission assertions |
| --- | --- | --- |
| Manager | Plan the week or season, assign work, correct records, reconcile stock and sales, archive finished assets. | Can manage the relevant records; does not gain account or site administration merely from Manager. |
| Worker | Find assigned work from the dashboard, profile or Calendar; record observations, quantities and completion; attach evidence. | Can edit another person's assigned record where the managed role permits it; cannot delete someone else's record, even when assigned to it; cannot update/delete taxonomy terms. |
| Viewer | Review production history, plan/calendar entries and permitted exports or API reads. | Cannot submit quick forms or mutate assets, logs, plans or their API resources. Verify actual read/export permissions instead of granting extra permissions to make a test pass. |

These are the standard managed-role boundaries in the
[People guide](https://farmos.org/guide/people/). Assignment is not an access-control
boundary. Do not assume workers see only their assigned assets, that farms are
isolated tenants, or that financial records are hidden from a standard Worker.
Verify contributed plan permissions for these roles before choosing who performs
each planning step.

## Priority 1: market garden, from seasonal plan to weekly sale

Proposed spec: `tests/journeys/market-garden.spec.js`.
Tags: `@journey @market-garden @crop-plan @calendar @ledger @inventory`.

Modules: core plants, seeds, products, land/structures, quantities, inventory,
planting quick form and roles; Crop Plan, Calendar and Ledger. Fixtures: one
manager, one worker and one viewer; a propagation area, two beds, one crop/variety,
one season, one seed lot and one harvested-product asset. Two successive plant
assets share the variety but retain distinct identities.

1. **Season setup, Manager.** Create the crop plan. Enter its planting quick
   form, confirm the season is prefilled, and create the first plant with seeding,
   transplanting and harvest logs. Leave future work pending. Complete the Add
   planting step and add a second succession with different dates. Confirm two
   distinct plants and plan records, not two links to the latest plant.
2. **Monday planning, Manager.** Assign the first transplanting log to Worker.
   Find the same log in the plant history, Calendar and worker task list. Move
   the log to another day and verify that its calendar entry moves without a
   duplicate. Inspect the plan's projected stage separately; explicitly edit its
   planning dates if the manager intends them to change too.
3. **Field work, Worker.** Open the assigned task through the UI. Record actual
   time, destination bed, quantity and notes, then mark it done. Pending work
   must not change current location; completing the movement must. Manager sees
   the same record and new location in a fresh session.
4. **Seed use, Worker.** Establish `1000 g` seed stock through an explicit
   quantity. Record `250 g` used on a seeding log with a decrement targeting the
   seed asset. Expect `750 g`. Preserve separate identities for the seed stock,
   growing plant and saleable product.
5. **Harvest days, Worker.** Record two harvests of `12.5 kg` and `7.5 kg`, each
   linked to the plant and a chosen lot identifier. Explicitly increment the
   product's stock by those amounts. Expect `20 kg`; a pending third harvest
   must not increase it. Assert that following the linked records reaches the
   originating plant, bed and harvest evidence.
6. **Weekly sale, Manager.** Create a sale referencing the product/lot. Enter
   price quantity `8 × 4.25 = 34.00` using one currency unit term. Add a separate
   weight quantity decrement of `8 kg` against product inventory. Expect `12 kg`
   remaining and a price total of `34.00`. The test supplies the physical/price
   correspondence; Ledger does not infer a conversion between those quantities.
7. **Review and season close.** Export selected records and check names, lot
   identifiers and numeric values, then inspect the API relationships. Correct
   one quantity and verify both the displayed result and the saved revision.
   Archive the finished plant; historical harvest and sale references remain
   readable. Recreate both containers and repeat the cross-record checks as
   Manager and Viewer.

Negative cases: duplicate plant in the plan; maturity days not greater than
transplant days; inconsistent Ledger total; Viewer mutation; Worker deletion of
Manager's task; an abandoned stock adjustment removing its previous effect.
Use the actual form validation for the pinned release. Do not assert that
overselling or insufficient stock is blocked without a supporting constraint.

This follows the distinct seed/plant roles and successive-planting model in the
[asset guide](https://farmos.org/guide/assets/). The numeric examples above are
test data, not agronomic recommendations.

## Priority 1: a grazing week with a herd and an individual exception

Proposed spec: `tests/journeys/grazing-week.spec.js`.
Tags: `@journey @grazing-plan @groups @calendar @inventory`.

Fixtures: three paddocks, a separate care area, two individually tracked animals,
one herd group, a feed asset and three role accounts. Use distinct timestamps
for membership, movement and care events.

1. Manager assigns both animals to the herd with a completed group-assignment
   log. Establish a completed move to paddock A and verify the group and both
   animals resolve there.
2. From a grazing plan, create pending group movements to B and C through the
   movement quick form. Finish each Add grazing event form. Set `24 hours`
   grazing and `168 hours` recovery on one event. Confirm correct group/location
   timeline rows, linked movement IDs and exact elapsed durations.
3. Assign B's movement to Worker. Worker finds it through Calendar or assigned
   logs and completes it. Both animals inherit B; C remains only planned.
   Editing the grazing event duration must update its timeline without silently
   completing or duplicating the underlying movement.
4. Worker records an observation and a medical log for one animal. Remove that
   animal from the herd and record a later individual move to the care area.
   Complete the herd's next move to C. The remaining member moves to C; the
   removed animal stays in the care area. Confirm the saved membership history.
5. Record `7.5 kg` feed use against initial `100 kg` stock through an explicit
   input quantity. Expect `92.5 kg`; verify the input still identifies the
   animals/group that received it. A medical log alone must not change stock.
6. Manager reviews group and individual histories and the plan. Viewer can
   inspect permitted records but cannot complete movements. Repeat membership,
   location, timeline and feed checks after container recreation.

Negative cases: duplicate movement in a plan; out-of-range duration/recovery
input; pending/abandoned movement excluded from current location; denied Viewer
plan edits. Treat paddock conflicts, stocking recommendations and treatment
withdrawal scheduling as manual decisions unless a tested module supplies them.
The core [group](https://farmos.org/model/logic/group/) and
[location](https://farmos.org/model/logic/location/) rules determine the expected
movement results; a plan's recovery band is not proof of an enforcement rule.

## Priority 2: poultry collection, stock reconciliation and sale

Proposed spec: `tests/journeys/poultry-week.spec.js`.
Tags: `@journey @eggs @inventory @ledger`.

Manager creates an eligible layer flock and a nonlayer control, then records
the flock's location. Worker collects `24` eggs on day one. Move the flock and
collect `30` on day two. Each harvest must reference the selected flock and the
location copied at entry, with count measure and `egg(s)` units. Confirm the
nonlayer is unavailable in the quick form.

Explicitly apply each harvest quantity to an egg-product inventory. Before
those adjustments, the quick forms alone must not create stock changes; after
them expect `54` eggs. Manager records a sale of `36 × 0.30 = 10.80` and a
separate decrement of `36` eggs, leaving `18`. A damaged-egg observation with an
explicit decrement of `2` leaves `16`. Reconcile the exact quantities and linked
logs from both the farm UI and API, then verify them after recreation.

Reject missing, negative and fractional egg counts through server validation.
Check Viewer denial and that archiving the flock removes it from the quick-form
options without deleting its harvest history. Do not treat `egg(s)` and `dozen`
as interchangeable unit terms or expect automatic packaging conversion.

Add a separate backdated-entry characterization case: after moving the flock,
submit an older harvest and inspect the copied location. The pinned
[Eggs implementation](https://ftp.drupal.org/files/projects/farm_eggs-3.0.0.tar.gz)
uses current location, not a historical lookup at the entered date. A user may
need to correct that location. Record this limitation rather than writing an
assertion for an unimplemented historical-location feature.

## Priority 2: apiary split to honey sale

Proposed spec: `tests/journeys/apiary-season.spec.js`.
Tags: `@journey @bee @calendar @ledger @inventory`.

Manager records parent and split bee colonies, their lineage and apiary location,
then assigns an inspection. Worker finds and completes it, uploads private
evidence and records a honey harvest of `8.25 kg`. Explicitly increment a honey
product's stock. Record a `3 kg` sale at `12.00` per unit, total `36.00`, with a
separate stock decrement; expect `5.25 kg` remaining.

Verify colony/inspection/harvest/product/sale links, private attachment bytes,
calendar task state, exact inventory and price values, and CSV/API output.
Rename the split colony and confirm references still target its UUID. Archive
it at the end of the scenario and verify historical access after recreation.
Viewer must not edit the inspection or sale. The released Bee bundle provides
the domain identity; observations and generic logs carry the beekeeping detail.

## Priority 2: mushroom batch, two flushes and closeout

Proposed spec: `tests/journeys/fungi-batch.spec.js`.
Tags: `@journey @fungi @calendar @ledger @inventory`.

Manager creates a mother culture and child production batch with required species
and substrate terms, then assigns an inoculation activity to Worker. Worker records it,
then explicit movements between incubation and fruiting locations. Record two
harvests, `4.75 kg` and `3.25 kg`, and explicit increments to a mushroom-product
inventory. Manager records a sale of `5 kg` at `6.40`, totaling `32.00`; a separate stock
decrement, leaves `3 kg`.

Verify mother/batch lineage, movement history, harvest quantities, product/lot
links and the sale. Edit a substrate description/reference and confirm its
saved value in API and CSV. Reject missing species and circular parent
references. Archive the spent batch while retaining all production records.
There is no automatic inoculation-to-fruiting transition, flush scheduler or
yield forecast in the pinned Fungi module; the worker records these events.

## Fixtures, assertions and runner design

**Independent farms.** Each journey starts from a fresh Compose project with
its own database, data volumes and artifacts. Use the existing locked Composer
fixture and production runtime, read-only application code, stock Playwright
image and normal browser installation. Do not depend on records created by
`features/` or another journey. Use unique names plus saved UUIDs, never fixed
database IDs or tests ordered across separate files.

**Small setup, real transitions.** Reuse helpers for login, creating accounts,
reference data and API reads. Prerequisite taxonomy, location and account seeds
may use authenticated public APIs once their creation is already covered.
Create plans, assignments, quick-form results, completion changes and business
adjustments through the UI under the responsible persona. Never insert their
expected results directly into the database.

**Recipes only for configuration.** The current explicit module installation is
sufficient for the first journeys. If repeated configuration warrants recipes,
put them under `fixtures/journeys/recipes/` and limit them to modules, settings
and deliberate role configuration. Seed assets and logs with named fixture
helpers. Recipes must not precreate completed workflows or broaden managed-role
permissions to hide access failures. Keep unit and crop terms consistent by
UUID, including terms used by multiple modules.

**Time.** Use a fixed past season for computed location/inventory scenarios.
Derive only upcoming/late-dashboard dates from the site's current date, captured
once per run. Keep each timeline's timestamps strictly ordered. A separate
`time-boundaries.spec.js` should exercise a non-UTC site timezone, UTC month
boundaries and daylight-saving transitions with explicit UTC/local expectations.
For a completed season, enter the planned dates in the past and preserve pending
status until the worker acts. Use a separate future task for the upcoming-list
assertion; do not advance server time midway through a journey. Changing the
browser clock does not change PHP/PostgreSQL time. The pinned crop
timeline computes a day as 86,400 seconds; characterize daylight-saving behavior
before promising local-calendar-day arithmetic. Do not run timezone-mutating
cases concurrently with other journeys on the same site.

**Evidence at each handoff.** Assert rendered names, links, status and quantities
when the next persona opens the record. Use API reads for stable UUID links,
exact fraction numerator/denominator values, authors versus assigned owners,
and computed inventory/location. Compare price calculations as decimals or
rationals, not binary floating-point tolerances that could hide a cent error.
Keep `kg` and `g`, currency terms and item counts separate; add a regression that
two measure/unit pairs remain separate inventory balances.

**Persistence and correction.** Extend the existing record manifest with plan
timeline expectations, quantities, unit UUIDs, owners, linked records and file
checksums/content. Recreate application and database containers while retaining
volumes; use new browser contexts to review all endpoints. Corrections must
change the current view without creating duplicate records, while available
revision history retains the previous values. Archive is not deletion.

**Negative paths.** Verify rejected submissions leave entity/plan-record counts
and stock unchanged. Separate browser validation from server validation by
deliberately submitting invalid values without native HTML validation in the
dedicated negative cases. Check UI and API permission denial, including CSRF
where relevant. Do not assume an owner field restricts read access.

**Field devices.** Repeat one worker handoff at a narrow phone-sized viewport,
including opening the assigned task, entering a quantity and submitting it.
Check usable controls and persisted results. This is responsive browser coverage;
offline capture, background synchronization and device GPS require separate
supported clients and are not implied by it.

**Concurrency follow-up.** Add `plan-entry-concurrency.spec.js` after the serial
journeys. The pinned Crop/Grazing submit hooks obtain the most recent global
quick-form entity ID before redirecting. This is a source-inspection risk, not
a reproduced defect. Use two authenticated users with distinct records and
controlled interleaved submissions; each redirect and plan association must
refer to that user's created record. Avoid a test that simply relies on random
timing. If a public-interface interleaving cannot reproduce the window reliably,
document it and pursue a focused upstream integration test rather than adding a
flaky E2E gate.

## Implementation order and acceptance

| Stage | Deliverable | Completion evidence |
| --- | --- | --- |
| 1 | Journey runner/selection, isolated fixtures, role contexts, saved record manifest; market-garden handoff through harvest. | Browser-created crop-plan quick-form association, assignment, Calendar reschedule and worker completion verified using the same record IDs. |
| 2 | Market stock/sales reconciliation and grazing group journey. | Exact arithmetic, plan/log distinction and member exceptions pass; no implicit inventory or scheduling behavior is assumed. |
| 3 | Poultry, apiary and fungi production journeys. | Each passes independently and in the seven-module configuration, including a real correction and permission/invalid-input path. |
| 4 | Time boundaries, interrupted-entry characterization and controlled concurrency investigation. | Deterministic assertions or a documented, reproducible upstream issue; no unconditional skip or expected-failure exemption. |
| 5 | CI integration and documentation. | Fresh install, all selected journeys, actual container recreation and review phase pass with JUnit, traces/screenshots on failure, logs, fixture lock and image identity retained. |

Propose a `journey` phase selecting `tests/journeys/**/*.spec.js` and a
`journey-persistence` phase that consumes only that run's manifest. Tags allow
focused debugging, but a selected journey must create all its prerequisites.
Use bounded per-journey timeouts and report durations before deciding which
extended cases belong on every PR versus a scheduled full run. Continue the
separate upstream PHPUnit suite.

Acceptance requires at least one Manager-to-Worker-to-Manager handoff in every
operational journey, stable cross-module references, exact numeric/time results,
successful persistence review and a meaningful denial/validation case. A page
load or a record count alone is insufficient. Describe discovered defects in
[CONTRIB-ISSUES.md](CONTRIB-ISSUES.md) with the pinned version and reproduction;
keep test mistakes distinct from application behavior.

Additional module candidates belong in a later fixture update, after checking
their own supported behavior. Asset Termination, for example, may replace a
manual end-of-production archive step if adopted; it must not be assumed in
these seven-module journeys. Restricted-entry scheduling must likewise use a
module that actually implements the required warnings, not infer them from a
material term. Coordinate those additions with
[the separate candidate research](CONTRIB-CANDIDATES.md).
