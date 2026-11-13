import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { login } from '../../support/farmos.js';

test('manage equipment taxonomy terms through create, edit and delete forms', async ({ page }) => {
  await login(page);
  const name = `Acceptance equipment class ${randomUUID().slice(0, 8)}`;
  const renamed = `${name} revised`;
  await page.goto('/admin/structure/taxonomy/manage/equipment_type/add');
  await page.locator('input[name="name[0][value]"]').fill(name);
  await page.locator('#gin-sticky-edit-submit').click();
  await page.goto('/admin/structure/taxonomy/manage/equipment_type/overview');
  const row = page.getByRole('row').filter({ hasText: name });
  await expect(row).toBeVisible();
  await row.getByRole('link', { name: `Edit ${name}`, exact: true }).click();
  const termPath = new URL(page.url()).pathname.replace(/\/edit$/, '');
  await page.locator('input[name="name[0][value]"]').fill(renamed);
  await page.locator('#gin-sticky-edit-submit').click();
  await page.goto('/admin/structure/taxonomy/manage/equipment_type/overview');
  await expect(page.getByRole('row').filter({ hasText: renamed })).toBeVisible();
  await page.goto(`${termPath}/delete`);
  await page.getByRole('button', { name: 'Delete', exact: true }).click();
  await page.goto('/admin/structure/taxonomy/manage/equipment_type/overview');
  await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(0);
});

test('save site configuration and restore the original value', async ({ page }) => {
  await login(page);
  await page.goto('/admin/config/system/site-information');
  const original = await page.locator('input[name="site_name"]').inputValue();
  const changed = `Acceptance farm ${randomUUID().slice(0, 8)}`;
  try {
    await page.locator('input[name="site_name"]').fill(changed);
    await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
    await expect(page.getByText('The configuration options have been saved.', { exact: true })).toBeVisible();
    await page.goto('/admin/config/system/site-information');
    await expect(page.locator('input[name="site_name"]')).toHaveValue(changed);
    const response = await page.request.get('/api');
    expect(response.status()).toBe(200);
    expect((await response.json()).meta.farm.name).toBe(changed);
  } finally {
    await page.goto('/admin/config/system/site-information');
    await page.locator('input[name="site_name"]').fill(original);
    await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
    await expect(page.locator('input[name="site_name"]')).toHaveValue(original);
  }
});
