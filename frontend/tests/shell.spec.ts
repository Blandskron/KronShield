import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const org = { id: "org-a", slug: "equipo-a", state: "active", version: 1 };
const projects = [
  { id: "a", slug: "portal-interno", org_id: org.id, customer_id: "c", environment: "lab", state: "active", version: 1 },
  { id: "b", slug: "proyecto-vacío", org_id: org.id, customer_id: "c", environment: "lab", state: "active", version: 1 },
];

async function fixture(page: Page, authenticated = true) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.slice("/api/v1".length);
    const data = (items: unknown[]) => route.fulfill({ json: { items, next_cursor: null } });
    if (path === "/auth/logout") {
      expect(route.request().headers()["x-csrf-token"]).toBe("test-csrf");
      authenticated = false;
      return route.fulfill({ status: 204 });
    }
    if (path === "/me") return authenticated
      ? route.fulfill({ json: { user_id: "user-a", source: "web", csrf_token: "test-csrf" } })
      : route.fulfill({ status: 401, json: { code: "authentication_required" } });
    if (path === "/organizations") return data([org]);
    if (path === "/projects") return data(projects);
    if (path.startsWith("/projects/b/")) return data([]);
    if (path.endsWith("/assessments")) {
      return data([{ id: "one", label: "Revisión documental", created_at: "2026-11-23T12:00:00Z", actor_id: "user-a" }]);
    }
    if (path.endsWith("/targets")) {
      return data([{ id: "one", slug: "portal", canonical_address: "https://portal.example", environment: "lab" }]);
    }
    if (path.endsWith("/authorizations")) return data([]);
    return route.fulfill({ status: 404 });
  });
}

for (const width of [360, 768, 1440]) {
  test("dashboard responsive y accesible a " + width, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await fixture(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Resumen", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Revisión documental" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(results.violations.map((entry) => entry.id)).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath("dashboard.png"), fullPage: true });
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Saltar al contenido" })).toBeFocused();
    expect(await page.evaluate(() => getComputedStyle(document.activeElement!).outlineStyle)).toBe("solid");
    await page.getByRole("navigation").getByRole("link", { name: "Activos" }).click();
    await expect(page.getByRole("table", { name: "Inventario de activos" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "https://portal.example" })).toBeVisible();
    await page.getByLabel("Proyecto").selectOption("b");
    await expect(page.getByText("Todavía no hay activos en este proyecto.")).toBeVisible();
    await expect(page.getByText("https://portal.example")).toHaveCount(0);
  });
}

test("sesión cerrada deja la pantalla de acceso", async ({ page }) => {
  await fixture(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Cerrar sesión" }).click();
  await expect(page.getByRole("link", { name: "Iniciar sesión" })).toHaveAttribute("href", "/api/v1/auth/login");
});

for (const width of [360, 1440]) {
  test("acceso al piloto accesible y sin animación con movimiento reducido a " + width, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await fixture(page, false);
    await page.route("**/api/v1/auth/mode", (route) => route.fulfill({ json: { mode: "pilot" } }));
    await page.goto("/");
    await expect(page.getByRole("img", { name: "Blandskron" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Acceso al piloto" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    const animations = await page.locator(".sign-in-identity").evaluate((element) =>
      ["::before", "::after"].map((pseudo) => getComputedStyle(element, pseudo).animationName),
    );
    expect(animations).toEqual(["none", "none"]);
    const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
    expect(results.violations.map((entry) => entry.id)).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath("acceso.png"), fullPage: true });

    await page.getByRole("button", { name: "Primer acceso" }).click();
    await expect(page.getByLabel("Código inicial")).toBeVisible();
  });
}
