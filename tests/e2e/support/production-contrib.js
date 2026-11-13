import { expect } from '@playwright/test';
import { login, createAsset, openTab, selectAutocomplete, fillEntityBasics, saveEntity } from './farmos.js';
import { createViewer } from './contrib-accounts.js';

export async function apiRecord(page, entity, bundle, name, include) {
  const response = await page.request.get(`/api/${entity}/${bundle}`, {
    params: { 'filter[name]': name, ...(include ? { include } : {}) },
  });
  expect(response.status(), await response.text()).toBe(200);
  const document = await response.json();
  expect(document.data).toHaveLength(1);
  return { record: document.data[0], included: document.included || [] };
}

export async function createLocation(page, name) {
  return createAsset(page, { type: 'land', name, configure: async () => {
    await page.locator('[name="land_type"][value="field"]').check();
  } });
}

export async function moveTo(page, asset, location) {
  await page.goto('/quick/movement');
  await page.locator('[name="date[date]"]').fill('2024-01-01');
  await selectAutocomplete(page, 'asset', asset.name);
  await expect(page.locator('.ajax-progress')).toHaveCount(0);
  await selectAutocomplete(page, 'location', location.name);
  await expect(page.locator('.ajax-progress')).toHaveCount(0);
  await page.getByRole('button', { name: 'Submit', exact: true }).click();
  await expect(page.locator('[data-drupal-messages]')).toContainText('Log created');
  await page.goto(asset.path);
  await expect(page.locator('.field--name-location')).toContainText(location.name);
}

export async function harvest(page, asset, name, value, units) {
  await page.goto(`/log/add/harvest?asset=${asset.id}`);
  await fillEntityBasics(page, { name });
  await openTab(page, 'Quantity');
  await page.locator('[name="quantity[actions][bundle]"]').selectOption('standard');
  await page.getByRole('button', { name: 'Add new quantity', exact: true }).click();
  await page.getByLabel('Measure', { exact: true }).selectOption('weight');
  await page.getByLabel('Value', { exact: true }).fill(value);
  await page.getByLabel('Units', { exact: true }).fill(units);
  await page.getByRole('button', { name: 'Create quantity', exact: true }).click();
  await expect(page.locator('#edit-quantity-wrapper')).toContainText(value);
  const log = await saveEntity(page, 'log');
  await expect(page.locator('.field--name-quantity')).toContainText(value);
  await expect(page.getByRole('link', { name: asset.name, exact: true }).first()).toHaveAttribute('href', asset.path);
  return { ...log, name };
}

export async function assertViewerAccess(page, browser, asset, bundle, denied = []) {
  const credentials = await createViewer(page, 'contrib-viewer');
  const context = await browser.newContext({ baseURL: new URL(page.url()).origin });
  try {
    const viewer = await context.newPage();
    await login(viewer, credentials);
    await viewer.goto(asset.path);
    await expect(viewer.getByRole('heading', { name: asset.name, exact: true })).toBeVisible();
    const { record } = await apiRecord(viewer, 'asset', bundle, asset.name);
    for (const path of [`${asset.path}/edit`, `/asset/add/${bundle}`, ...denied]) {
      expect((await viewer.goto(path)).status(), path).toBe(403);
    }
    const token = await viewer.request.get('/session/token');
    const response = await viewer.request.patch(`/api/asset/${bundle}/${record.id}`, {
      headers: { 'Content-Type': 'application/vnd.api+json', 'X-CSRF-Token': await token.text() },
      data: { data: { type: record.type, id: record.id, attributes: { name: 'Forbidden change' } } },
    });
    expect(response.status()).toBe(403);
    expect((await apiRecord(page, 'asset', bundle, asset.name)).record.attributes.name).toBe(asset.name);
  } finally {
    await context.close();
  }
}

export async function exportAsset(page, asset, expectedValues) {
  await page.goto('/assets');
  if (!(await page.locator('[name="name"]').isVisible())) await page.getByRole('button', { name: 'Filter', exact: true }).click();
  await page.locator('[name="name"]').fill(asset.name);
  await page.getByRole('button', { name: 'Apply', exact: true }).click();
  await page.getByRole('row').filter({ has: page.getByRole('link', { name: asset.name, exact: true }) }).getByRole('checkbox').check();
  await page.getByRole('combobox', { name: 'Action:', exact: true }).selectOption({ label: 'Export CSV' });
  await page.getByRole('button', { name: 'Apply to selected items', exact: true }).click();
  await page.getByRole('button', { name: 'Export', exact: true }).click();
  const link = page.getByRole('link', { name: /^csv_export-.*\.csv$/ });
  await expect(link).toBeVisible();
  const response = await page.request.get(await link.getAttribute('href'));
  expect(response.status()).toBe(200);
  for (const value of [asset.name, ...expectedValues]) expect(await response.text()).toContain(value);
}
