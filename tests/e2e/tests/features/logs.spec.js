import { test, expect } from '@playwright/test';
import { login, uniqueName, fillEntityBasics, saveEntity, createAsset, openTab, selectAutocomplete, username } from '../../support/farmos.js';

// farmOS 4.0's standard log bundles, including optional base modules enabled by
// the installation test. Each case persists a record, revises it, then deletes it.
const logTypes = ['activity', 'birth', 'harvest', 'input', 'lab_test', 'maintenance', 'medical', 'observation', 'seeding', 'transplanting'];
const bundleFields = {
  birth: ['Veterinarian'], harvest: ['Lot number'],
  input: ['Lot number', 'Method', 'Source'], lab_test: ['Soil texture', 'Laboratory'],
  medical: ['Veterinarian'], seeding: ['Lot number', 'Source'],
};

test.beforeEach(async ({ page }) => login(page));

for (const type of logTypes) {
  test(`${type} logs retain edits, dates and workflow status and can be deleted`, async ({ page }) => {
    const name = uniqueName(`${type} record`);
    const notes = `Created through the ${type} form.`;
    await page.goto(`/log/add/${type}`);
    await fillEntityBasics(page, { name, notes });
    if (type === 'lab_test') await page.getByRole('radio', { name: 'Soil test', exact: true }).check();
    const fieldValues = (bundleFields[type] || []).map(label => [label, uniqueName(label)]);
    for (const [label, value] of fieldValues) await page.getByLabel(label, { exact: true }).fill(value);
    const dateFields = type === 'lab_test' ? ['lab_received_date', 'lab_processed_date']
      : ['input', 'seeding'].includes(type) ? ['purchase_date'] : [];
    for (const field of dateFields) {
      await page.locator(`input[name="${field}[0][value][date]"]`).fill('2024-04-10');
      await page.locator(`input[name="${field}[0][value][time]"]`).fill('08:15:00');
    }
    await page.getByLabel('Status', { exact: true }).selectOption('pending');
    await page.locator('input[name="timestamp[0][value][date]"]').fill('2024-04-12');
    await page.locator('input[name="timestamp[0][value][time]"]').fill('09:30:00');
    const log = await saveEntity(page, 'log');
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
    await expect(page.getByText(notes, { exact: true })).toBeVisible();
    for (const [, value] of fieldValues) await expect(page.getByText(value, { exact: true })).toBeVisible();

    await page.goto(`${log.path}/edit`);
    await expect(page.getByLabel('Status', { exact: true })).toHaveValue('pending');
    for (const [label, value] of fieldValues) await expect(page.getByLabel(label, { exact: true })).toHaveValue(new RegExp(value));
    for (const field of dateFields) {
      await expect(page.locator(`input[name="${field}[0][value][date]"]`)).toHaveValue('2024-04-10');
      await expect(page.locator(`input[name="${field}[0][value][time]"]`)).toHaveValue('08:15:00');
    }
    await expect(page.locator('input[name="timestamp[0][value][date]"]')).toHaveValue('2024-04-12');
    await expect(page.locator('input[name="timestamp[0][value][time]"]')).toHaveValue('09:30:00');
    await fillEntityBasics(page, { name: `${name} revised`, notes: `${notes} Revised and completed.` });
    await page.getByLabel('Status', { exact: true }).selectOption('done');
    await saveEntity(page, 'log');
    await expect(page.getByRole('heading', { name: `${name} revised`, exact: true })).toBeVisible();
    await expect(page.getByText(`${notes} Revised and completed.`, { exact: true })).toBeVisible();
    await page.goto(`${log.path}/edit`);
    await expect(page.getByLabel('Status', { exact: true })).toHaveValue('done');
    await page.goto(`${log.path}/delete`);
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    expect((await page.request.get(log.path)).status()).toBe(404);
  });
}

test('an assigned observation appears in its asset history and supports status transitions', async ({ page }) => {
  const asset = await createAsset(page, { name: uniqueName('Observed equipment') });
  const name = uniqueName('Assigned inspection');
  await page.goto(`/log/add/observation?asset=${asset.id}`);
  await fillEntityBasics(page, { name, notes: 'Inspect equipment before field work.' });
  await page.getByLabel('Status', { exact: true }).selectOption('pending');
  await page.locator('select[name="owner[]"]').selectOption({ label: username });
  await openTab(page, 'Assets');
  await expect(page.locator('#edit-asset-current')).toContainText(asset.name);
  const log = await saveEntity(page, 'log');
  await expect(page.getByRole('link', { name: asset.name, exact: true }).first()).toHaveAttribute('href', asset.path);
  await page.goto(`${log.path}/edit`);
  await expect(page.locator('select[name="owner[]"] option:checked')).toHaveText(username);
  await page.getByLabel('Status', { exact: true }).selectOption('done');
  await saveEntity(page, 'log');
  await page.goto(`${log.path}/edit`);
  await expect(page.getByLabel('Status', { exact: true })).toHaveValue('done');
  await page.goto(`${asset.path}/logs`);
  await expect(page.getByRole('link', { name, exact: true })).toBeVisible();
});

for (const [quick, field, assetType, computedField] of [
  ['movement', 'location', 'equipment', 'location'],
  ['group', 'group', 'group', 'group'],
]) {
  test(`${quick} quick form changes computed asset relationships only for completed logs`, async ({ page }) => {
    const asset = await createAsset(page, { name: uniqueName(`Member of ${quick}`) });
    const target = await createAsset(page, {
      type: assetType, name: uniqueName(`${quick} destination`),
      configure: quick === 'movement' ? async page => {
        await openTab(page, 'Location');
        await page.locator('input[name="is_location[value]"]').check();
      } : undefined,
    });
    await page.goto(`/quick/${quick}`);
    await page.locator('input[name="date[date]"]').fill('2024-02-01');
    await selectAutocomplete(page, 'asset', asset.name);
    await expect(page.locator('.ajax-progress')).toHaveCount(0);
    await selectAutocomplete(page, field, target.name);
    await expect(page.locator('.ajax-progress')).toHaveCount(0);
    await page.getByLabel('Completed', { exact: true }).uncheck();
    await page.getByRole('button', { name: 'Submit', exact: true }).click();
    const created = page.locator('[data-drupal-messages]').getByRole('link').filter({ hasText: asset.name });
    await expect(created).toBeVisible();
    const logPath = await created.getAttribute('href');
    await page.goto(asset.path);
    await expect(page.locator(`.field--name-${computedField}`).getByRole('link', { name: target.name, exact: true })).toHaveCount(0);
    await page.goto(`${logPath}/edit`);
    await page.getByLabel('Status', { exact: true }).selectOption('done');
    await saveEntity(page, 'log');
    await page.goto(asset.path);
    await expect(page.locator(`.field--name-${computedField}`).getByRole('link', { name: target.name, exact: true })).toHaveAttribute('href', target.path);

    // A later completed quick form with an empty destination clears membership.
    await page.goto(`/quick/${quick}`);
    await selectAutocomplete(page, 'asset', asset.name);
    await expect(page.locator('.ajax-progress')).toHaveCount(0);
    await page.locator('input[name="date[date]"]').fill('2024-02-02');
    await page.getByRole('button', { name: 'Submit', exact: true }).click();
    await expect(page.locator('[data-drupal-messages]')).toContainText('Log created');
    await page.goto(asset.path);
    await expect(page.locator(`.field--name-${computedField}`).getByRole('link', { name: target.name, exact: true })).toHaveCount(0);
  });
}

test('planting quick form creates one plant with seeding, transplanting and harvest records', async ({ page }) => {
  const location = await createAsset(page, { name: uniqueName('Planting bed'), configure: async page => {
    await openTab(page, 'Location');
    await page.locator('input[name="is_location[value]"]').check();
  } });
  const season = uniqueName('Growing season');
  const crop = uniqueName('Carrot');
  const plantName = `${season} ${location.name} ${crop}`;
  await page.goto('/quick/planting');
  await page.locator('input[name="seasons"]').fill(season);
  await page.locator('input[name="crops[0]"]').fill(crop);
  for (const type of ['transplanting', 'harvest']) {
    await page.locator(`input[name="log_types[${type}]"]`).check();
    await expect(page.locator(`input[name="${type}[date][date]"]`)).toBeAttached();
    await expect(page.locator('.ajax-progress')).toHaveCount(0);
  }
  for (const [type, amount] of [['seeding', '100'], ['transplanting', '80'], ['harvest', '65']]) {
    await openTab(page, type[0].toUpperCase() + type.slice(1));
    if (type !== 'harvest') await selectAutocomplete(page, `${type}[location]`, location.name);
    await page.locator(`input[name="${type}[quantity][value]"]`).fill(amount);
    await page.locator(`select[name="${type}[quantity][measure]"]`).selectOption('count');
    await page.locator(`input[name="${type}[done]"]`).check();
  }
  await page.getByRole('button', { name: 'Submit', exact: true }).click();
  const messages = page.locator('[data-drupal-messages]');
  await expect(messages.getByRole('link', { name: plantName, exact: true })).toBeVisible();
  const assetPath = await messages.getByRole('link', { name: plantName, exact: true }).getAttribute('href');
  const logs = await messages.locator('a[href^="/log/"]').evaluateAll(links => links.map(link => ({ path: link.getAttribute('href'), name: link.textContent })));
  expect(logs).toHaveLength(3);
  for (const log of logs) {
    await page.goto(log.path);
    await expect(page.getByRole('heading', { name: log.name, exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: plantName, exact: true }).first()).toHaveAttribute('href', assetPath);
    await expect(page.locator('.field--name-quantity')).toBeVisible();
  }
  await page.goto(assetPath);
  await expect(page.locator('.field--name-location')).toContainText(location.name);
});

test('birth quick form creates an animal with lineage and a birth-weight observation', async ({ page }) => {
  const mother = await createAsset(page, { type: 'animal', name: uniqueName('Mother animal'), configure: async page => {
    await page.getByLabel('Species/breed', { exact: true }).fill(uniqueName('Cattle'));
    await page.getByRole('radio', { name: 'Female', exact: true }).check();
  } });
  const child = uniqueName('Newborn animal');
  await page.goto('/quick/birth');
  await page.locator('input[name="children[0][name]"]').fill(child);
  await page.locator('input[name="children[0][sex]"][value="F"]').check();
  await page.locator('input[name="children[0][weight]"]').fill('32.5');
  await openTab(page, 'Lineage');
  await selectAutocomplete(page, 'birth_mother', mother.name);
  await selectAutocomplete(page, 'genetic_mother', mother.name);
  await page.getByRole('button', { name: 'Submit', exact: true }).click();
  const messages = page.locator('[data-drupal-messages]');
  const childLink = messages.getByRole('link', { name: child, exact: true });
  await expect(childLink).toBeVisible();
  const childPath = await childLink.getAttribute('href');
  const logs = await messages.locator('a[href^="/log/"]').evaluateAll(links => links.map(link => link.getAttribute('href')));
  expect(logs).toHaveLength(2);
  await page.goto(childPath);
  await expect(page.getByRole('heading', { name: child, exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: mother.name, exact: true }).first()).toBeVisible();
  let weightFound = false;
  for (const path of logs) {
    await page.goto(path);
    await expect(page.getByRole('link', { name: child, exact: true }).first()).toHaveAttribute('href', childPath);
    if (await page.locator('.field--name-quantity').count()) {
      await expect(page.locator('.field--name-quantity')).toContainText('32.5');
      weightFound = true;
    }
  }
  expect(weightFound).toBe(true);
});
