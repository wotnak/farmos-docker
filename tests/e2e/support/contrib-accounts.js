import { expect } from '@playwright/test';
import { uniqueName } from './farmos.js';

export async function createViewer(page, prefix) {
  const username = uniqueName(prefix).replaceAll(' ', '-');
  const password = `Viewer-password-${username}-938!`;
  await page.goto('/admin/people/create');
  await page.locator('input[name="name"]').fill(username);
  await page.locator('input[name="mail"]').fill(`${username}@example.test`);
  await page.locator('input[name="pass[pass1]"]').fill(password);
  await page.locator('input[name="pass[pass2]"]').fill(password);
  await page.locator('input[name="roles[farm_viewer]"]').check();
  await page.locator('input[name="notify"]').uncheck();
  await page.getByRole('button', { name: 'Create new account', exact: true }).click();
  await expect(page.getByText('No email has been sent.', { exact: false })).toBeVisible();
  return { username, password };
}
