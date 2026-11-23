import { defineConfig, devices } from "@playwright/test";

const pilot = process.env.PENTEST_AGENT_E2E_ORIGIN;

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  use: { ...devices["Desktop Chrome"], baseURL: pilot ?? "http://127.0.0.1:5177", timezoneId: "UTC" },
  webServer: pilot ? undefined : {
    command: "npm run dev -- --port 5177 --strictPort",
    url: "http://127.0.0.1:5177",
    timeout: 30_000,
    reuseExistingServer: false,
  },
});
