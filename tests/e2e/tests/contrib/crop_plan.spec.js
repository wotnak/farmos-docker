import { test, expect } from '@playwright/test';
import { login, uniqueName, createAsset, saveEntity } from '../../support/farmos.js';
import { createPlan, timeline, assertViewerAccess, rememberPlan } from './planning-helpers.js';

const timestamp = value => Date.parse(value) / 1000;

test('Crop Plan: two plantings retain stages, reject duplicates, allow edits and enforce Viewer access', async ({ page, browser }) => {
  await login(page);
  const plan = await createPlan(page, 'crop');
  const plants = [];
  for (let index = 0; index < 2; index++) {
    const plant = await createAsset(page, {
      type: 'plant', name: uniqueName(`Planned carrot ${index}`),
      configure: async () => {
        await page.locator('[name="plant_type[0][target_id]"]').fill(uniqueName('Carrot variety'));
        await page.locator('[name="season[0][target_id]"]').fill(plan.season);
      },
    });
    plants.push(plant);
    // This is the module's documented preselected-plant entry point. The
    // relationship itself is created by submitting the released browser form.
    await page.goto(`${plan.path}/crop/planting?plant=${plant.id}`);
    await expect(page.locator('[name="plant"]')).toHaveValue(new RegExp(plant.name));
    await page.locator('[name="seeding_date[date]"]').fill('2026-03-01');
    await page.locator('[name="seeding_date[time]"]').fill('09:00:00');
    await page.locator('[name="transplant_days"]').fill('14');
    await page.locator('[name="maturity_days"]').fill('60');
    await page.locator('[name="harvest_days"]').fill('10');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page).toHaveURL(plan.path);
  }
  for (const plant of plants) await expect(page.locator('.farm-timeline').getByRole('link', { name: plant.name, exact: true })).toBeVisible();
  const endpoint = `${plan.path}/timeline/crop/plant_type`;
  let rows = await timeline(page, endpoint);
  expect(rows.flatMap(row => row.children).map(row => row.label).sort()).toEqual(plants.map(plant => plant.name).sort());
  const planting = rows.flatMap(row => row.children).find(row => row.label === plants[0].name);
  const stage = kind => planting.tasks.find(task => task.meta.stage === kind);
  const seeded = Date.parse('2026-03-01T09:00:00Z') / 1000;
  expect(timestamp(stage('seeding').start)).toBe(seeded);
  expect(timestamp(stage('seeding').end)).toBe(seeded + 14 * 86400);
  expect(timestamp(stage('transplanting').end)).toBe(seeded + 60 * 86400);
  expect(timestamp(stage('harvest').end)).toBe(seeded + 70 * 86400);
  const editPath = stage('seeding').edit_url;
  await page.goto(editPath);
  await page.locator('[name="maturity_days[0][value]"]').fill('75');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page).toHaveURL(plan.path);
  rows = await timeline(page, endpoint);
  const edited = rows.flatMap(row => row.children).find(row => row.label === plants[0].name);
  expect(timestamp(edited.tasks.find(task => task.meta.stage === 'harvest').start)).toBe(seeded + 75 * 86400);

  await page.goto(`${plan.path}/crop/planting?plant=${plants[0].id}`);
  await page.locator('[name="maturity_days"]').fill('60');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.locator('.messages--error')).toContainText('This plant asset is already added to the plan.');
  expect((await timeline(page, endpoint)).flatMap(row => row.children)).toHaveLength(2);
  await assertViewerAccess(page, browser, plan, endpoint, [`${plan.path}/crop/planting`, editPath]);

  await page.goto(`${plan.path}/edit`);
  await page.locator('[name="archived[value]"]').check();
  await saveEntity(page, 'plan');
  await page.goto(`${plan.path}/edit`);
  await expect(page.locator('[name="archived[value]"]')).toBeChecked();
  await rememberPlan(page, 'crop_plan', 'crop', plan, true);
});
