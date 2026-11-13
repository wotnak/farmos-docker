import { test, expect } from '@playwright/test';
import { login, uniqueName, createAsset, selectAutocomplete } from '../../support/farmos.js';

async function saveStream(page) {
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page).toHaveURL(/\/data_stream\/\d+$/);
  return { path: new URL(page.url()).pathname };
}

test('sensor data streams enforce keys, store measurements, filter readings, and allow public reads only', async ({ page, request }) => {
  await login(page);
  const sensor = await createAsset(page, { type: 'sensor', name: uniqueName('Weather station') });
  const name = uniqueName('Temperature');
  await page.goto('/data_stream/add/basic');
  await page.locator('input[name="name[0][value]"]').fill(name);
  const key = await page.locator('input[name="private_key[0][value]"]').inputValue();
  expect(key.length).toBeGreaterThan(20);
  await page.locator('input[name="public[value]"]').uncheck();
  await selectAutocomplete(page, 'asset[0][target_id]', sensor.name);
  const stream = await saveStream(page);
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();

  const lookup = await page.request.get('/api/data_stream/basic', { params: { 'filter[name]': name } });
  expect(lookup.status()).toBe(200);
  const entities = (await lookup.json()).data;
  expect(entities).toHaveLength(1);
  const endpoint = `/api/data_stream/${entities[0].id}/data`;
  const timestamp = 1704067200;
  // PostgreSQL returns decimal readings and timestamps as numeric strings.
  const points = async response => (await response.json()).map(point => ({
    timestamp: Number(point.timestamp), [name]: Number(point[name]),
  }));
  expect((await request.get(endpoint)).status()).toBe(403);
  expect((await request.post(endpoint, { params: { private_key: 'invalid' }, data: { [name]: 999 } })).status()).toBe(403);
  const write = await request.post(endpoint, {
    params: { private_key: key },
    data: [{ timestamp, [name]: 18.25 }, { timestamp: timestamp + 60, [name]: 19.5 }],
  });
  expect(write.status()).toBe(201);
  const read = await request.get(endpoint, { params: { private_key: key } });
  expect(read.status()).toBe(200);
  expect(await points(read)).toEqual([
    { timestamp: timestamp + 60, [name]: 19.5 }, { timestamp, [name]: 18.25 },
  ]);
  const filtered = await request.get(endpoint, { params: { private_key: key, start: timestamp + 1 } });
  expect(await points(filtered)).toEqual([{ timestamp: timestamp + 60, [name]: 19.5 }]);

  await page.goto(`${stream.path}/edit`);
  await expect(page.locator('input[name="asset[0][target_id]"]')).toHaveValue(new RegExp(sensor.name));
  await page.locator('input[name="public[value]"]').check();
  await saveStream(page);
  const publicRead = await request.get(endpoint, { params: { limit: 1 } });
  expect(publicRead.status()).toBe(200);
  expect(await points(publicRead)).toEqual([{ timestamp: timestamp + 60, [name]: 19.5 }]);
  expect((await request.post(endpoint, { data: { [name]: 999 } })).status()).toBe(403);
  expect((await request.get(endpoint, { params: { limit: 100001 } })).status()).toBe(422);
  await page.goto(`${stream.path}/delete`);
  await page.getByRole('button', { name: 'Delete', exact: true }).click();
  expect((await request.get(endpoint)).status()).toBe(404);
});
