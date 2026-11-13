import { defineConfig } from '@playwright/test';
import path from 'node:path';
import { selectedModules } from './support/contrib.js';

const artifacts = process.env.TEST_ARTIFACTS || './artifacts';
const phase = process.env.TEST_PHASE || 'core';
if (!['install', 'core', 'smoke', 'persistence', 'contrib', 'contrib-persistence'].includes(phase)) throw new Error(`Unknown TEST_PHASE: ${phase}`);
const testMatch = phase === 'core' ? ['smoke.spec.js', 'features/**/*.spec.js']
  : phase === 'contrib' ? selectedModules().map(module => `contrib/${module}.spec.js`)
    : `${phase}.spec.js`;

export default defineConfig({
  testDir: './tests',
  testMatch,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: phase === 'install' ? 600_000 : 180_000,
  expect: { timeout: 30_000 },
  outputDir: path.join(artifacts, phase, 'results'),
  reporter: [
    ['list'],
    ['html', { outputFolder: path.join(artifacts, phase, 'report'), open: 'never' }],
    ['junit', { outputFile: path.join(artifacts, phase, 'junit.xml') }],
  ],
  use: {
    browserName: 'chromium',
    baseURL: process.env.BASE_URL || 'http://farmos:8080',
    locale: 'en-US',
    timezoneId: 'UTC',
    actionTimeout: 30_000,
    navigationTimeout: 120_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
});
