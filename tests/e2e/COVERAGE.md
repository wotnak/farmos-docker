# Base farmOS E2E coverage

The suite targets the farmOS version in the selected image. It enables standard
modules through the browser setup wizard
and module form. Each feature test creates its own uniquely named records on a
disposable installed site. No prefilled database or test-only backend module is
required; Drupal recipes are unnecessary for these fixtures.

| Area | Scenarios | Spec |
| --- | --- | --- |
| Installation | Browser installation with immutable environment settings or the standalone DB form; site/admin configuration; wizard and remaining standard modules | `install.spec.js` |
| Assets | Create, read, edit, archive and delete all 12 bundles: animal, compost, equipment, group, land, material, plant, product, seed, sensor, structure, water; bundle-specific fields and taxonomy | `features/assets.spec.js` |
| Asset relationships and maps | Parent persistence, circular-reference rejection, fixed geometry, rendered map, identification tags, ownership/flags | `features/assets.spec.js` |
| Bulk operations | List filters, clone with preserved notes and distinct ID, archive/unarchive selected records | `features/assets.spec.js` |
| Attachments | Private file bytes; private original image and generated AVIF derivative; anonymous denial; public generated CSS | `features/assets.spec.js`, `smoke.spec.js` |
| Logs | CRUD for all ten bundles; timestamps, subtype fields, pending/done/abandoned status, owner assignment and asset history | `features/logs.spec.js` |
| Quick forms | Birth with lineage and weight; planting with seeding/transplanting/harvest records; movement; group membership; inventory | `features/logs.spec.js`, `features/quantities.spec.js` |
| Computed relationships | Pending movement/group changes do not apply; completed changes do; clearing relationships; fixed past dates | `features/logs.spec.js` |
| Quantities | Standard, material and test quantities; decimal values, measures, units, labels, edits and removal | `features/quantities.spec.js` |
| Inventory | Exact totals after reset/increment/decrement; pending excluded; completing applies adjustment; abandoning removes it | `features/quantities.spec.js` |
| Farms | Organization CRUD/archive, duplicate-name rejection, asset association surviving rename, cross-farm parent restriction | `features/organizations.spec.js` |
| CSV | Download template; import quoted text and type-specific fields; assert saved records; filtered bulk export and downloaded content; missing-file validation | `features/import-export.spec.js` |
| KML | Upload/parse polygon, create parent and field, assert saved geometry/location flags/relationship/map, export selected geometry | `features/import-export.spec.js` |
| Sensors | Create a linked basic data stream; private-key enforcement; exact readings, timestamps and filtering; public read without public write; delete stream | `features/data-streams.spec.js` |
| Users and roles | Login/logout, anonymous denial, create/block Viewer, Viewer read-only access, Worker/Manager create/edit and ownership-dependent deletion, denied administration | `features/access.spec.js` |
| Administration | Taxonomy CRUD and saved site settings reflected in API, with original settings restored | `features/administration.spec.js` |
| JSON:API | Session-authenticated CRUD, linked assets/logs, filtering, missing-CSRF and anonymous-write rejection, deletion | `features/api.spec.js` |
| OAuth | Key generation if absent; real authorization-code/S256 PKCE login/consent; token/refresh exchange; role-scoped API access; replay rejection; private-key download protection | `features/oauth.spec.js` |
| Collaboration | Comment CRUD; stored revisions and old values; current values preserved; revision revert unavailable as designed by farmOS | `features/collaboration.spec.js` |
| Persistence | Fresh login and exact linked records/file bytes after app+DB recreation; unchanged public OAuth signing keys | `persistence.spec.js` |
| Container operation | Read-only settings/code, writable file paths before/after recreation, cron exit and persisted last-success timestamp | `scripts/test.sh` |

## Scope boundaries

- This is broad workflow coverage, not every possible field combination or every
  upstream validation branch. Upstream farmOS PHPUnit remains a separate suite.
- The browser matrix currently uses Chromium, English and UTC. External Google
  Maps/Mapbox providers and localization downloads are excluded from module
  setup. No external service credentials are needed.
- Map tests verify saved geometry and rendered map controls, not third-party
  tile availability or pixel-perfect map appearance.
- Generic plans have no standard user-facing bundle in the base distribution.
  Crop and grazing plans belong in the [contrib plan](CONTRIB-TEST-PLAN.md).
- Private files are the standard attachment behavior. The suite does not change
  that setting to manufacture a public attachment case.
- Email delivery, live hardware/vendor integrations, load testing, cross-version
  upgrades and all contrib modules remain outside this base acceptance suite.

## Observed upstream CSV limitation

On the pinned farmOS 4.0.4 code, with the Farms module enabled, a hand-written
equipment CSV omitting the optional `farm` column triggers
`OrganizationLookup::query(): trim(null)` and a batch HTTP 500. This occurs in
upstream migration code, not in container filesystem permissions. The passing
CSV scenario uses the full header returned by farmOS's own template download,
including empty optional columns. There is no upstream patch or skipped test
hidden in this suite. Recheck this edge case when updating farmOS.
