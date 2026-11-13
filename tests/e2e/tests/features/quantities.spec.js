import { test, expect } from '@playwright/test';
import { login, uniqueName, createAsset, fillEntityBasics, saveEntity, openTab, selectAutocomplete } from '../../support/farmos.js';

test.beforeEach(async ({ page }) => login(page));

for (const [type, logType, extraLabel] of [
  ['standard', 'harvest', null],
  ['material', 'input', 'Material type'],
  ['test', 'lab_test', 'Test method'],
]) {
  test(`${type} quantities preserve decimal measurements, units and edits`, async ({ page }) => {
    const name = uniqueName(`${type} measurement`);
    const units = uniqueName('kg');
    const label = uniqueName('Measured sample');
    const extra = uniqueName(type === 'material' ? 'Compost' : 'Laboratory method');
    await page.goto(`/log/add/${logType}`);
    await fillEntityBasics(page, { name });
    await openTab(page, 'Quantity');
    await page.locator('select[name="quantity[actions][bundle]"]').selectOption(type);
    await page.getByRole('button', { name: 'Add new quantity', exact: true }).click();
    await page.getByLabel('Measure', { exact: true }).selectOption('weight');
    await page.getByLabel('Value', { exact: true }).fill('12.5');
    await page.getByLabel('Units', { exact: true }).fill(units);
    await page.getByLabel('Label', { exact: true }).fill(label);
    if (extraLabel) await page.getByLabel(type === 'material' ? 'Material type (value 1)' : extraLabel, { exact: true }).fill(extra);
    await page.getByRole('button', { name: 'Create quantity', exact: true }).click();
    await expect(page.locator('#edit-quantity-wrapper')).toContainText('12.5');
    const log = await saveEntity(page, 'log');
    await expect(page.getByText(label, { exact: true })).toBeVisible();
    await expect(page.getByText(units, { exact: true })).toBeVisible();
    if (extraLabel) await expect(page.getByText(extra, { exact: true })).toBeVisible();

    await page.goto(`${log.path}/edit`);
    await openTab(page, 'Quantity');
    await page.locator('#edit-quantity-wrapper').getByRole('button', { name: 'Edit', exact: true }).click();
    await expect(page.getByLabel('Value', { exact: true })).toHaveValue('12.5');
    await expect(page.getByLabel('Units', { exact: true })).toHaveValue(new RegExp(units));
    await expect(page.getByLabel('Measure', { exact: true })).toHaveValue('weight');
    await page.getByLabel('Value', { exact: true }).fill('18.75');
    await page.getByRole('button', { name: 'Update quantity', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Update quantity', exact: true })).toHaveCount(0);
    await expect(page.locator('#edit-quantity-wrapper')).toContainText('18.75');
    await saveEntity(page, 'log');
    await expect(page.locator('.field--name-quantity')).toContainText('18.75');
    await expect(page.locator('.field--name-quantity')).not.toContainText('12.5');
    await page.goto(`${log.path}/edit`);
    await openTab(page, 'Quantity');
    await page.locator('#edit-quantity-wrapper').getByRole('button', { name: 'Remove', exact: true }).click();
    await page.locator('input[name^="ief-remove-confirm-quantity-form-"]').click();
    await expect(page.locator('#edit-quantity-wrapper')).not.toContainText(label);
    await saveEntity(page, 'log');
    await expect(page.locator('.field--name-quantity')).toHaveCount(0);
  });
}

test('inventory quick form applies reset, increment and decrement only when completed', async ({ page }) => {
  const asset = await createAsset(page, { name: uniqueName('Inventory bin') });
  const units = uniqueName('crates');
  let pending;
  for (const [adjustment, amount, completed, expected, date] of [
    ['reset', '20', true, '20', '2024-01-01'],
    ['increment', '5', true, '25', '2024-01-02'],
    ['decrement', '3', true, '22', '2024-01-03'],
    ['increment', '7', false, '22', '2024-01-04'],
  ]) {
    await page.goto('/quick/inventory');
    await selectAutocomplete(page, 'asset', asset.name);
    await page.locator('input[name="date[date]"]').fill(date);
    await page.locator('input[name="quantity[value]"]').fill(amount);
    await page.locator('input[name="quantity[units]"]').fill(units);
    await page.locator('select[name="quantity[measure]"]').selectOption('count');
    await page.locator('select[name="inventory_adjustment"]').selectOption(adjustment);
    await page.getByLabel('Completed', { exact: true }).setChecked(completed);
    await page.getByRole('button', { name: 'Submit', exact: true }).click();
    const message = page.locator('[data-drupal-messages]').getByRole('link').filter({ hasText: asset.name });
    await expect(message).toBeVisible();
    const path = await message.getAttribute('href');
    if (!completed) pending = path;
    await page.goto(asset.path);
    await expect(page.locator('.field--name-inventory .field__item')).toHaveText(`${expected} ${units} (Count)`);
  }
  await page.goto(`${pending}/edit`);
  await page.getByLabel('Status', { exact: true }).selectOption('done');
  await saveEntity(page, 'log');
  await page.goto(asset.path);
  await expect(page.locator('.field--name-inventory .field__item')).toHaveText(`29 ${units} (Count)`);
  // Abandoning the adjustment removes its effect from computed inventory.
  await page.goto(`${pending}/edit`);
  await page.getByLabel('Status', { exact: true }).selectOption('abandoned');
  await saveEntity(page, 'log');
  await page.goto(asset.path);
  await expect(page.locator('.field--name-inventory .field__item')).toHaveText(`22 ${units} (Count)`);
});
