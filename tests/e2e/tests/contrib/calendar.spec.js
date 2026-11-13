import { test, expect } from '@playwright/test';
import { login, uniqueName, fillEntityBasics, saveEntity } from '../../support/farmos.js';
import { createViewer } from '../../support/contrib-accounts.js';
import { rememberRecord } from '../../support/contrib.js';

const day = (page, date) => page.locator('.calendar-view-day').filter({ has: page.locator(`time[datetime^="${date}"]`) });
const event = (page, date, name) => day(page, date).getByRole('link', { name, exact: true });

async function createDatedLog(page, name, date, time, status) {
  await page.goto('/log/add/observation');
  await fillEntityBasics(page, { name });
  await page.locator('input[name="timestamp[0][value][date]"]').fill(date);
  await page.locator('input[name="timestamp[0][value][time]"]').fill(time);
  await page.getByLabel('Status', { exact: true }).selectOption(status);
  return { ...await saveEntity(page, 'log'), name };
}

test('Calendar places pending and completed logs by site timezone and moves an edited event across months', async ({ page, browser }) => {
  await login(page);
  const viewerCredentials = await createViewer(page, 'calendar-viewer');
  await page.goto('/admin/config/regional/settings');
  const originalTimezone = await page.getByRole('combobox', { name: 'Default time zone', exact: true }).inputValue();
  const originalConfigurable = await page.locator('[name="configurable_timezones"]').isChecked();
  const viewerContext = await browser.newContext({ baseURL: new URL(page.url()).origin });
  try {
    // Force site timezone for all users, regardless of individual profile preferences.
    await page.getByRole('combobox', { name: 'Default time zone', exact: true }).selectOption('America/Los_Angeles');
    await page.locator('[name="configurable_timezones"]').uncheck();
    await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
    const pending = await createDatedLog(page, uniqueName('Calendar pending'), '2024-03-31', '23:30:00', 'pending');
    const completed = await createDatedLog(page, uniqueName('Calendar completed'), '2024-04-01', '00:15:00', 'done');
    const result = await page.request.get('/api/log/observation', { params: { 'filter[name]': pending.name } });
    expect(result.status()).toBe(200);
    const [resource] = (await result.json()).data;
    // March 31 in California is already April 1 UTC.
    expect(Date.parse(resource.attributes.timestamp)).toBe(Date.parse('2024-04-01T06:30:00Z'));

    await page.goto('/calendar?calendar_timestamp=2024-03-15');
    await expect(event(page, '2024-03-31', pending.name)).toHaveAttribute('href', pending.path);
    await expect(day(page, '2024-03-31').locator('li').filter({ hasText: pending.name }).locator('.dot.pending')).toBeVisible();
    await page.locator('.calendar-view-pager .pager__next a').click();
    await expect(event(page, '2024-04-01', completed.name)).toHaveAttribute('href', completed.path);
    await expect(day(page, '2024-04-01').locator('li').filter({ hasText: completed.name }).locator('.dot.done')).toBeVisible();
    await event(page, '2024-04-01', completed.name).click();
    await expect(page.getByRole('heading', { name: completed.name, exact: true })).toBeVisible();

    await page.goto(`${pending.path}/edit`);
    await page.locator('input[name="timestamp[0][value][date]"]').fill('2024-04-01');
    await page.locator('input[name="timestamp[0][value][time]"]').fill('00:30:00');
    await page.getByLabel('Status', { exact: true }).selectOption('done');
    await saveEntity(page, 'log');
    await page.goto('/calendar?calendar_timestamp=2024-03-15');
    await expect(event(page, '2024-03-31', pending.name)).toHaveCount(0);
    await page.locator('.calendar-view-pager .pager__next a').click();
    await expect(event(page, '2024-04-01', pending.name)).toHaveAttribute('href', pending.path);
    await expect(day(page, '2024-04-01').locator('li').filter({ hasText: pending.name }).locator('.dot.done')).toBeVisible();

    const viewer = await viewerContext.newPage();
    await login(viewer, viewerCredentials);
    await viewer.goto('/calendar?calendar_timestamp=2024-04-15');
    await expect(event(viewer, '2024-04-01', pending.name)).toBeVisible();
    await event(viewer, '2024-04-01', pending.name).click();
    await expect(viewer.getByRole('heading', { name: pending.name, exact: true })).toBeVisible();
    expect((await viewer.goto(`${pending.path}/edit`)).status()).toBe(403);
    const updated = await page.request.get(`/api/log/observation/${resource.id}`);
    expect(updated.status()).toBe(200);
    const updatedLog = (await updated.json()).data;
    expect(Date.parse(updatedLog.attributes.timestamp)).toBe(Date.parse('2024-04-01T07:30:00Z'));
    rememberRecord('calendar', { ...pending, apiPath: `/api/log/observation/${resource.id}`,
      attributes: { status: 'done', timestamp: updatedLog.attributes.timestamp } });
    rememberRecord('calendar', completed);
  } finally {
    await viewerContext.close();
    await page.goto('/admin/config/regional/settings');
    await page.getByRole('combobox', { name: 'Default time zone', exact: true }).selectOption(originalTimezone);
    await page.locator('[name="configurable_timezones"]').setChecked(originalConfigurable);
    await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
    await page.reload();
    await expect(page.getByRole('combobox', { name: 'Default time zone', exact: true })).toHaveValue(originalTimezone);
    await expect(page.locator('[name="configurable_timezones"]')).toBeChecked({ checked: originalConfigurable });
  }
});
