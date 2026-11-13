import { test, expect } from '@playwright/test';
import { login, uniqueName, createAsset, saveEntity, openTab } from '../../support/farmos.js';
import { apiRecord, createLocation, moveTo, assertViewerAccess } from '../../support/production-contrib.js';
import { rememberRecord } from '../../support/contrib.js';

test('egg quick form validates whole counts and records dated flock harvests with inherited locations', async ({ page, browser }) => {
  await login(page);
  const location = await createLocation(page, uniqueName('Layer pasture'));
  const flock = await createAsset(page, { type: 'group', name: uniqueName('Layer flock'), configure: async () => {
    await page.getByLabel('Produces eggs', { exact: true }).check();
  } });
  const excluded = await createAsset(page, { type: 'group', name: uniqueName('Nonlayer flock') });
  await moveTo(page, flock, location);
  const { record: flockApi } = await apiRecord(page, 'asset', 'group', flock.name);
  expect(flockApi.attributes.produces_eggs).toBe(true);
  const { record: locationApi } = await apiRecord(page, 'asset', 'land', location.name);

  for (const invalid of ['-1', '1.5', '']) {
    await page.goto('/quick/eggs');
    await expect(page.locator(`input[name="assets[${flock.id}]"]`)).toBeVisible();
    await expect(page.locator(`input[name="assets[${excluded.id}]"]`)).toHaveCount(0);
    await page.getByLabel('Quantity', { exact: true }).fill(invalid);
    // Bypass browser validation deliberately to exercise Drupal's server-side
    // required, minimum and integer-step constraints as well.
    await page.locator('form').filter({ has: page.locator('input[name="quantity"]') }).evaluate(form => { form.noValidate = true; });
    await page.getByRole('button', { name: 'Submit', exact: true }).click();
    await expect(page.getByRole('contentinfo', { name: 'Error message' })).toBeVisible();
    await expect(page.locator('[data-drupal-messages]')).not.toContainText('Log created');
  }

  const logs = [];
  for (const [date, amount] of [['2024-03-04', '23'], ['2024-03-05', '29']]) {
    await page.goto('/quick/eggs');
    await page.locator('input[name="date[date]"]').fill(date);
    await page.locator('input[name="date[time]"]').fill('08:30:00');
    await page.getByLabel('Quantity', { exact: true }).fill(amount);
    // Other tests may have created layers; choose this scenario's flock only.
    for (const checkbox of await page.locator('input[name^="assets["]').all()) await checkbox.uncheck();
    await page.locator(`input[name="assets[${flock.id}]"]`).check();
    await page.getByRole('button', { name: 'Submit', exact: true }).click();
    const name = `Collected ${amount} egg(s)`;
    const link = page.locator('[data-drupal-messages]').getByRole('link', { name, exact: true });
    await expect(link).toBeVisible();
    const path = await link.getAttribute('href');
    await page.goto(path);
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
    await expect(page.locator('.field--name-quantity')).toContainText(`${amount}`);
    await expect(page.locator('.field--name-quantity')).toContainText('egg(s)');
    await expect(page.getByRole('link', { name: flock.name, exact: true }).first()).toHaveAttribute('href', flock.path);
    await expect(page.getByRole('link', { name: location.name, exact: true }).first()).toHaveAttribute('href', location.path);
    await page.goto(`${path}/edit`);
    await expect(page.locator('[name="timestamp[0][value][date]"]')).toHaveValue(date);
    await expect(page.locator('[name="status"]')).toHaveValue('done');
    // Give generated names a unique suffix for repeatable API and persistence checks.
    const unique = uniqueName(name);
    await page.locator('[name="name[0][value]"]').fill(unique);
    if (logs.length === 0) {
      await openTab(page, 'Quantity');
      await page.locator('#edit-quantity-wrapper').getByRole('button', { name: 'Edit', exact: true }).click();
      await page.getByLabel('Value', { exact: true }).fill('24');
      await page.getByRole('button', { name: 'Update quantity', exact: true }).click();
      await expect(page.getByRole('button', { name: 'Update quantity', exact: true })).toHaveCount(0);
      await expect(page.locator('#edit-quantity-wrapper')).toContainText('24');
    }
    await saveEntity(page, 'log');
    const { record, included } = await apiRecord(page, 'log', 'harvest', unique, 'quantity,quantity.units');
    const quantity = included.find(item => item.type === 'quantity--standard');
    expect(quantity.attributes.measure).toBe('count');
    expect(Number(quantity.attributes.value.decimal)).toBe(logs.length === 0 ? 24 : 29);
    expect(included.find(item => item.type === 'taxonomy_term--unit').attributes.name).toBe('egg(s)');
    expect(record.relationships.asset.data.map(item => item.id)).toEqual([flockApi.id]);
    expect(record.relationships.location.data.map(item => item.id)).toEqual([locationApi.id]);
    logs.push(record);
    rememberRecord('eggs', { path, name: unique, apiPath: `/api/log/harvest/${record.id}`,
      attributes: { status: 'done' }, relationships: { asset: flockApi.id, location: locationApi.id } });
    rememberRecord('eggs', { path, name: unique, apiPath: `/api/quantity/standard/${quantity.id}`, attributes: { measure: 'count', value: quantity.attributes.value } });
  }
  await assertViewerAccess(page, browser, flock, 'group', ['/quick/eggs']);
  await page.goto(`${flock.path}/edit`);
  await page.locator('[name="archived[value]"]').check();
  await saveEntity(page);
  await page.goto('/quick/eggs');
  await expect(page.locator(`input[name="assets[${flock.id}]"]`)).toHaveCount(0);
  rememberRecord('eggs', { path: flock.path, name: flock.name, apiPath: `/api/asset/group/${flockApi.id}`, attributes: { archived: true, produces_eggs: true } });
});
