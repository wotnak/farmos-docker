import { test, expect } from '@playwright/test';
import { login, uniqueName, createAsset, fillEntityBasics, saveEntity, openTab, selectAutocomplete } from '../../support/farmos.js';
import { apiRecord, createLocation, moveTo, harvest, assertViewerAccess, exportAsset } from '../../support/production-contrib.js';
import { rememberRecord } from '../../support/contrib.js';

// farm_bee 3.0.0 contributes a bee_colony bundle using the standard asset fields.
// It does not add queen, hive, or inspection-specific fields.
test('bee colonies support apiary placement, inspections, honey harvests, edits and Viewer access', async ({ page, browser }) => {
  await login(page);
  const apiary = await createLocation(page, uniqueName('Apiary'));
  const parent = await createAsset(page, { type: 'bee_colony', name: uniqueName('Parent colony') });
  const filename = `${uniqueName('inspection').replaceAll(' ', '-')}.txt`;
  const contents = 'Colony inspection: brood present, stores adequate.';
  const colony = await createAsset(page, { type: 'bee_colony', name: uniqueName('Split colony'), configure: async () => {
    await openTab(page, 'Parents');
    await selectAutocomplete(page, 'parent[0][target_id]', parent.name);
    await openTab(page, 'Files');
    const upload = page.locator('input[name="files[file_0][]"]');
    await expect(upload).toHaveAttribute('data-once', /auto-file-upload/);
    await upload.setInputFiles({ name: filename, mimeType: 'text/plain', buffer: Buffer.from(contents) });
    await expect(page.getByRole('link', { name: filename, exact: true })).toBeVisible();
    await expect(page.locator('.ajax-progress')).toHaveCount(0);
  } });
  await moveTo(page, colony, apiary);
  await page.goto(`/log/add/observation?asset=${colony.id}`);
  const inspectionName = uniqueName('Colony inspection');
  await fillEntityBasics(page, { name: inspectionName, notes: contents });
  const inspection = await saveEntity(page, 'log');
  await expect(page.getByText(contents, { exact: true })).toBeVisible();
  const honey = await harvest(page, colony, uniqueName('Honey harvest'), '8.25', 'kg');
  const { record: honeyApi, included } = await apiRecord(page, 'log', 'harvest', honey.name, 'quantity');
  const quantity = included.find(item => item.type === 'quantity--standard');
  expect(Number(quantity.attributes.value.decimal)).toBe(8.25);
  expect(honeyApi.relationships.asset.data).toHaveLength(1);

  await page.goto(`${colony.path}/edit`);
  colony.name += ' established';
  await fillEntityBasics(page, { name: colony.name, notes: 'Queenright colony after the split.' });
  await saveEntity(page);
  await expect(page.getByText('Queenright colony after the split.', { exact: true })).toBeVisible();
  const href = await page.getByRole('link', { name: filename, exact: true }).getAttribute('href');
  const download = await page.request.get(href);
  expect(download.status()).toBe(200);
  expect(await download.text()).toBe(contents);
  const { record, included: related } = await apiRecord(page, 'asset', 'bee_colony', colony.name, 'parent,location');
  expect(related.find(item => item.id === record.relationships.parent.data[0].id).attributes.name).toBe(parent.name);
  expect(related.find(item => item.id === record.relationships.location.data[0].id).attributes.name).toBe(apiary.name);
  await exportAsset(page, colony, ['Queenright colony after the split.']);
  await assertViewerAccess(page, browser, colony, 'bee_colony');
  await page.goto(`${colony.path}/edit`);
  await page.locator('[name="archived[value]"]').check();
  await saveEntity(page);
  expect((await apiRecord(page, 'asset', 'bee_colony', colony.name)).record.attributes.archived).toBe(true);
  rememberRecord('bee', { path: colony.path, name: colony.name, apiPath: `/api/asset/bee_colony/${record.id}`,
    attributes: { archived: true }, relationships: { parent: record.relationships.parent.data[0].id, location: record.relationships.location.data[0].id }, file: { href, contents } });
  rememberRecord('bee', { path: inspection.path, name: inspectionName });
  rememberRecord('bee', { path: honey.path, name: honey.name, apiPath: `/api/log/harvest/${honeyApi.id}`, relationships: { asset: record.id } });
  rememberRecord('bee', { path: honey.path, name: honey.name, apiPath: `/api/quantity/standard/${quantity.id}`, attributes: { measure: 'weight', value: quantity.attributes.value } });
});
