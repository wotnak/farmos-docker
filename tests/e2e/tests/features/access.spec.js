import { test, expect } from '@playwright/test';
import { randomUUID } from 'node:crypto';
import { login, createAsset, fillEntityBasics, saveEntity } from '../../support/farmos.js';

test('anonymous visitors cannot read farm records or administration pages', async ({ page }) => {
  for (const path of ['/assets', '/logs', '/asset/add/equipment', '/admin/people']) {
    const response = await page.goto(path);
    // farmOS may send anonymous visitors to login; neither response grants access.
    expect([200, 403]).toContain(response.status());
    if (response.status() === 200) {
      await expect(page.locator('input[name="pass"]')).toBeVisible();
      await expect(page.getByRole('button', { name: 'Log in', exact: true })).toBeVisible();
    } else {
      await expect(page.getByRole('heading', { name: 'Access denied', exact: true })).toBeVisible();
    }
  }
});

test('administrator manages a Viewer account whose session can read records but cannot change them', async ({ page, browser }) => {
  await login(page);
  const suffix = randomUUID().slice(0, 8);
  const viewerName = `viewer-${suffix}`;
  const viewerPassword = `Viewer-test-${suffix}-938!`;
  const assetName = `Viewer access tractor ${suffix}`;
  let userPath;
  const viewerContext = await browser.newContext({ baseURL: new URL(page.url()).origin });
  const viewer = await viewerContext.newPage();
  try {
    await test.step('Create an active Viewer without sending email', async () => {
      await page.goto('/admin/people/create');
      await page.locator('input[name="name"]').fill(viewerName);
      await page.locator('input[name="mail"]').fill(`${viewerName}@example.test`);
      await page.locator('input[name="pass[pass1]"]').fill(viewerPassword);
      await page.locator('input[name="pass[pass2]"]').fill(viewerPassword);
      await page.locator('input[name="roles[farm_viewer]"]').check();
      await page.locator('input[name="notify"]').uncheck();
      await page.getByRole('button', { name: 'Create new account', exact: true }).click();
      const userLink = page.getByRole('link', { name: viewerName, exact: true }).first();
      await expect(userLink).toHaveAttribute('href', /\/user\/\d+$/);
      userPath = await userLink.getAttribute('href');
    });

    const { path: assetPath } = await createAsset(page, { name: assetName });

    await test.step('Log in as Viewer and enforce read-only permissions', async () => {
      await login(viewer, { username: viewerName, password: viewerPassword });
      await viewer.goto(assetPath);
      await expect(viewer.getByRole('heading', { name: assetName, exact: true })).toBeVisible();
      for (const path of [`${assetPath}/edit`, '/asset/add/equipment', '/admin/people', '/admin/config/system/site-information']) {
        const response = await viewer.goto(path);
        expect(response.status(), path).toBe(403);
        await expect(viewer.getByRole('heading', { name: 'Access denied', exact: true })).toBeVisible();
      }
      const collection = await viewer.request.get('/api/asset/equipment', {
        params: { 'filter[name]': assetName },
      });
      expect(collection.status()).toBe(200);
      const records = (await collection.json()).data;
      expect(records).toHaveLength(1);
      const token = await viewer.request.get('/session/token');
      const forbidden = await viewer.request.patch(`/api/asset/equipment/${records[0].id}`, {
        headers: { 'Content-Type': 'application/vnd.api+json', 'X-CSRF-Token': await token.text() },
        data: { data: { type: records[0].type, id: records[0].id, attributes: { name: 'Forbidden viewer edit' } } },
      });
      expect(forbidden.status()).toBe(403);
    });

    await test.step('Log out and require authentication again', async () => {
      await viewer.goto('/user/logout');
      await viewer.getByRole('button', { name: 'Log out', exact: true }).click();
      await viewer.goto('/user/login');
      await expect(viewer.getByRole('button', { name: 'Log in', exact: true })).toBeVisible();
      await expect(viewer.locator('#toolbar-item-user-secondary')).toHaveCount(0);
    });

    await test.step('Block the account and reject a fresh login', async () => {
      await page.goto(`${userPath}/edit`);
      await page.locator('input[name="status"][value="0"]').check();
      await page.getByRole('button', { name: 'Save', exact: true }).click();
      await viewer.locator('input[name="name"]').fill(viewerName);
      await viewer.locator('input[name="pass"]').fill(viewerPassword);
      await viewer.getByRole('button', { name: 'Log in', exact: true }).click();
      await expect(viewer.locator('.messages--error')).toBeVisible();
      await expect(viewer.getByRole('button', { name: 'Log in', exact: true })).toBeVisible();
      await page.goto(`${userPath}/edit`);
      await expect(page.locator('input[name="status"][value="0"]')).toBeChecked();
    });
  } finally {
    await viewerContext.close();
    // The disposable test farm retains the blocked account as proof of the
    // administrative transition; unique names also allow standalone reruns.
  }
});

// Managed-role configuration grants Workers updates to any farm record but
// deletes only their own; Managers can delete any record. Neither role grants
// account/role administration or site configuration permissions.
for (const role of ['farm_worker', 'farm_manager']) {
  test(`${role}: create and edit records, enforce ownership on deletion, deny administration`, async ({ page, browser }) => {
    await login(page);
    const suffix = randomUUID().slice(0, 8);
    const accountName = `${role}-${suffix}`;
    const accountPassword = `Role-test-${suffix}-938!`;
    const other = await createAsset(page, { name: `Administrator tractor ${suffix}` });
    await page.goto('/admin/people/create');
    await page.locator('input[name="name"]').fill(accountName);
    await page.locator('input[name="mail"]').fill(`${accountName}@example.test`);
    await page.locator('input[name="pass[pass1]"]').fill(accountPassword);
    await page.locator('input[name="pass[pass2]"]').fill(accountPassword);
    await page.locator(`input[name="roles[${role}]"]`).check();
    await page.locator('input[name="notify"]').uncheck();
    await page.getByRole('button', { name: 'Create new account', exact: true }).click();
    const context = await browser.newContext({ baseURL: new URL(page.url()).origin });
    try {
      const member = await context.newPage();
      await login(member, { username: accountName, password: accountPassword });
      const own = await createAsset(member, { name: `Member tractor ${suffix}` });
      for (const asset of [own, other]) {
        await member.goto(`${asset.path}/edit`);
        await fillEntityBasics(member, { name: `${asset.name} serviced`, notes: `Updated by ${accountName}` });
        await saveEntity(member);
        await expect(member.getByRole('heading', { name: `${asset.name} serviced`, exact: true })).toBeVisible();
        await expect(member.getByText(`Updated by ${accountName}`, { exact: true })).toBeVisible();
      }
      const otherDelete = await member.goto(`${other.path}/delete`);
      if (role === 'farm_worker') {
        expect(otherDelete.status()).toBe(403);
        await expect(member.getByRole('heading', { name: 'Access denied', exact: true })).toBeVisible();
      } else {
        expect(otherDelete.status()).toBe(200);
        await member.getByRole('button', { name: 'Delete', exact: true }).click();
        expect((await member.request.get(other.path)).status()).toBe(404);
      }
      await member.goto(`${own.path}/delete`);
      await member.getByRole('button', { name: 'Delete', exact: true }).click();
      expect((await member.request.get(own.path)).status()).toBe(404);
      for (const path of ['/admin/people/create', '/admin/people/roles', '/admin/config/system/site-information']) {
        const denied = await member.goto(path);
        expect(denied.status(), path).toBe(403);
        await expect(member.getByRole('heading', { name: 'Access denied', exact: true })).toBeVisible();
      }
    } finally {
      await context.close();
    }
  });
}
