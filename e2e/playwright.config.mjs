import {defineConfig, devices} from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1, // One demo student; do not race quiz/assignment updates.
  retries: 0, // Failures remain visible; no hidden second attempt.
  timeout: 90000,
  expect: {timeout: 15000},
  forbidOnly: true,
  outputDir: 'artifacts/test-results',
  reporter: [
    ['list'],
    ['html', {outputFolder: 'artifacts/html', open: 'never'}],
    ['junit', {outputFile: 'artifacts/junit.xml'}],
  ],
  use: {
    ...devices['Desktop Chrome'],
    locale: 'en-US',
    timezoneId: 'UTC',
    actionTimeout: 15000,
    navigationTimeout: 30000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{name: 'chromium', use: {browserName: 'chromium'}}],
});
