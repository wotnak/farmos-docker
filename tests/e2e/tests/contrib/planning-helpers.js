import { expect } from '@playwright/test';
import { login, uniqueName, fillEntityBasics, saveEntity } from '../../support/farmos.js';
import { rememberRecord } from '../../support/contrib.js';
import { createViewer } from '../../support/contrib-accounts.js';

export async function createPlan(page, type) {
  const name = uniqueName(`${type} plan`);
  const season = uniqueName('Planning season');
  await page.goto(`/plan/add/${type}`);
  await fillEntityBasics(page, { name });
  await page.locator('[name="season[0][target_id]"]').fill(season);
  const plan = await saveEntity(page, 'plan');
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  return { ...plan, name, season };
}

export async function timeline(page, url) {
  const response = await page.request.get(url);
  expect(response.status(), await response.text()).toBe(200);
  const data = await response.json();
  expect(data.rows).toBeInstanceOf(Array);
  return data.rows;
}

export async function assertViewerAccess(page, browser, plan, timelinePath, deniedPaths) {
  const credentials = await createViewer(page, 'planner-viewer');
  const context = await browser.newContext({ baseURL: new URL(page.url()).origin });
  try {
    const viewer = await context.newPage();
    await login(viewer, credentials);
    expect((await viewer.goto(plan.path)).status()).toBe(200);
    await expect(viewer.getByRole('heading', { name: plan.name, exact: true })).toBeVisible();
    expect((await timeline(viewer, timelinePath)).length).toBeGreaterThan(0);
    for (const path of [`${plan.path}/edit`, `${plan.path}/delete`, ...deniedPaths]) {
      expect((await viewer.goto(path)).status(), path).toBe(403);
      await expect(viewer.getByRole('heading', { name: 'Access denied', exact: true })).toBeVisible();
    }
  } finally {
    await context.close();
  }
}

export async function rememberPlan(page, module, type, plan, archived) {
  const response = await page.request.get(`/api/plan/${type}`, { params: { 'filter[name]': plan.name } });
  expect(response.status()).toBe(200);
  const { data } = await response.json();
  expect(data).toHaveLength(1);
  expect(data[0].attributes.archived).toBe(archived);
  expect(data[0].relationships.season.data).toHaveLength(1);
  rememberRecord(module, {
    path: plan.path, name: plan.name, apiPath: `/api/plan/${type}/${data[0].id}`,
    attributes: { name: plan.name, archived },
    relationships: { season: data[0].relationships.season.data[0].id },
  });
}
