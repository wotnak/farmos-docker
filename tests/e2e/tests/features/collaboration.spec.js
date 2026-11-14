import { test, expect } from '@playwright/test';
import { login, uniqueName, createAsset, fillEntityBasics, saveEntity } from '../../support/farmos.js';

test.beforeEach(async ({ page }) => login(page));

test('asset comments persist, can be edited, and can be deleted', async ({ page }) => {
  const asset = await createAsset(page, { name: uniqueName('Commented tractor') });
  const comment = uniqueName('Inspection discussion');
  const revised = `${comment} with corrected details`;
  await page.locator('textarea[name="comment_body[0][value]"]').fill(comment);
  await page.getByRole('button', { name: 'Save comment', exact: true }).click();
  await page.goto(asset.path);
  const article = page.locator('article.comment').filter({ hasText: comment });
  await article.locator('a[href*="/comment/"][href*="/edit"]').click();
  await page.locator('textarea[name="comment_body[0][value]"]').fill(revised);
  await page.getByRole('button', { name: 'Save comment', exact: true }).click();
  await page.goto(asset.path);
  const updated = page.locator('article.comment').filter({ hasText: revised });
  await updated.locator('a[href*="/comment/"][href*="/delete"]').click();
  await page.getByRole('button', { name: 'Delete', exact: true }).click();
  await page.goto(asset.path);
  await expect(page.locator('article.comment').filter({ hasText: comment })).toHaveCount(0);
});

test('asset revision history preserves old values without allowing unsafe reverts', async ({ page }) => {
  const original = uniqueName('Revision tractor');
  const originalNotes = `Original inspection for ${original}`;
  const asset = await createAsset(page, { name: original, notes: originalNotes });
  const updated = `${original} updated`;
  await page.goto(`${asset.path}/edit`);
  await fillEntityBasics(page, { name: updated, notes: `Updated inspection for ${original}` });
  // farm_entity creates revisions on every save and hides Drupal's checkbox.
  await saveEntity(page);
  await expect(page.getByRole('heading', { name: updated, exact: true })).toBeVisible();
  await page.goto(`${asset.path}/revisions`);
  const revisionLinks = page.locator(`a[href*="${asset.path}/revisions/"][href$="/view"]`);
  await expect(page.locator('main table tbody tr')).toHaveCount(2);
  await expect(revisionLinks).toHaveCount(1);
  const oldRevision = await revisionLinks.last().getAttribute('href');
  await page.goto(oldRevision);
  await expect(page.getByText(originalNotes, { exact: true })).toBeVisible();
  await expect(page.getByText(`Updated inspection for ${original}`, { exact: true })).toHaveCount(0);
  await page.goto(`${asset.path}/revisions`);
  // farm_entity deliberately disables reverts because cross-record validation
  // cannot be guaranteed when Drupal restores an older revision.
  await expect(page.getByRole('link', { name: 'Revert', exact: true })).toHaveCount(0);
  expect((await page.request.get(oldRevision.replace(/\/view$/, '/revert'))).status()).toBe(404);
  await page.goto(asset.path);
  await expect(page.getByRole('heading', { name: updated, exact: true })).toBeVisible();
  await expect(page.getByText(`Updated inspection for ${original}`, { exact: true })).toBeVisible();
});
