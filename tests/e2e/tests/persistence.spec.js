import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { login, assertRecords, stateFile } from '../helpers.js';

// The shell runner recreates both farmOS and PostgreSQL before this process starts.
// This browser has no cookies or storage from installation.
test('login, linked records, and uploaded file survive container recreation', async ({ page }) => {
  const records = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
  await login(page);
  await assertRecords(page, records);
});

test('OAuth signing keys survive container recreation', async ({ request }) => {
  const file = path.join(process.env.TEST_ARTIFACTS || './artifacts', 'oauth-state.json');
  const before = JSON.parse(fs.readFileSync(file, 'utf8'));
  const response = await request.get('/oauth/jwks');
  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual(before);
});
