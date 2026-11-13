import { expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { username, password } from '../helpers.js';

export { username, password };
export const uniqueName = prefix => `${prefix} ${randomUUID().slice(0, 8)}`;

export async function login(page, credentials = {}) {
  const user = credentials.username || username;
  await page.goto('/user/login');
  await page.locator('input[name="name"]').fill(user);
  await page.locator('input[name="pass"]').fill(credentials.password || password);
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.locator('#toolbar-item-user-secondary')).toHaveText(user);
}

export async function openTab(page, label) {
  await page.locator('.vertical-tabs__menu-link').filter({ hasText: new RegExp(`^${label}(?:\\s|\\(|$)`) }).click();
}

export async function fillEntityBasics(page, { name, notes }) {
  if (name !== undefined) await page.locator('input[name="name[0][value]"]').fill(name);
  if (notes !== undefined) await page.locator('textarea[name="notes[0][value]"]').fill(notes);
}

export async function saveEntity(page, kind = 'asset') {
  await page.locator('#gin-sticky-edit-submit').click();
  await expect(page).toHaveURL(new RegExp(`/${kind}/\\d+$`));
  const path = new URL(page.url()).pathname;
  return { id: path.split('/').pop(), path };
}

export async function createAsset(page, { type = 'equipment', name = uniqueName(type), notes, configure } = {}) {
  await page.goto(`/asset/add/${type}`);
  await fillEntityBasics(page, { name, notes });
  if (configure) await configure(page);
  const record = await saveEntity(page);
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  return { ...record, name };
}

export async function selectAutocomplete(page, fieldName, label) {
  const field = page.locator(`input[name="${fieldName}"]`);
  await expect(field).toHaveAttribute('data-once', /autocomplete/);
  await field.fill(label);
  await page.locator('.ui-autocomplete:visible .ui-menu-item').filter({ hasText: label }).first().click();
}
