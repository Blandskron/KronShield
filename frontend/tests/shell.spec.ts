import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const accessibilityTags = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"];
const org = { id: "org-a", slug: "equipo-a", state: "active", version: 1 };
const projects = [
  { id: "a", slug: "portal-interno", org_id: org.id, customer_id: "c", environment: "lab", state: "active", version: 1 },
  { id: "b", slug: "proyecto-vacío", org_id: org.id, customer_id: "c", environment: "lab", state: "active", version: 1 },
];

async function fixture(page: Page, authenticated = true) {
  const modes = ["red", "blue", "purple", "yellow", "orange", "green", "white", "black", "gold", "rainbow"]
    .map((id) => ({
      manifest: { id, version: 1, label: id[0].toUpperCase() + id.slice(1) + " Team",
        purpose: "Revisión de evidencia autorizada", inputs: ["Manifiesto de evidencia"],
        output: "Informe documentado", workflow: [{ id: "review", kind: "capability", tool: "scope-record-review" }] },
      digest: "fixture-" + id,
      eligible_for_analysis: false,
    }));
  let selection: { version: number; selection: null | { mode_id: string; mode_version: number; mode_digest: string } } =
    { version: 0, selection: null };
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
      ? route.fulfill({ json: { user_id: "user-a", source: "web", csrf_token: "test-csrf",
          permissions: url.searchParams.get("project_id") === "a" ? ["project:manage"] : ["project:read"] } })
      : route.fulfill({ status: 401, json: { code: "authentication_required" } });
    if (path === "/organizations") return data([org]);
    if (path === "/projects") return data(projects);
    if (path.endsWith("/team-modes")) return route.fulfill({ json: { items: modes } });
    if (path.endsWith("/team-selection")) {
      if (path.startsWith("/projects/b/")) return route.fulfill({ json: { version: 0, selection: null } });
      if (route.request().method() === "PUT") {
        const { mode_id } = route.request().postDataJSON();
        expect(route.request().headers()["x-csrf-token"]).toBe("test-csrf");
        expect(route.request().headers()["if-match"]).toBe('"' + selection.version + '"');
        selection = { version: selection.version + 1,
          selection: { mode_id, mode_version: 1, mode_digest: "fixture-" + mode_id } };
      }
      return route.fulfill({ json: selection });
    }
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

for (const width of [320, 360, 768, 1440]) {
  test("dashboard responsive y accesible a " + width, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await fixture(page);
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Resumen", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Revisión documental" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    const results = await new AxeBuilder({ page }).withTags(accessibilityTags).analyze();
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

test("la especialidad se guarda por proyecto y los lectores consultan el catálogo", async ({ page }) => {
  await fixture(page);
  await page.goto("/");
  const select = page.getByLabel("Elegir especialidad");
  await expect(select.locator("option:not([disabled])")).toHaveCount(10);
  await select.focus();
  await select.press("End");
  await expect(select).toHaveValue("rainbow");
  await page.getByText("Ver capacidades de Rainbow Team").click();
  await expect(page.getByText("Análisis pendiente de habilitación")).toBeVisible();
  const save = page.getByRole("button", { name: "Guardar especialidad" });
  await save.focus();
  await save.press("Enter");
  await expect(page.getByText("Especialidad guardada.")).toBeVisible();
  await expect(save).toBeFocused();
  await page.reload();
  await expect(select).toHaveValue("rainbow");

  await select.selectOption("red");
  const project = page.getByRole("combobox", { name: "Proyecto", exact: true });
  await project.selectOption("b");
  await expect(page.getByText("Todavía no hay una especialidad configurada.")).toBeVisible();
  await expect(save).toHaveCount(0);
  await expect(page.getByLabel("Consultar especialidad").locator("option:not([disabled])")).toHaveCount(10);
  await project.selectOption("a");
  await expect(select).toHaveValue("rainbow");
});

test("una selección que llega tarde no aparece en el proyecto nuevo", async ({ page }) => {
  await fixture(page);
  let started!: () => void;
  const requestStarted = new Promise<void>((resolve) => { started = resolve; });
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => { finish = resolve; });
  let completed!: () => void;
  const responseAttempted = new Promise<void>((resolve) => { completed = resolve; });
  await page.route((url) => url.pathname === "/api/v1/projects/a/team-selection", async (route) => {
    started();
    await pending;
    try {
      await route.fulfill({ json: { version: 1,
        selection: { mode_id: "rainbow", mode_version: 1, mode_digest: "fixture-rainbow" } } });
    } catch {
      // Changing projects cancels the request if it is still in flight.
    } finally {
      completed();
    }
  });
  try {
    await page.goto("/");
    await requestStarted;
    await expect(page.getByText("Cargando especialidades…")).toBeVisible();
    await page.getByRole("combobox", { name: "Proyecto", exact: true }).selectOption("b");
    await expect(page.getByText("Todavía no hay una especialidad configurada.")).toBeVisible();
  } finally {
    finish();
  }
  await responseAttempted;
  await expect(page.getByText("Selección guardada · Rainbow Team")).toHaveCount(0);
  await expect(page.getByLabel("Consultar especialidad")).toHaveValue("");
});

for (const width of [320, 360, 1440]) {
  test("acceso al piloto accesible y sin animación con movimiento reducido a " + width, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await fixture(page, false);
    await page.route("**/api/v1/auth/mode", (route) => route.fulfill({ json: { mode: "pilot" } }));
    await page.goto("/");
    await expect(page.getByText("KronShield", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Acceso al piloto" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    const animations = await page.locator(".sign-in-identity").evaluate((element) =>
      ["::before", "::after"].map((pseudo) => getComputedStyle(element, pseudo).animationName),
    );
    expect(animations).toEqual(["none", "none"]);
    const results = await new AxeBuilder({ page }).withTags(accessibilityTags).analyze();
    expect(results.violations.map((entry) => entry.id)).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath("acceso.png"), fullPage: true });

    await page.getByRole("button", { name: "Primer acceso" }).click();
    await expect(page.getByLabel("Código inicial")).toBeVisible();
  });
}

test("preferencia de tema, filtros y salto al contenido conservan el contexto", async ({ page }) => {
  await fixture(page);
  await page.goto("/#activos");
  await expect(page.getByRole("table", { name: "Inventario de activos" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByLabel("Tema", { exact: true }).selectOption("light");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await expect(page.getByLabel("Tema", { exact: true })).toHaveValue("light");
  const results = await new AxeBuilder({ page }).withTags(accessibilityTags).analyze();
  expect(results.violations.map((entry) => entry.id)).toEqual([]);
  const filter = page.getByRole("searchbox", { name: "Filtrar inventario de activos" });
  await filter.fill("not-a-match");
  await expect(page.getByText("0 de 1 registros cargados")).toBeVisible();
  await filter.fill("portal");
  await expect(page.getByRole("cell", { name: "https://portal.example" })).toBeVisible();
  await page.emulateMedia({ colorScheme: "light" });
  await page.getByLabel("Tema", { exact: true }).selectOption("system");
  await expect(page.locator("html")).toHaveCSS("color", "rgb(17, 28, 43)");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveCSS("color", "rgb(241, 245, 249)");
  await page.getByRole("link", { name: "Saltar al contenido" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
  expect(new URL(page.url()).hash).toBe("#activos");
});

test("historial consulta los eventos y enlaza al informe HTML del proyecto", async ({ page }) => {
  await fixture(page);
  const planId = "00000000-0000-4000-8000-000000000008";
  await page.route((url) => url.pathname.startsWith("/api/v1/projects/a/plans/" + planId), (route) => {
    const url = new URL(route.request().url());
    expect(url.searchParams.get("org_id")).toBe("org-a");
    return route.fulfill({ json: url.pathname.endsWith("/events") ? {
      items: [{ id: "event", kind: "scope_review_recorded", created_at: "2026-11-23T12:00:00Z" }],
    } : { id: planId, hash: "a".repeat(64), status: "reviewed" } });
  });
  await page.goto("/#historial");
  await page.getByLabel("UUID del registro").fill(planId);
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect(page.getByRole("table", { name: "Registro de auditoría" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Descargar informe HTML" }))
    .toHaveAttribute("href", "/api/v1/projects/a/plans/" + planId + "/report?org_id=org-a");
  await page.route("**/api/v1/projects/a/legacy-imports/**", (route) => route.fulfill({ json: {
    origin: "legacy", confidence: "unverified", findings: [
      { record_key: "legacy-a", type: "observación", detail: "Resultado de una captura guardada" },
    ],
  } }));
  await page.getByLabel("Tipo de registro").selectOption("legacy");
  await page.getByLabel("UUID del registro").fill(planId);
  await page.getByRole("button", { name: "Consultar", exact: true }).click();
  await expect(page.getByText("Históricos importados · confianza sin verificar")).toBeVisible();
  await expect(page.getByRole("cell", { name: "Resultado de una captura guardada" })).toBeVisible();
});

test("primer acceso y entrada al piloto conservan los cuerpos y el orden de la API", async ({ page }) => {
  await fixture(page, false);
  let authenticated = false;
  const calls: string[] = [];
  const username = "operator";
  const password = "synthetic-password-only";
  const code = "x".repeat(40);
  await page.route("**/api/v1/auth/mode", (route) => route.fulfill({ json: { mode: "pilot" } }));
  await page.route("**/api/v1/me**", (route) => authenticated
    ? route.fulfill({ json: { user_id: "user-a", source: "web", csrf_token: "test-csrf" } })
    : route.fulfill({ status: 401, json: { code: "authentication_required" } }));
  await page.route("**/api/v1/bootstrap/redeem", (route) => {
    expect(route.request().postDataJSON()).toEqual({ username, password, code });
    calls.push("bootstrap");
    return route.fulfill({ status: 201, json: {} });
  });
  await page.route("**/api/v1/auth/local/login", (route) => {
    expect(route.request().postDataJSON()).toEqual({ username, password });
    calls.push("login");
    authenticated = true;
    return route.fulfill({ json: {} });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Primer acceso" }).click();
  await page.getByLabel("Código inicial").fill(code);
  await page.getByLabel("Usuario", { exact: true }).fill(username);
  await page.getByLabel("Contraseña", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Crear primer administrador" }).click();
  await expect(page.getByRole("heading", { name: "Resumen", exact: true })).toBeVisible();
  expect(calls).toEqual(["bootstrap", "login"]);
});

test("regresión visual de los temas del dashboard", async ({ page }) => {
  test.skip(process.platform !== "win32" || process.env.KRONSHIELD_VISUAL !== "1", "Baseline Chromium en Windows");
  await page.setViewportSize({ width: 1440, height: 920 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await fixture(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Control de alcance" })).toBeVisible();
  await expect(page.getByText("Todavía no hay una especialidad configurada.")).toBeVisible();
  await expect(page).toHaveScreenshot("dashboard-dark.png", { fullPage: true, maxDiffPixelRatio: 0.005 });
  await page.getByLabel("Tema", { exact: true }).selectOption("light");
  await expect(page).toHaveScreenshot("dashboard-light.png", { fullPage: true, maxDiffPixelRatio: 0.005 });
});

test("regresión visual de la landing móvil", async ({ page }) => {
  test.skip(process.platform !== "win32" || process.env.KRONSHIELD_VISUAL !== "1", "Baseline Chromium en Windows");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await fixture(page, false);
  await page.route("**/api/v1/auth/mode", (route) => route.fulfill({ json: { mode: "pilot" } }));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Acceso al piloto" })).toBeVisible();
  await expect(page).toHaveScreenshot("landing-mobile.png", { fullPage: true, maxDiffPixelRatio: 0.005 });
});
