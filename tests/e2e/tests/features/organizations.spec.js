import { test, expect } from '@playwright/test';
import { login, uniqueName, fillEntityBasics, saveEntity, createAsset, selectAutocomplete, openTab } from '../../support/farmos.js';

async function createFarm(page, name, notes) {
  await page.goto('/organization/add/farm');
  await fillEntityBasics(page, { name, notes });
  const farm = await saveEntity(page, 'organization');
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  return { ...farm, name };
}

test.beforeEach(async ({ page }) => login(page));

test('farm organization lifecycle and asset association', async ({ page }) => {
  const name = uniqueName('Browser farm');
  const notes = `Farm organization notes for ${name}`;
  const farm = await createFarm(page, name, notes);
  await expect(page.getByText(notes, { exact: true })).toBeVisible();
  await page.goto('/organization/add/farm');
  await fillEntityBasics(page, { name });
  await page.locator('#gin-sticky-edit-submit').click();
  await expect(page.getByRole('contentinfo', { name: 'Error message' })).toContainText('already exists');

  const asset = await createAsset(page, { name: uniqueName('Farm tractor'), configure: async () => {
    await selectAutocomplete(page, 'farm[0][target_id]', farm.name);
  } });
  await expect(page.locator('main').getByRole('link', { name: farm.name, exact: true })).toBeVisible();
  await page.goto(`${asset.path}/edit`);
  await expect(page.locator('[name="farm[0][target_id]"]')).toHaveValue(new RegExp(farm.name));

  const editedName = `${name} renamed`;
  await page.goto(`${farm.path}/edit`);
  await fillEntityBasics(page, { name: editedName, notes: `Updated ${notes}` });
  await page.locator('[name="archived[value]"]').check();
  await saveEntity(page, 'organization');
  await expect(page.getByRole('heading', { name: editedName, exact: true })).toBeVisible();
  await expect(page.getByText(`Updated ${notes}`, { exact: true })).toBeVisible();
  await page.goto(`${farm.path}/edit`);
  await expect(page.locator('[name="archived[value]"]')).toBeChecked();
  await page.goto(asset.path);
  await expect(page.locator('main').getByRole('link', { name: editedName, exact: true })).toHaveAttribute('href', farm.path);

  // Remove the referencing record before deleting its organization.
  for (const record of [asset, farm]) {
    await page.goto(`${record.path}/delete`);
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    expect((await page.goto(record.path)).status()).toBe(404);
  }
});

test('parent relationships cannot cross farm organizations', async ({ page }) => {
  const first = await createFarm(page, uniqueName('First farm'));
  const second = await createFarm(page, uniqueName('Second farm'));
  const parent = await createAsset(page, { name: uniqueName('First farm parent'), configure: async () => {
    await selectAutocomplete(page, 'farm[0][target_id]', first.name);
  } });
  await page.goto('/asset/add/equipment');
  const childName = uniqueName('Second farm child');
  await fillEntityBasics(page, { name: childName });
  await selectAutocomplete(page, 'farm[0][target_id]', second.name);
  await openTab(page, 'Parents');
  await selectAutocomplete(page, 'parent[0][target_id]', parent.name);
  await page.locator('#gin-sticky-edit-submit').click();
  await expect(page.getByRole('contentinfo', { name: 'Error message' }))
    .toContainText('Assets must be in the same farm as their parents.');
  await expect(page).toHaveURL(/\/asset\/add\/equipment$/);
  await selectAutocomplete(page, 'farm[0][target_id]', first.name);
  const child = await saveEntity(page);
  await expect(page.getByRole('heading', { name: childName, exact: true })).toBeVisible();
  await expect(page.locator('main').getByRole('link', { name: parent.name, exact: true })).toBeVisible();
  await page.goto(`${child.path}/edit`);
  await expect(page.locator('[name="farm[0][target_id]"]')).toHaveValue(new RegExp(first.name));
});
