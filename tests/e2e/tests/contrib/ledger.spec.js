import { test, expect } from '@playwright/test';
import { login, uniqueName, createAsset, fillEntityBasics, saveEntity, openTab } from '../../support/farmos.js';
import { createViewer } from '../../support/contrib-accounts.js';
import { rememberRecord } from '../../support/contrib.js';

const fractionValue = value => Number(value.numerator) / Number(value.denominator);

async function priceForm(page, values) {
  await openTab(page, 'Quantity');
  await page.locator('select[name="quantity[actions][bundle]"]').selectOption('price');
  await page.getByRole('button', { name: 'Add new quantity', exact: true }).click();
  await page.getByLabel('Measure', { exact: true }).selectOption('count');
  for (const [label, value] of Object.entries(values)) await page.getByLabel(label, { exact: true }).fill(value);
}

async function loadLedger(page, type, name) {
  const response = await page.request.get(`/api/log/${type}`, {
    params: { 'filter[name]': name, include: 'quantity,quantity.units,asset' },
  });
  expect(response.status()).toBe(200);
  const document = await response.json();
  expect(document.data).toHaveLength(1);
  const quantity = document.included.find(record => record.type === 'quantity--price');
  expect(quantity).toBeDefined();
  return { log: document.data[0], quantity, included: document.included };
}

test.beforeEach(async ({ page }) => login(page));

for (const [type, party, currency] of [['purchase', 'Seller', 'USD'], ['sale', 'Customer', 'EUR']]) {
  test(`${type} logs calculate decimal prices, retain edits and expose API and CSV records`, async ({ page }) => {
    const asset = await createAsset(page, { name: uniqueName(`${type} equipment`) });
    const name = uniqueName(`${type} ledger`);
    const invoice = uniqueName('Invoice');
    const lot = uniqueName('Lot');
    const counterparty = uniqueName(party);
    await page.goto(`/log/add/${type}?asset=${asset.id}`);
    await fillEntityBasics(page, { name, notes: 'Browser ledger transaction' });
    await page.getByLabel(party, { exact: true }).fill(counterparty);
    await page.getByLabel('Invoice number', { exact: true }).fill(invoice);
    await page.getByLabel('Lot number', { exact: true }).fill(lot);
    await page.getByLabel('Status', { exact: true }).selectOption('done');
    await priceForm(page, { Value: '2.5', 'Unit price': '12.4', Units: currency, Label: 'Invoice line' });
    await page.getByRole('button', { name: 'Create quantity', exact: true }).click();
    await expect(page.locator('#edit-quantity-wrapper')).toContainText('2.5');
    const record = await saveEntity(page, 'log');
    await expect(page.getByText(counterparty, { exact: true })).toBeVisible();
    await expect(page.getByText(invoice, { exact: true })).toBeVisible();
    await expect(page.locator('.field--name-quantity')).toContainText('31');
    let api = await loadLedger(page, type, name);
    expect(fractionValue(api.quantity.attributes.unit_price)).toBe(12.4);
    expect(fractionValue(api.quantity.attributes.total_price)).toBe(31);
    expect(api.log.attributes.invoice_number).toBe(invoice);
    expect(api.log.attributes.lot_number).toBe(lot);
    expect(api.log.attributes[party.toLowerCase()]).toBe(counterparty);
    expect(api.included.some(item => item.type === 'taxonomy_term--unit' && item.attributes.name === currency)).toBe(true);
    const assetUuid = api.included.find(item => item.type === 'asset--equipment').id;
    expect(api.log.relationships.asset.data.map(reference => reference.id)).toContain(assetUuid);

    await page.goto(`${record.path}/edit`);
    await page.getByLabel('Invoice number', { exact: true }).fill(`${invoice} amended`);
    await openTab(page, 'Quantity');
    await page.locator('#edit-quantity-wrapper').getByRole('button', { name: 'Edit', exact: true }).click();
    await expect(page.getByLabel('Unit price', { exact: true })).toHaveValue('12.4');
    await expect(page.getByLabel('Total price', { exact: true })).toHaveValue('31');
    await page.getByLabel('Value', { exact: true }).fill('3');
    await page.getByLabel('Total price', { exact: true }).fill('');
    await page.getByRole('button', { name: 'Update quantity', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Update quantity', exact: true })).toHaveCount(0);
    await saveEntity(page, 'log');
    api = await loadLedger(page, type, name);
    expect(fractionValue(api.quantity.attributes.total_price)).toBe(37.2);
    expect(api.log.attributes.invoice_number).toBe(`${invoice} amended`);

    await page.goto('/logs');
    await page.getByRole('button', { name: 'Filter', exact: true }).click();
    await page.locator('input[name="name"]').fill(name);
    await page.locator('select[name="type[]"]').selectOption(type);
    await page.getByRole('button', { name: 'Apply', exact: true }).click();
    const row = page.getByRole('row').filter({ has: page.getByRole('link', { name, exact: true }) });
    await expect(row).toHaveCount(1);
    await row.getByRole('checkbox').check();
    await page.getByRole('combobox', { name: 'Action:', exact: true }).selectOption({ label: 'Export CSV' });
    await page.getByRole('button', { name: 'Apply to selected items', exact: true }).click();
    await page.getByRole('button', { name: 'Export', exact: true }).click();
    const csv = page.getByRole('link', { name: /^csv_export-.*\.csv$/ });
    await expect(csv).toBeVisible();
    const download = await page.request.get(await csv.getAttribute('href'));
    expect(download.status()).toBe(200);
    const contents = await download.text();
    for (const value of [name, `${invoice} amended`, counterparty, lot]) expect(contents).toContain(value);
    rememberRecord('ledger', { ...record, name, apiPath: `/api/log/${type}/${api.log.id}`,
      attributes: { invoice_number: `${invoice} amended`, lot_number: lot }, relationships: { asset: assetUuid } });
    rememberRecord('ledger', { ...record, name, apiPath: `/api/quantity/price/${api.quantity.id}`,
      attributes: { value: api.quantity.attributes.value, unit_price: api.quantity.attributes.unit_price, total_price: api.quantity.attributes.total_price } });
  });
}

test('price quantities reject inconsistent totals and calculate missing unit price and count', async ({ page }) => {
  await page.goto('/log/add/purchase');
  const name = uniqueName('Ledger validation');
  await fillEntityBasics(page, { name });
  await priceForm(page, { Value: '2', 'Unit price': '5', 'Total price': '99' });
  await page.getByRole('button', { name: 'Create quantity', exact: true }).click();
  await expect(page.locator('.messages--error')).toContainText('The total price must be equal to the unit price multiplied by quantity value.');
  await page.getByLabel('Unit price', { exact: true }).fill('');
  await page.getByLabel('Total price', { exact: true }).fill('10');
  await page.getByRole('button', { name: 'Create quantity', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Create quantity', exact: true })).toHaveCount(0);
  await expect(page.locator('#edit-quantity-wrapper')).toContainText('2');
  const record = await saveEntity(page, 'log');
  let api = await loadLedger(page, 'purchase', name);
  expect(fractionValue(api.quantity.attributes.unit_price)).toBe(5);
  await page.goto(`${record.path}/edit`);
  await openTab(page, 'Quantity');
  await page.locator('#edit-quantity-wrapper').getByRole('button', { name: 'Edit', exact: true }).click();
  await page.getByLabel('Value', { exact: true }).fill('');
  await page.getByLabel('Total price', { exact: true }).fill('15');
  await page.getByRole('button', { name: 'Update quantity', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Update quantity', exact: true })).toHaveCount(0);
  await saveEntity(page, 'log');
  api = await loadLedger(page, 'purchase', name);
  expect(fractionValue(api.quantity.attributes.value)).toBe(3);
});

test('Viewer can read Ledger records but cannot create or change transactions', async ({ page, browser }) => {
  await page.goto('/log/add/sale');
  const name = uniqueName('Viewer ledger sale');
  await fillEntityBasics(page, { name });
  const record = await saveEntity(page, 'log');
  const credentials = await createViewer(page, 'ledger-viewer');
  const context = await browser.newContext({ baseURL: new URL(page.url()).origin });
  try {
    const viewer = await context.newPage();
    await login(viewer, credentials);
    await viewer.goto(record.path);
    await expect(viewer.getByRole('heading', { name, exact: true })).toBeVisible();
    for (const url of ['/log/add/purchase', '/log/add/sale', `${record.path}/edit`, `${record.path}/delete`]) {
      expect((await viewer.goto(url)).status()).toBe(403);
    }
    const result = await viewer.request.get('/api/log/sale', { params: { 'filter[name]': name } });
    expect(result.status()).toBe(200);
    const [resource] = (await result.json()).data;
    const token = await viewer.request.get('/session/token');
    const denied = await viewer.request.patch(`/api/log/sale/${resource.id}`, {
      headers: { 'Content-Type': 'application/vnd.api+json', 'X-CSRF-Token': await token.text() },
      data: { data: { type: 'log--sale', id: resource.id, attributes: { name: 'Forbidden sale change' } } },
    });
    expect(denied.status()).toBe(403);
  } finally {
    await context.close();
  }
});
