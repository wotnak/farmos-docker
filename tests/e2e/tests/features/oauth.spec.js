import { test, expect } from '@playwright/test';
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { login, createAsset } from '../../support/farmos.js';

// Use the shipped public client and a fresh Viewer so every run exercises
// consent, even when the client remembers earlier users' approvals.
test('OAuth authorization code with PKCE signs tokens using private persistent keys and limits API access', async ({ page, browser, request }) => {
  await login(page);
  const origin = new URL(page.url()).origin;
  const keysResponse = await request.get('/oauth/jwks');
  expect(keysResponse.status()).toBe(200);
  let publicKeys = await keysResponse.json();
  if (!publicKeys.keys?.length) {
    await test.step('Generate initial OAuth keys through the administration form', async () => {
      await page.goto('/admin/config/people/simple_oauth');
      const privateKey = page.locator('input[name="private_key"]');
      const directory = process.env.FARMOS_OAUTH_KEY_DIR || path.posix.dirname(await privateKey.inputValue());
      const generate = page.getByRole('link', { name: 'Generate keys', exact: true });
      await expect(generate).toHaveAttribute('data-once', /ajax/);
      await generate.click();
      await page.locator('input[name="directory"]').fill(directory);
      await page.getByRole('button', { name: 'Generate', exact: true }).click();
      await expect(privateKey).toHaveValue(path.posix.join(directory, 'private.key'));
      await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
      const generated = await request.get('/oauth/jwks');
      expect(generated.status()).toBe(200);
      publicKeys = await generated.json();
      expect(publicKeys.keys[0].kty).toBe('RSA');
    });
  }
  const artifacts = process.env.TEST_ARTIFACTS || './artifacts';
  fs.mkdirSync(artifacts, { recursive: true });
  fs.writeFileSync(path.join(artifacts, 'oauth-state.json'), JSON.stringify(publicKeys, null, 2));

  const suffix = randomUUID().slice(0, 8);
  const viewerName = `oauth-viewer-${suffix}`;
  const viewerPassword = `OAuth-viewer-${suffix}-938!`;
  const asset = await createAsset(page, { name: `OAuth visible tractor ${suffix}` });
  await page.goto('/admin/people/create');
  await page.locator('input[name="name"]').fill(viewerName);
  await page.locator('input[name="mail"]').fill(`${viewerName}@example.test`);
  await page.locator('input[name="pass[pass1]"]').fill(viewerPassword);
  await page.locator('input[name="pass[pass2]"]').fill(viewerPassword);
  await page.locator('input[name="roles[farm_viewer]"]').check();
  await page.locator('input[name="notify"]').uncheck();
  await page.getByRole('button', { name: 'Create new account', exact: true }).click();

  const context = await browser.newContext({ baseURL: origin });
  try {
    const authorize = await context.newPage();
    const verifier = randomBytes(48).toString('base64url');
    const state = randomUUID();
    const query = new URLSearchParams({
      response_type: 'code', client_id: 'farm', scope: 'farm_viewer',
      redirect_uri: origin, state,
      code_challenge: createHash('sha256').update(verifier).digest('base64url'),
      code_challenge_method: 'S256',
    });
    await authorize.goto(`/oauth/authorize?${query}`);
    await expect(authorize.locator('input[name="pass"]')).toBeVisible();
    await authorize.locator('input[name="name"]').fill(viewerName);
    await authorize.locator('input[name="pass"]').fill(viewerPassword);
    await authorize.getByRole('button', { name: 'Log in', exact: true }).click();
    await expect(authorize.getByRole('button', { name: 'Allow', exact: true })).toBeVisible();
    await expect(authorize.getByText('Grants access to the Farm Viewer role.', { exact: true })).toBeVisible();
    await authorize.getByRole('button', { name: 'Allow', exact: true }).click();
    await expect(authorize).toHaveURL(url => url.searchParams.has('code'));
    const callback = new URL(authorize.url());
    expect(callback.origin).toBe(origin);
    expect(callback.searchParams.get('state')).toBe(state);
    const tokenForm = {
      grant_type: 'authorization_code', client_id: 'farm', redirect_uri: origin,
      code: callback.searchParams.get('code'), code_verifier: verifier,
    };
    const exchange = await request.post('/oauth/token', { form: tokenForm });
    expect(exchange.status()).toBe(200);
    const tokens = await exchange.json();
    expect(tokens.token_type).toBe('Bearer');
    const headers = { Authorization: `Bearer ${tokens.access_token}`, Accept: 'application/vnd.api+json' };
    const collection = await request.get('/api/asset/equipment', { headers, params: { 'filter[name]': asset.name } });
    expect(collection.status()).toBe(200);
    const records = (await collection.json()).data;
    expect(records).toHaveLength(1);
    const resource = `/api/asset/equipment/${records[0].id}`;
    const denied = await request.patch(resource, {
      headers: { ...headers, 'Content-Type': 'application/vnd.api+json' },
      data: { data: { type: records[0].type, id: records[0].id, attributes: { name: 'Forbidden OAuth write' } } },
    });
    expect(denied.status()).toBe(403);
    expect((await request.post('/oauth/token', { form: tokenForm })).status()).toBe(400);
    const refreshed = await request.post('/oauth/token', {
      form: { grant_type: 'refresh_token', client_id: 'farm', refresh_token: tokens.refresh_token },
    });
    expect(refreshed.status()).toBe(200);
    const refreshedToken = (await refreshed.json()).access_token;
    expect((await request.get(resource, { headers: { Authorization: `Bearer ${refreshedToken}` } })).status()).toBe(200);
    expect((await request.get('/system/files/keys/private.key')).status()).toBe(404);
  } finally {
    await context.close();
  }
});
