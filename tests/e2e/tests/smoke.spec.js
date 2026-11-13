import { test, expect } from '@playwright/test';
import {
  assetName, assetNotes, logName, logNotes,
  filename, fileContents, login, assertRecords, saveRecords,
} from '../helpers.js';

test('create linked asset and log records and retrieve an uploaded file', async ({ page }) => {
  await login(page);
  const records = { assetName, logName, filename };
  await test.step('Create an equipment asset with notes and a file attachment', async () => {
    await page.goto('/asset/add/equipment');
    await page.locator('input[name="name[0][value]"]').fill(assetName);
    await page.locator('textarea[name="notes[0][value]"]').fill(assetNotes);
    await page.getByRole('link', { name: 'Files', exact: true }).click();
    await page.locator('input[type="file"][name="files[file_0][]"]').setInputFiles({
      name: filename, mimeType: 'text/plain', buffer: Buffer.from(fileContents),
    });
    await expect(page.getByRole('link', { name: filename, exact: true })).toBeVisible();
    await expect(page.locator('.ajax-progress')).toHaveCount(0);
    await page.locator('#gin-sticky-edit-submit').click();
    await expect(page).toHaveURL(/\/asset\/\d+$/);
    records.assetPath = new URL(page.url()).pathname;
  });

  await test.step('Create an observation linked to that asset', async () => {
    // The asset's Add Log action preselects this asset in the new log form.
    await expect(page.getByRole('heading', { name: assetName, exact: true })).toBeVisible();
    const addLog = page.getByRole('link', { name: 'Add Log: Observation', exact: true });
    if (!(await addLog.isVisible())) {
      await page.getByRole('button', { name: 'List additional actions' }).click();
    }
    await addLog.click();
    await page.locator('input[name="name[0][value]"]').fill(logName);
    await page.locator('textarea[name="notes[0][value]"]').fill(logNotes);
    await page.locator('a[href="#edit-asset-field-group"]').click();
    await expect(page.locator('#edit-asset-current')).toBeVisible();
    await expect(page.locator('#edit-asset-current')).toContainText(assetName);
    await page.locator('#gin-sticky-edit-submit').click();
    await expect(page).toHaveURL(/\/log\/\d+$/);
    records.logPath = new URL(page.url()).pathname;
  });

  await test.step('Read saved records and retrieve the uploaded bytes', async () => {
    await assertRecords(page, records);
    saveRecords(records);
  });
});
