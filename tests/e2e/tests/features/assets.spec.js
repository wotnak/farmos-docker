import { test, expect } from '@playwright/test';
import { login, uniqueName, createAsset, openTab, fillEntityBasics, saveEntity, selectAutocomplete, username } from '../../support/farmos.js';

const types = ['animal', 'compost', 'equipment', 'group', 'land', 'material', 'plant', 'product', 'seed', 'sensor', 'structure', 'water'];
const taxonomyFields = { animal: 'animal_type', equipment: 'equipment_type', material: 'material_type', plant: 'plant_type', product: 'product_type', seed: 'plant_type' };

test.beforeEach(async ({ page }) => login(page));

for (const type of types) {
  test(`${type}: create, read, edit, archive and delete an asset`, async ({ page }) => {
    const name = uniqueName(`Lifecycle ${type}`);
    const category = uniqueName(`${type} category`);
    const notes = `Original browser notes for ${name}`;
    const asset = await createAsset(page, { type, name, notes, configure: async () => {
      if (taxonomyFields[type]) await page.locator(`[name="${taxonomyFields[type]}[0][target_id]"]`).fill(category);
      if (type === 'land') await page.locator('[name="land_type"][value="field"]').check();
      if (type === 'structure') await page.locator('[name="structure_type"][value="greenhouse"]').check();
      if (type === 'equipment') {
        await page.getByLabel('Manufacturer', { exact: true }).fill('Browser machinery');
        await page.getByLabel('Model', { exact: true }).fill('Model 42');
        await page.getByLabel('Serial number', { exact: true }).fill('E2E-0042');
        await page.locator('[name="flag[priority]"]').check();
        await page.locator('[name="owner[]"]').selectOption({ label: username });
      }
      if (type === 'animal') {
        await page.locator('[name="sex"][value="F"]').check();
        await page.locator('[name="nickname[0][value]"]').fill('Clover');
        await page.locator('[name="is_sterile[value]"]').check();
      }
      if (['plant', 'seed'].includes(type)) await page.locator('[name="season[0][target_id]"]').fill('Browser season');
      if (type === 'sensor') await page.locator('[name="private_key[0][value]"]').fill('browser-test-sensor-key');
    } });
    await expect(page.getByText(notes, { exact: true })).toBeVisible();
    if (taxonomyFields[type]) await expect(page.locator('main')).toContainText(category);

    await page.goto(`${asset.path}/edit`);
    if (taxonomyFields[type]) await expect(page.locator(`[name="${taxonomyFields[type]}[0][target_id]"]`)).toHaveValue(new RegExp(category));
    if (type === 'equipment') {
      await expect(page.getByLabel('Manufacturer', { exact: true })).toHaveValue('Browser machinery');
      await expect(page.getByLabel('Model', { exact: true })).toHaveValue('Model 42');
      await expect(page.getByLabel('Serial number', { exact: true })).toHaveValue('E2E-0042');
      await expect(page.locator('[name="flag[priority]"]')).toBeChecked();
      await expect(page.locator('[name="owner[]"] option:checked')).toHaveText(username);
    }
    if (type === 'animal') {
      await expect(page.locator('[name="sex"][value="F"]')).toBeChecked();
      await expect(page.locator('[name="nickname[0][value]"]')).toHaveValue('Clover');
      await expect(page.locator('[name="is_sterile[value]"]')).toBeChecked();
    }
    if (['plant', 'seed'].includes(type)) await expect(page.locator('[name="season[0][target_id]"]')).toHaveValue(/Browser season/);
    if (type === 'land') await expect(page.locator('[name="land_type"][value="field"]')).toBeChecked();
    if (type === 'structure') await expect(page.locator('[name="structure_type"][value="greenhouse"]')).toBeChecked();
    if (type === 'sensor') await expect(page.locator('[name="private_key[0][value]"]')).toHaveValue('browser-test-sensor-key');
    await fillEntityBasics(page, { name: `${name} edited`, notes: `Edited ${notes}` });
    await page.locator('[name="archived[value]"]').check();
    await saveEntity(page);
    await expect(page.getByRole('heading', { name: `${name} edited`, exact: true })).toBeVisible();
    await expect(page.getByText(`Edited ${notes}`, { exact: true })).toBeVisible();
    await page.goto(`${asset.path}/edit`);
    await expect(page.locator('[name="archived[value]"]')).toBeChecked();
    await page.goto(`${asset.path}/delete`);
    await page.getByRole('button', { name: 'Delete', exact: true }).click();
    const response = await page.goto(asset.path);
    expect(response.status()).toBe(404);
  });
}

test('asset parents persist and circular relationships are rejected', async ({ page }) => {
  const parent = await createAsset(page, { name: uniqueName('Parent tractor') });
  const child = await createAsset(page, { name: uniqueName('Child implement'), configure: async () => {
    await openTab(page, 'Parents');
    await selectAutocomplete(page, 'parent[0][target_id]', parent.name);
  } });
  await expect(page.locator('main').getByRole('link', { name: parent.name, exact: true })).toBeVisible();
  await page.goto(`${child.path}/edit`);
  await openTab(page, 'Parents');
  await expect(page.locator('[name="parent[0][target_id]"]')).toHaveValue(new RegExp(parent.name));
  await page.goto(`${parent.path}/edit`);
  await openTab(page, 'Parents');
  await selectAutocomplete(page, 'parent[0][target_id]', child.name);
  await page.locator('#gin-sticky-edit-submit').click();
  await expect(page.getByRole('contentinfo', { name: 'Error message' })).toContainText('cannot be referenced');
  await expect(page).toHaveURL(`${parent.path}/edit`);
});

test('location geometry and identification tags survive saving', async ({ page }) => {
  const asset = await createAsset(page, { type: 'land', name: uniqueName('Mapped field'), configure: async () => {
    await page.locator('[name="land_type"][value="field"]').check();
    await openTab(page, 'Location');
    await expect(page.locator('[name="is_location[value]"]')).toBeChecked();
    await expect(page.locator('[name="is_fixed[value]"]')).toBeChecked();
    await page.locator('[name="intrinsic_geometry[0][value]"]').fill('POINT (19.94 50.06)');
    await openTab(page, 'ID Tags');
    await page.locator('[name="id_tag[0][id]"]').fill('FIELD-42');
    await page.locator('[name="id_tag[0][type]"]').selectOption({ label: 'Other' });
    await page.locator('[name="id_tag[0][location]"]').fill('North gate');
  } });
  await expect(page.locator('main')).toContainText('FIELD-42');
  await expect(page.locator('canvas').first()).toBeVisible();
  await page.goto(`${asset.path}/edit`);
  await openTab(page, 'Location');
  await expect(page.locator('[name="intrinsic_geometry[0][value]"]')).toHaveValue('POINT (19.94 50.06)');
  await openTab(page, 'ID Tags');
  await expect(page.locator('[name="id_tag[0][id]"]')).toHaveValue('FIELD-42');
  await expect(page.locator('[name="id_tag[0][location]"]')).toHaveValue('North gate');
});

test('private attachments and image styles enforce access while public CSS remains readable', async ({ page, browser }) => {
  const filename = `${uniqueName('attachment').replaceAll(' ', '-')}.txt`;
  const imageName = `${uniqueName('field-photo').replaceAll(' ', '-')}.png`;
  const contents = 'Private farm attachment: browser acceptance';
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=', 'base64');
  const asset = await createAsset(page, { name: uniqueName('Attachment equipment'), configure: async () => {
    await openTab(page, 'Files');
    await expect(page.locator('input[name="files[file_0][]"]')).toHaveAttribute('data-once', /auto-file-upload/);
    await page.locator('input[name="files[file_0][]"]').setInputFiles({ name: filename, mimeType: 'text/plain', buffer: Buffer.from(contents) });
    await expect(page.getByRole('link', { name: filename, exact: true })).toBeVisible();
    await expect(page.locator('.ajax-progress')).toHaveCount(0);
    await expect(page.locator('input[name="files[image_0][]"]')).toBeEnabled();
    await expect(page.locator('input[name="files[image_0][]"]')).toHaveAttribute('data-once', /auto-file-upload/);
    await page.locator('input[name="files[image_0][]"]').setInputFiles({ name: imageName, mimeType: 'image/png', buffer: png });
    await expect(page.getByRole('link', { name: imageName, exact: true })).toBeVisible();
    await expect(page.locator('.ajax-progress')).toHaveCount(0);
  } });
  const link = page.getByRole('link', { name: filename, exact: true });
  const privateUrl = await link.getAttribute('href');
  expect(privateUrl).toContain('/system/files/');
  const download = await page.request.get(privateUrl);
  expect(download.status()).toBe(200);
  expect(await download.text()).toBe(contents);
  const image = page.locator('main img[src*="field-photo"]');
  await expect(image).toBeVisible();
  const imageUrl = await image.getAttribute('src');
  expect(imageUrl).toContain('/system/files/styles/');
  const derivative = await page.request.get(imageUrl);
  expect(derivative.status()).toBe(200);
  expect(derivative.headers()['content-type']).toMatch(/^image\//);
  await expect(image).toHaveJSProperty('naturalWidth', 1);
  // Standard farmOS stores both attachment fields privately. Aggregated CSS exercises public storage.
  const publicUrl = await page.locator('link[rel="stylesheet"][href*="/sites/default/files/"]').first().getAttribute('href');
  const anonymous = await browser.newContext();
  const anon = await anonymous.newPage();
  expect((await anon.request.get(new URL(publicUrl, page.url()).href)).status()).toBe(200);
  expect((await anon.request.get(new URL(imageUrl, page.url()).href)).status()).toBe(403);
  expect((await anon.request.get(new URL(privateUrl, page.url()).href)).status()).toBe(403);
  await anonymous.close();
  await page.goto(`${asset.path}/edit`);
  await openTab(page, 'Files');
  await expect(page.getByRole('link', { name: filename, exact: true })).toBeVisible();
});

test('asset list filters and bulk clone, archive and unarchive actions', async ({ page }) => {
  const name = uniqueName('Bulk equipment');
  const notes = `Cloned notes for ${name}`;
  const original = await createAsset(page, { name, notes });
  await page.goto('/assets');
  const filter = async archived => {
    if (!(await page.locator('input[name="name"]').isVisible())) await page.getByRole('button', { name: 'Filter', exact: true }).click();
    await page.locator('input[name="name"]').fill(name);
    await page.locator('select[name="type[]"]').selectOption('equipment');
    await page.locator('select[name="archived"]').selectOption(archived);
    await page.getByRole('button', { name: 'Apply', exact: true }).click();
  };
  const row = label => page.locator('table tbody tr').filter({ has: page.getByRole('link', { name: label, exact: true }) });
  const apply = async label => {
    await page.locator('select[name="action"]').selectOption({ label });
    await page.getByRole('button', { name: 'Apply to selected items', exact: true }).click();
  };
  await filter('0');
  await expect(row(name)).toHaveCount(1);
  await row(name).getByRole('checkbox').check();
  await apply('Clone asset');
  const cloneName = `${name} (clone of asset #${original.id})`;
  await expect(row(cloneName)).toHaveCount(1);
  const clonePath = await row(cloneName).getByRole('link', { name: cloneName, exact: true }).getAttribute('href');
  expect(clonePath).not.toBe(original.path);
  await page.goto(clonePath);
  await expect(page.getByText(notes, { exact: true })).toBeVisible();

  await page.goto('/assets');
  await filter('0');
  for (const label of [name, cloneName]) await row(label).getByRole('checkbox').check();
  await apply('Archive asset');
  await expect(row(name)).toHaveCount(0);
  await expect(row(cloneName)).toHaveCount(0);
  await filter('1');
  for (const label of [name, cloneName]) {
    await expect(row(label)).toHaveCount(1);
    await row(label).getByRole('checkbox').check();
  }
  await apply('Unarchive asset');
  await expect(row(name)).toHaveCount(0);
  await filter('0');
  await expect(row(name)).toHaveCount(1);
  await expect(row(cloneName)).toHaveCount(1);
});
