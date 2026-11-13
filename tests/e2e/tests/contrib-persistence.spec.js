import { test, expect } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { login } from '../support/farmos.js';
import { selectedModules } from '../support/contrib.js';

for (const module of selectedModules()) {
  test(`${module}: records survive application and database container recreation`, async ({ page }) => {
    const file = path.join(process.env.TEST_ARTIFACTS || './artifacts', 'contrib-records', `${module}.json`);
    const records = JSON.parse(fs.readFileSync(file, 'utf8'));
    expect(records.length).toBeGreaterThan(0);
    await login(page);
    for (const record of records) {
      expect((await page.goto(record.path)).status()).toBe(200);
      await expect(page.getByRole('heading', { name: record.name, exact: true })).toBeVisible();
      if (record.apiPath) {
        const response = await page.request.get(record.apiPath);
        expect(response.status()).toBe(200);
        const { data } = await response.json();
        if (record.attributes) expect(data.attributes).toMatchObject(record.attributes);
        for (const [field, uuid] of Object.entries(record.relationships || {})) {
          const relation = data.relationships[field].data;
          expect(Array.isArray(relation) ? relation.map(item => item.id) : [relation.id]).toContain(uuid);
        }
      }
      if (record.file) {
        const response = await page.request.get(record.file.href);
        expect(response.status()).toBe(200);
        expect(await response.text()).toBe(record.file.contents);
      }
    }
  });
}
