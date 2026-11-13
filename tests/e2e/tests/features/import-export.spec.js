import { test, expect } from '@playwright/test';
import { login, uniqueName } from '../../support/farmos.js';

const csvCell = value => `"${String(value).replaceAll('"', '""')}"`;

test('CSV import preserves quoted text and type-specific fields, and selected assets export as CSV', async ({ page }) => {
  await login(page);
  const prefix = uniqueName('CSV equipment');
  const first = `${prefix}, "tractor"`;
  const second = `${prefix} implement`;
  const notes = 'Imported café equipment, with "quoted" notes.';
  await page.goto('/import/csv/csv_asset:equipment');
  const template = await page.request.get('/import/csv/csv_asset:equipment/template');
  expect(template.status()).toBe(200);
  const templateText = await template.text();
  const columns = templateText.split(/\r?\n/, 1)[0].split(',').map(cell => cell.replace(/^"|"$/g, ''));
  expect(columns).toContain('name');
  expect(columns).toContain('manufacturer');
  // Use the published template, including optional module columns such as farm.
  const rows = [
    { name: first, notes, manufacturer: 'E2E manufacturer', model: 'Model 42' },
    { name: second, notes: 'Imported implement', manufacturer: 'E2E manufacturer', model: 'Model 7' },
  ];
  const csv = [columns, ...rows.map(row => columns.map(column => row[column] ?? ''))]
    .map(row => row.map(csvCell).join(',')).join('\n');
  await page.locator('input[type="file"]').setInputFiles({
    name: 'equipment.csv', mimeType: 'text/csv', buffer: Buffer.from(csv),
  });
  await page.getByRole('button', { name: 'Import', exact: true }).click();
  await expect(page.getByText(/Processed 2 items \(2 created, 0 updated, 0 failed/)).toBeVisible({ timeout: 120_000 });
  for (const name of [first, second]) {
    const response = await page.request.get('/api/asset/equipment', { params: { 'filter[name]': name } });
    expect(response.status()).toBe(200);
    const records = (await response.json()).data;
    expect(records).toHaveLength(1);
    expect(records[0].attributes.manufacturer).toBe('E2E manufacturer');
    if (name === first) expect(records[0].attributes.notes.value).toBe(notes);
  }

  await page.goto('/assets');
  await page.getByRole('button', { name: 'Filter', exact: true }).click();
  await page.locator('input[name="name"]').fill(prefix);
  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  for (const name of [first, second]) {
    const row = page.getByRole('row').filter({ has: page.getByRole('link', { name, exact: true }) });
    await row.getByRole('checkbox').check();
  }
  await page.getByRole('combobox', { name: 'Action:', exact: true }).selectOption({ label: 'Export CSV' });
  await page.getByRole('button', { name: 'Apply to selected items', exact: true }).click();
  await expect(page.getByRole('heading', { name: /Export a CSV of 2 assets/ })).toBeVisible();
  await page.getByRole('button', { name: 'Export', exact: true }).click();
  const link = page.getByRole('link', { name: /^csv_export-.*\.csv$/ });
  await expect(link).toBeVisible();
  const exported = await page.request.get(await link.getAttribute('href'));
  expect(exported.status()).toBe(200);
  const text = await exported.text();
  expect(text).toContain(csvCell(first));
  expect(text).toContain(second);
  expect(text).toContain('Model 42');
  expect(text).toContain(csvCell(notes));
});

test('KML import creates mapped land with a parent and exports the saved geometry', async ({ page }) => {
  await login(page);
  const name = uniqueName('Imported field');
  const parent = `${name} farm`;
  const filename = `${name.replaceAll(' ', '-')}.kml`;
  const coordinates = '21,52,0 21.001,52,0 21.001,52.001,0 21,52.001,0 21,52,0';
  const kml = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark>
<name>${name}</name><description>Imported field boundary</description>
<Polygon><outerBoundaryIs><LinearRing><coordinates>${coordinates}</coordinates></LinearRing></outerBoundaryIs></Polygon>
</Placemark></Document></kml>`;
  await page.goto('/import/kml');
  await page.locator('input[type="file"]').setInputFiles({
    name: filename, mimeType: 'application/vnd.google-earth.kml+xml', buffer: Buffer.from(kml),
  });
  await expect(page.getByRole('link', { name: filename, exact: true })).toBeVisible();
  await expect(page.locator('.ajax-progress')).toHaveCount(0);
  await page.getByLabel('Default land type', { exact: true }).selectOption('field');
  await page.getByRole('button', { name: 'Parse', exact: true }).click();
  await expect(page.locator('input[name="assets[0][name]"]')).toHaveValue(name);
  await expect(page.locator('textarea[name="assets[0][geometry]"]')).toContainText('POLYGON');
  await page.getByLabel('Create a parent asset', { exact: true }).check();
  await page.locator('input[name="parent[name]"]').fill(parent);
  await page.locator('select[name="parent[land_type]"]').selectOption('property');
  await page.getByRole('button', { name: 'Create assets', exact: true }).click();
  await expect(page.getByRole('link', { name, exact: true })).toBeVisible();
  const assetLink = page.getByRole('link', { name, exact: true });
  await assetLink.click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: parent, exact: true }).first()).toBeVisible();
  await expect(page.locator('.ol-viewport')).toBeVisible();
  const response = await page.request.get('/api/asset/land', { params: { 'filter[name]': name } });
  expect(response.status()).toBe(200);
  const [asset] = (await response.json()).data;
  expect(asset.attributes.is_fixed).toBe(true);
  expect(asset.attributes.is_location).toBe(true);
  expect(asset.attributes.intrinsic_geometry.value).toContain('POLYGON');
  expect(asset.relationships.parent.data).toHaveLength(1);
  await page.goto('/assets');
  await page.getByRole('button', { name: 'Filter', exact: true }).click();
  await page.locator('input[name="name"]').fill(name);
  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  await page.getByRole('row').filter({ has: page.getByRole('link', { name, exact: true }) }).getByRole('checkbox').check();
  await page.getByRole('combobox', { name: 'Action:', exact: true }).selectOption({ label: 'Export KML' });
  await page.getByRole('button', { name: 'Apply to selected items', exact: true }).click();
  const link = page.getByRole('link', { name: /^kml_export-.*\.kml$/ });
  await expect(link).toBeVisible();
  const exported = await page.request.get(await link.getAttribute('href'));
  expect(exported.status()).toBe(200);
  expect(await exported.text()).toContain(name);
  expect(await exported.text()).toContain('<Polygon>');
  expect(await exported.text()).toContain('21.001,52.001');
});

test('CSV import reports a missing source file without creating records', async ({ page }) => {
  await login(page);
  await page.goto('/import/csv/csv_asset:equipment');
  await page.getByRole('button', { name: 'Import', exact: true }).click();
  await expect(page.getByText('You have to upload a source file.', { exact: true })).toBeVisible();
});
