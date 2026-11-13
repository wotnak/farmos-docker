import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { login } from '../../support/farmos.js';

const mediaType = 'application/vnd.api+json';

// farm_api exposes Drupal JSON:API at /api and enables write operations.
// Authenticate through the same browser login/session used by farmOS users.
test('JSON:API enforces access and CSRF while creating, linking, filtering, updating and deleting records', async ({ page, request }) => {
  await login(page);
  const discovery = await page.request.get('/api', { headers: { Accept: mediaType } });
  expect(discovery.status()).toBe(200);
  expect((await discovery.json()).meta.farm.version).toBeTruthy();
  const tokenResponse = await page.request.get('/session/token');
  expect(tokenResponse.status()).toBe(200);
  const token = await tokenResponse.text();
  expect(token.length).toBeGreaterThan(20);
  const headers = { Accept: mediaType, 'Content-Type': mediaType, 'X-CSRF-Token': token };
  const name = `API tractor ${randomUUID().slice(0, 8)}`;
  let assetPath;
  let logPath;
  try {
    const created = await page.request.post('/api/asset/equipment', {
      headers, data: { data: { type: 'asset--equipment', attributes: { name } } },
    });
    expect(created.status(), await created.text()).toBe(201);
    const asset = (await created.json()).data;
    assetPath = `/api/asset/equipment/${asset.id}`;
    expect(asset.attributes.name).toBe(name);
    await page.goto(`/asset/${asset.attributes.drupal_internal__id}`);
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();

    await test.step('Reject anonymous reads/writes and cookie writes without a CSRF token', async () => {
      const anonymousRead = await request.get(assetPath, { headers: { Accept: mediaType } });
      expect(anonymousRead.status()).toBe(403);
      const anonymousWrite = await request.post('/api/asset/equipment', {
        headers: { Accept: mediaType, 'Content-Type': mediaType },
        data: { data: { type: 'asset--equipment', attributes: { name: `${name} forbidden` } } },
      });
      expect(anonymousWrite.status()).toBe(403);
      const withoutToken = await page.request.patch(assetPath, {
        headers: { Accept: mediaType, 'Content-Type': mediaType },
        data: { data: { type: asset.type, id: asset.id, attributes: { name: 'Forbidden rename' } } },
      });
      expect(withoutToken.status()).toBe(403);
      const unchanged = await page.request.get(assetPath, { headers });
      expect((await unchanged.json()).data.attributes.name).toBe(name);
    });

    await test.step('Update and filter an asset, then link an observation', async () => {
      const renamed = `${name} serviced`;
      const updated = await page.request.patch(assetPath, {
        headers, data: { data: { type: asset.type, id: asset.id, attributes: { name: renamed } } },
      });
      expect(updated.status(), await updated.text()).toBe(200);
      const filtered = await page.request.get('/api/asset/equipment', {
        headers, params: { 'filter[name]': renamed },
      });
      expect(filtered.status()).toBe(200);
      expect((await filtered.json()).data.map(record => record.id)).toEqual([asset.id]);
      const createdLog = await page.request.post('/api/log/observation', {
        headers,
        data: { data: {
          type: 'log--observation', attributes: { name: `Inspection of ${renamed}` },
          relationships: { asset: { data: [{ type: asset.type, id: asset.id }] } },
        } },
      });
      expect(createdLog.status(), await createdLog.text()).toBe(201);
      const log = (await createdLog.json()).data;
      logPath = `/api/log/observation/${log.id}`;
      const related = await page.request.get(logPath, { headers, params: { include: 'asset' } });
      expect(related.status()).toBe(200);
      const document = await related.json();
      expect(document.data.relationships.asset.data.map(({ type, id }) => ({ type, id }))).toEqual([{ type: asset.type, id: asset.id }]);
      expect(document.included.find(record => record.id === asset.id).attributes.name).toBe(renamed);
    });

    await test.step('Delete both records and verify they cannot be retrieved', async () => {
      for (const path of [logPath, assetPath]) {
        const removed = await page.request.delete(path, { headers });
        expect(removed.status(), await removed.text()).toBe(204);
        expect((await page.request.get(path, { headers })).status()).toBe(404);
      }
      logPath = undefined;
      assetPath = undefined;
    });
  } finally {
    for (const path of [logPath, assetPath].filter(Boolean)) {
      await page.request.delete(path, { headers });
    }
  }
});
