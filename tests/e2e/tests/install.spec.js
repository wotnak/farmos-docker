import { test, expect } from '@playwright/test';
import { username, password } from '../helpers.js';

test('install farmOS and configure base modules', async ({ page }) => {
  await test.step('Install farmOS through its browser installer', async () => {
    await page.goto('/core/install.php?profile=farm&langcode=en');
    // Production supplies immutable settings; standalone sites may use the database form.
    if (process.env.FARMOS_DB_PRECONFIGURED !== '1') {
      await expect(page.getByRole('heading', { name: 'Database configuration' })).toBeVisible();
      await page.getByLabel('Database name', { exact: true }).fill(process.env.FARMOS_DB_NAME || 'farmos');
      await page.getByLabel('Database username', { exact: true }).fill(process.env.FARMOS_DB_USER || 'farm');
      await page.getByLabel('Database password', { exact: true }).fill(process.env.FARMOS_DB_PASS || 'farm-test-password');
      await page.getByText('Advanced options', { exact: true }).click();
      await page.getByLabel('Host', { exact: true }).fill(process.env.FARMOS_DB_HOST || 'db');
      await page.getByRole('button', { name: 'Save and continue' }).click();
    }
    await expect(page.locator('input[name="site_name"]')).toBeVisible({ timeout: 240_000 });
    await page.locator('input[name="site_name"]').fill('Container acceptance farm');
    await page.locator('input[name="site_mail"]').fill(process.env.FARMOS_ADMIN_EMAIL || 'admin@example.test');
    await page.locator('input[name="account[name]"]').fill(username);
    await page.locator('input[name="account[pass][pass1]"]').fill(password);
    await page.locator('input[name="account[pass][pass2]"]').fill(password);
    await page.locator('input[name="account[mail]"]').fill(process.env.FARMOS_ADMIN_EMAIL || 'admin@example.test');
    await page.getByLabel('Default time zone').selectOption('UTC');
    await page.getByLabel('Check for updates automatically').uncheck();
    await page.getByRole('button', { name: 'Save and continue' }).click();
    await expect(page.getByText('Congratulations, you installed farmOS!')).toBeVisible({ timeout: 240_000 });
  });

  await test.step('Enable base asset and log types through the setup wizard', async () => {
    await page.getByRole('button', { name: 'Continue', exact: true }).click();
    for (const name of [
      'plant', 'plant_seeding', 'plant_transplanting',
      'animal', 'animal_birth', 'animal_medical', 'animal_movement', 'animal_group', 'animal_inventory',
      'equipment', 'equipment_maintenance', 'equipment_movement', 'compost',
      'inventory', 'inventory_material', 'inventory_product', 'inventory_seed',
      'land', 'land_lab_test', 'structure', 'water', 'water_lab_test',
      'activity', 'observation', 'input', 'harvest',
    ]) {
      const checkbox = page.locator(`input[name="${name}"]`);
      if (await checkbox.isDisabled()) {
        await expect(checkbox).toBeChecked();
        continue;
      }
      // Wait for Drupal to attach AJAX behavior before interacting with a new form.
      await expect(checkbox).toHaveAttribute('data-once', /drupal-ajax/);
      await Promise.all([
        page.waitForResponse(response => response.request().method() === 'POST'
          && response.url().includes('_wrapper_format=drupal_ajax')),
        checkbox.check(),
      ]);
      await expect(page.getByText('The following modules will be installed:', { exact: false })).toBeVisible();
      await expect(page.locator('.ajax-progress')).toHaveCount(0);
      await expect(checkbox).toBeChecked();
    }
    await page.getByRole('button', { name: 'Save and continue' }).click();
    await expect(page.getByText('Step 3: Resources', { exact: true })).toBeVisible({ timeout: 180_000 });
    await page.getByRole('button', { name: 'Finish', exact: true }).click();
    await expect(page.getByText('farmOS setup is complete! Happy record keeping!')).toBeVisible();
  });

  await test.step('Enable remaining standard farmOS modules', async () => {
    await page.goto('/setup/modules');
    // Optional external map providers require third-party API keys and are not base fixtures.
    const excluded = ['farm_map_google', 'farm_map_mapbox', 'farm_l10n'];
    for (const checkbox of await page.locator('input[type="checkbox"][name^="core[modules]"]').all()) {
      const name = await checkbox.getAttribute('name');
      if (!excluded.some(module => name === `core[modules][${module}]`) && await checkbox.isEnabled()) {
        await checkbox.check();
      }
    }
    await page.getByRole('button', { name: 'Install modules', exact: true }).click();
    await expect(page.locator('input[name="core[modules][farm_sensor]"]')).toBeDisabled({ timeout: 240_000 });
  });
});
