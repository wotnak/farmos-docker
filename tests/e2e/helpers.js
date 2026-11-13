import { expect } from '@playwright/test';
import fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import path from 'node:path';

export const username = process.env.FARMOS_ADMIN_USER || 'farm-admin';
export const password = process.env.FARMOS_ADMIN_PASSWORD || 'Container-test-password-938!';
const runId = randomUUID().slice(0, 8);
export const assetName = `Acceptance tractor ${runId}`;
export const assetNotes = 'Equipment created through the production container browser.';
export const logName = `Acceptance inspection ${runId}`;
export const logNotes = 'Inspection linked to the acceptance tractor.';
export const filename = `container-acceptance-${runId}.txt`;
export const fileContents = 'farmOS container acceptance upload\nPersists across container recreation.\n';
export const stateFile = path.join(process.env.TEST_ARTIFACTS || './artifacts', 'records.json');

export async function login(page) {
  await page.goto('/user/login');
  await page.locator('input[name="name"]').fill(username);
  await page.locator('input[name="pass"]').fill(password);
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.locator('#toolbar-item-user-secondary')).toHaveText(username);
}

export async function assertRecords(page, records) {
  await page.goto(records.assetPath);
  await expect(page.getByRole('heading', { name: records.assetName, exact: true })).toBeVisible();
  await expect(page.getByText(assetNotes, { exact: true })).toBeVisible();
  const fileLink = page.getByRole('link', { name: records.filename, exact: true });
  await expect(fileLink).toBeVisible();
  const response = await page.request.get(await fileLink.getAttribute('href'));
  expect(response.status()).toBe(200);
  expect(await response.text()).toBe(fileContents);
  await page.goto(records.logPath);
  await expect(page.getByRole('heading', { name: records.logName, exact: true })).toBeVisible();
  await expect(page.getByText(logNotes, { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: records.assetName, exact: true })).toHaveAttribute('href', records.assetPath);
}

export function saveRecords(records) {
  fs.mkdirSync(path.dirname(stateFile), { recursive: true });
  fs.writeFileSync(stateFile, JSON.stringify(records, null, 2));
}
