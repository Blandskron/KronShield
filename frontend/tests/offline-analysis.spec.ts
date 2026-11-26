import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { createHash } from "node:crypto";

const org = "11111111-1111-4111-8111-111111111111";
const project = "22222222-2222-4222-8222-222222222222";
const anotherProject = "99999999-9999-4999-8999-999999999999";
const plan = "33333333-3333-4333-8333-333333333333";
const target = "44444444-4444-4444-8444-444444444444";
const permission = "55555555-5555-4555-8555-555555555555";
const analysis = "66666666-6666-4666-8666-666666666666";
const reservation = "77777777-7777-4777-8777-777777777777";
const planHash = "a".repeat(64);
const manifestDigest = "b".repeat(64);
const now = "2026-11-25T16:00:00Z";
const content = Buffer.from(JSON.stringify({ target_id: target, observations: [{ control: "logging", result: "observed" }] }));
const digest = createHash("sha256").update(content).digest("hex");
const file = { name: "observaciones.json", mimeType: "application/json", buffer: content };
const roles = {
  operator: ["project:read", "evidence:request", "assessments:manage"],
  approver: ["project:read", "evidence:decide", "analyses:publish"],
  viewer: ["project:read"],
};
type Role = keyof typeof roles;
type Decision = { conclusion_id: string; actor_id: string; decision: string; reason: string; decided_at: string };

function link(refs: Record<string, string>) {
  return "/#plan?" + new URLSearchParams({ org, project, ...refs });
}

const blueRule = "identity-login-failure-v1";
const eventContent = Buffer.from(JSON.stringify({
  target_id: target, producer: "identity-audit", window_start: now, window_end: "2026-11-25T17:00:00Z", events: [],
}));
const eventFile = { name: "eventos.json", mimeType: "application/json", buffer: eventContent };
const secondEventFile = { ...eventFile, name: "eventos-2.json", buffer: Buffer.from(JSON.stringify({
  target_id: target, producer: "identity-audit", window_start: "2026-11-25T17:00:00Z",
  window_end: "2026-11-25T18:00:00Z", events: [],
})) };
const coverageScenario = {
  scenario_id: "88888888-8888-4888-8888-888888888888", target_id: target,
  checks: [0, 1, 2].map((index) => ({
    control_id: ["hit", "negative", "gap"][index], rule_id: blueRule,
    window_start: `2026-11-25T1${index + 5}:00:00Z`, window_end: `2026-11-25T1${index + 6}:00:00Z`,
  })),
};

function fixture(mode = "white") {
  const blue = mode === "blue";
  const purple = mode === "purple";
  const eventBased = blue || purple;
  const step = purple ? "coverage-comparison" : blue ? "event-review" : "scope-record-review";
  const conclusion = step + ".observation";
  const payload = eventBased ? eventContent : content;
  const sourceDigest = createHash("sha256").update(payload).digest("hex");
  const payloads = new Map([[sourceDigest, payload]]);
  if (purple) payloads.set(createHash("sha256").update(secondEventFile.buffer).digest("hex"), secondEventFile.buffer);
  const spec = { plan_id: plan, plan_hash: planHash, mode_id: mode, mode_version: 1, mode_digest: manifestDigest,
    valid_from: "2025-01-01T00:00:00Z", valid_until: "2030-01-01T00:00:00Z", purpose: "offline-review",
    allow_local_inference: !eventBased, sources: [...payloads].map(([digest, raw]) => ({ target_id: target, classification: "internal",
      capability: eventBased ? "event-review" : step, kind: eventBased ? "event-batch-v1" : "control-observations-v1",
      digest, size_bytes: raw.length })) };
  let requested = false;
  let allowed = false;
  const uploaded = new Set<string>();
  let isPublished = false;
  let deniedDownload = false;
  let decision: Decision | null = null;
  let state = "draft";
  let strategy = "deterministic";
  let proposalError: string | null = null;
  let reason: string | null = null;
  let resumed = false;
  const receipt = () => ({ step_id: step, reservation_id: reservation,
    state: state === "awaiting_review" ? "completed" : state === "cancelled" ? "blocked" : state,
    created_at: now, proposal_error: proposalError, reason, strategy });
  const publication = { analysis_id: analysis, report_digest: planHash, actor_id: "approver", published_at: now };

  async function install(page: Page, role: Role) {
    await page.route("**/api/v1/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const path = url.pathname.slice("/api/v1".length);
      const method = request.method();
      const json = (body: unknown, status = 200) => route.fulfill({ status, json: body });
      const fail = (code: string, status = 404) => json({ code }, status);
      const list = (items: unknown[] = []) => json({ items, next_cursor: null });
      if (method !== "GET") expect(request.headers()["x-csrf-token"]).toBe("csrf-" + role);
      if (path === "/me") return json({ user_id: role, source: "web", csrf_token: "csrf-" + role, permissions: roles[role] });
      if (path === "/auth/mode") return json({ mode: "oidc" });
      if (path === "/organizations") return list([{ id: org, slug: "equipo", state: "active", version: 1 }]);
      if (path === "/projects") return list([project, anotherProject].map((id, index) => ({
        id, org_id: org, slug: index ? "proyecto B" : "proyecto A", environment: "lab", state: "active", version: 1,
      })));
      if (path.startsWith(`/projects/${anotherProject}/`)) return list();
      expect(url.searchParams.get("org_id")).toBe(org);
      expect(path).toContain("/projects/" + project + "/");
      const resource = path.slice(project.length + "/projects//".length);
      if (["targets", "authorizations", "assessments"].includes(resource)) return list();
      if (resource === "team-selection") return json({ version: 8, selection: { mode_id: mode, mode_digest: manifestDigest, mode_version: 1 } });
      if (resource === "team-modes") return json({ items: [{ digest: manifestDigest, eligible_for_analysis: true,
        manifest: { id: mode, version: 1, label: purple ? "Purple Team" : blue ? "Blue Team" : "White Team",
          inputs: [eventBased ? "Eventos minimizados" : "Plan con decisión de alcance"],
          workflow: [{ id: step, kind: "capability", tool: step }] } }] });
      if (resource === "plans/" + plan) return json({ id: plan, hash: planHash, status: "reviewed", denials: [],
        authorization: { revision: 1, valid_from: spec.valid_from, valid_until: spec.valid_until },
        targets: [{ id: target, attribution: "first_party", reason: "allowed", canonical_address: "portal.example" }] });
      if (resource === "evidence-permissions" && method === "POST") {
        expect(role).toBe("operator");
        expect(request.postDataJSON()).toEqual(spec);
        expect(request.headers()["idempotency-key"]).toBeTruthy();
        requested = true;
        return json({ id: permission, revision: 1 }, 201);
      }
      if (resource === "evidence-permissions/" + permission) return !requested ? fail("evidence_permission_not_found")
        : json({ id: permission, revision: 1, requester_id: "operator", approver_id: allowed ? "approver" : null,
          status: allowed ? "approved" : "pending", spec });
      if (resource === `evidence-permissions/${permission}/decisions`) {
        expect(role).toBe("approver");
        expect(request.postDataJSON()).toEqual({ decision: "approve", reason: "Evidencia revisada", revision: 1 });
        allowed = true;
        return json({ status: "approved" });
      }
      const uploadPrefix = `evidence-permissions/${permission}/revisions/1/sources/`;
      if (resource.startsWith(uploadPrefix)) {
        const digest = resource.slice(uploadPrefix.length);
        expect(role).toBe("operator");
        expect(allowed).toBe(true);
        expect(request.headers()["content-type"]).toBe("application/json");
        expect(request.postDataBuffer()).toEqual(payloads.get(digest));
        uploaded.add(digest);
        return json({ source_digest: digest });
      }
      if (resource === "analyses" && method === "POST") {
        expect(uploaded.size).toBe(payloads.size);
        expect(request.postDataJSON()).toEqual({ permission_id: permission, permission_revision: 1,
          selection_version: 8, sources: [...payloads.keys()].sort(), ...(blue ? { event_rule: blueRule } : {}),
          ...(purple ? { coverage_scenario: coverageScenario } : {}) });
        return json({ id: analysis, snapshot_digest: planHash, created_at: now }, 201);
      }
      if (resource === "analyses/" + analysis) {
        expect(role).toBe("operator");
        return json({ id: analysis, plan_id: plan, plan_hash: planHash, mode_id: mode, mode_version: 1,
          selection_version: 8, snapshot_digest: planHash, created_at: now,
          state: isPublished && !deniedDownload ? "published" : state, cancelled_at: null,
          next_step: ["draft", "processing"].includes(state) ? step : null,
          steps: state === "draft" ? [] : [receipt()] });
      }
      if (resource === `analyses/${analysis}/steps/${step}`) {
        expect(role).toBe("operator");
        const posted = request.postDataJSON().strategy;
        expect(request.headers()["idempotency-key"]).toBe(`offline-${analysis}-${step}-${posted}`);
        if (posted === "assisted") return fail("proposal_dependency_missing", 503);
        expect(posted).toBe("deterministic");
        state = "awaiting_review";
        return json(receipt());
      }
      if (resource === `analyses/${analysis}/cancellation`) {
        expect(role).toBe("operator");
        expect(method).toBe("PUT");
        state = "cancelled";
        reason = "analysis_cancelled";
        return json({ id: analysis, state, cancelled_at: now });
      }
      if (resource === `analyses/${analysis}/review`) {
        expect(role).toBe("approver");
        if (state !== "awaiting_review") return fail("analysis_review_unavailable", 409);
        return json({ analysis_id: analysis, author_id: "operator", snapshot_digest: planHash,
          conclusions: [{ id: conclusion, status: blue ? "missing" : "observed", citations: [sourceDigest], observation: null,
            ...(blue ? { triage: { rule_id: blueRule, batches_evaluated: 1, matching_events: 0 } } : {}),
            ...(purple ? { coverage: { scenario_id: coverageScenario.scenario_id, target_id: target, detected: 1, evaluated: 2,
              rows: coverageScenario.checks.map((check, index) => ({
                ...check, status: ["detected", "not_detected", "no_data"][index], citations: index === 2 ? [] : [sourceDigest],
              })) } } : {}),
            provenance: { tool: step, mode_id: mode, mode_version: 1 } }], decisions: decision ? [decision] : [],
          publication: isPublished ? publication : null });
      }
      if (resource === `analyses/${analysis}/review/decisions/${conclusion}`) {
        expect(role).toBe("approver");
        decision = { ...request.postDataJSON(), conclusion_id: conclusion, actor_id: role, decided_at: now };
        return json(decision);
      }
      if (resource === `analyses/${analysis}/publication`) {
        expect(role).toBe("approver");
        expect(decision?.decision).toBe("approve");
        isPublished = true;
        return json(publication);
      }
      if (resource === `analyses/${analysis}/publication/report`) {
        if (role === "viewer" || !isPublished || deniedDownload) return fail("analysis_publication_not_found");
        return route.fulfill({ contentType: "text/html; charset=utf-8", body: "<h1>Informe de análisis offline</h1>" });
      }
      return fail("route_not_found");
    });
  }

  return { install, withdraw: () => { deniedDownload = true; },
    markProcessing: () => {
      resumed = true;
      state = "processing";
      strategy = "assisted";
    },
    finishProcessing: () => {
      expect(resumed).toBe(true);
      state = "awaiting_review";
      proposalError = "proposal_dependency_missing";
    },
    block: () => { state = "blocked"; reason = "plan_state_changed"; },
  };
}

async function checkAccessibility(page: Page) {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22a", "wcag22aa"]).analyze();
  expect(result.violations.map((item) => item.id)).toEqual([]);
}

test("operador, aprobador y lector completan el recorrido offline con sus permisos", async ({ page, browser }, testInfo) => {
  test.setTimeout(90_000);
  const scenario = fixture();
  await page.setViewportSize({ width: 360, height: 840 });
  await scenario.install(page, "operator");
  const reviewerContext = await browser.newContext({ viewport: { width: 360, height: 840 } });
  const viewerContext = await browser.newContext();
  const reviewer = await reviewerContext.newPage();
  const viewer = await viewerContext.newPage();
  try {
    await scenario.install(reviewer, "approver");
    await scenario.install(viewer, "viewer");
    await page.goto(link({ id: plan }));
    await expect(page.getByText("Plan con decisión de alcance")).toBeVisible();
    await checkAccessibility(page);
    await page.getByLabel("Activo autorizado").selectOption(target);
    await page.getByLabel("Archivo JSON de observaciones").setInputFiles(file);
    await page.getByLabel("Solicitar permiso de inferencia local").check();
    await page.getByRole("button", { name: "Solicitar permiso", exact: true }).click();
    await expect(page.getByText("En espera de aprobación del permiso.")).toBeVisible();
    await expect(page.getByRole("region", { name: "Análisis offline", exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Copiar enlace del permiso" })).toBeFocused();
    await expect(page.getByRole("button", { name: "Cargar evidencia" })).toHaveCount(0);
    await reviewer.goto(link({ permission }));
    await reviewer.getByLabel("Decisión del permiso").selectOption("approve");
    await reviewer.getByLabel("Motivo del permiso").fill("Evidencia revisada");
    await reviewer.getByRole("button", { name: "Registrar decisión del permiso" }).click();
    await expect(reviewer.getByText("Aprobado", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Actualizar permiso" }).click();
    await page.getByText(/^Fuente ·/).click();
    await page.getByLabel("Cargar archivo autorizado").setInputFiles({ ...file, buffer: Buffer.from("{}") });
    await page.getByRole("button", { name: "Cargar evidencia" }).click();
    await expect(page.getByRole("alert")).toContainText("debe coincidir");
    await page.getByLabel("Cargar archivo autorizado").setInputFiles(file);
    await page.getByRole("button", { name: "Cargar evidencia" }).click();
    await expect(page.getByText("Evidencia cargada.")).toBeVisible();
    await page.getByRole("button", { name: "Crear análisis offline" }).click();
    await expect(page.getByLabel("Modo de análisis")).toHaveValue("deterministic");
    await page.getByLabel("Modo de análisis").selectOption("assisted");
    await page.getByRole("button", { name: "Avanzar siguiente paso" }).click();
    await expect(page.getByRole("alert")).toContainText("El proveedor de inferencia local no está disponible.");
    await page.getByLabel("Modo de análisis").selectOption("deterministic");
    await page.getByRole("button", { name: "Avanzar siguiente paso" }).click();
    await expect(page.getByText("En espera de revisión", { exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByText("Paso confirmado", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Avanzar siguiente paso" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Revisión humana" })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(360);
    await checkAccessibility(page);
    await page.screenshot({ path: testInfo.outputPath("analisis-operador.png"), fullPage: true });

    await reviewer.goto(link({ analysis }));
    await expect(reviewer.getByRole("heading", { name: "Estado del análisis" })).toHaveCount(0);
    await expect(reviewer.getByRole("button", { name: "Publicar informe" })).toHaveCount(0);
    await reviewer.getByText("Referencias de evidencia (1)").click();
    await expect(reviewer.getByText(digest, { exact: true })).toBeVisible();
    await reviewer.getByLabel("Decisión de la conclusión").selectOption("approve");
    await reviewer.getByLabel("Motivo de la decisión").fill("Control revisado");
    await reviewer.getByRole("button", { name: "Registrar decisión", exact: true }).click();
    await reviewer.getByRole("button", { name: "Publicar informe" }).click();
    await expect(reviewer.getByText(/Informe publicado · SHA-256/)).toBeVisible();
    await reviewer.reload();
    await expect(reviewer.getByText(/Informe publicado · SHA-256/)).toBeVisible();
    await expect(reviewer.getByRole("button", { name: "Publicar informe" })).toHaveCount(0);
    expect(await reviewer.evaluate(() => document.documentElement.scrollWidth)).toBe(360);
    await checkAccessibility(reviewer);
    await reviewer.screenshot({ path: testInfo.outputPath("analisis-aprobador.png"), fullPage: true });
    for (const width of [768, 1440]) {
      await reviewer.setViewportSize({ width, height: 920 });
      expect(await reviewer.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
    }
    await reviewer.screenshot({ path: testInfo.outputPath("analisis-escritorio.png"), fullPage: true });

    const pending = page.waitForEvent("download");
    await page.reload();
    await expect(page.getByText("Publicado", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Cancelar análisis", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Descargar informe publicado" }).click();
    expect((await pending).suggestedFilename()).toBe(`analysis-${analysis}.html`);
    await viewer.goto(link({ analysis }));
    await expect(viewer.getByRole("heading", { name: "Estado del análisis" })).toHaveCount(0);
    await expect(viewer.getByRole("heading", { name: "Revisión humana" })).toHaveCount(0);
    await viewer.getByRole("button", { name: "Descargar informe publicado" }).click();
    await expect(viewer.getByRole("alert")).toContainText("tu cuenta ya no tiene acceso");
    scenario.withdraw();
    await page.getByRole("button", { name: "Descargar informe publicado" }).click();
    await expect(page.getByRole("alert")).toContainText("tu cuenta ya no tiene acceso");
  } finally {
    await reviewerContext.close();
    await viewerContext.close();
  }
});

test("Blue solicita el lote y muestra una ventana evaluada sin coincidencias", async ({ page, browser }) => {
  test.setTimeout(90_000);
  const scenario = fixture("blue");
  const reviewer = await browser.newPage();
  try {
    await scenario.install(page, "operator");
    await scenario.install(reviewer, "approver");
    await page.goto(link({ id: plan }));
    await expect(page.getByText(blueRule, { exact: true })).toBeVisible();
    await expect(page.getByLabel("Solicitar permiso de inferencia local")).toHaveCount(0);
    await page.getByLabel("Activo autorizado").selectOption(target);
    await page.getByLabel("Archivo JSON de eventos").setInputFiles(eventFile);
    await page.getByRole("button", { name: "Solicitar permiso", exact: true }).click();
    await expect(page.getByText("En espera de aprobación del permiso.")).toBeVisible();
    await reviewer.goto(link({ permission }));
    await reviewer.getByLabel("Decisión del permiso").selectOption("approve");
    await reviewer.getByLabel("Motivo del permiso").fill("Evidencia revisada");
    await reviewer.getByRole("button", { name: "Registrar decisión del permiso" }).click();
    await expect(reviewer.getByText("Aprobado", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Actualizar permiso" }).click();
    await page.getByText(/^Fuente ·/).click();
    await page.getByLabel("Cargar archivo autorizado").setInputFiles(eventFile);
    await page.getByRole("button", { name: "Cargar evidencia" }).click();
    await expect(page.getByText("Evidencia cargada.")).toBeVisible();
    await page.getByRole("button", { name: "Crear análisis offline" }).click();
    await expect(page.getByLabel("Modo de análisis")).toHaveValue("deterministic");
    await expect(page.getByRole("option", { name: "Inferencia local" })).toHaveCount(0);
    await page.getByRole("button", { name: "Avanzar siguiente paso" }).click();
    await expect(page.getByText("En espera de revisión", { exact: true })).toBeVisible();
    await reviewer.goto(link({ analysis }));
    await expect(reviewer.getByRole("heading", { name: "Triaje de eventos" })).toBeVisible();
    await expect(reviewer.getByText("No observado", { exact: true })).toBeVisible();
    await expect(reviewer.getByText("Eventos coincidentes", { exact: true })).toBeVisible();
  } finally {
    await reviewer.close();
  }
});

test("Purple congela el escenario y muestra resultados y fuentes por control", async ({ page, browser }) => {
  test.setTimeout(90_000);
  const scenario = fixture("purple");
  const reviewer = await browser.newPage();
  try {
    await scenario.install(page, "operator");
    await scenario.install(reviewer, "approver");
    await page.goto(link({ id: plan }));
    await page.getByLabel("Activo autorizado").selectOption(target);
    await page.getByLabel("Archivos JSON de eventos").setInputFiles([eventFile, secondEventFile]);
    await page.getByRole("button", { name: "Solicitar permiso", exact: true }).click();
    await expect(page.getByText("En espera de aprobación del permiso.")).toBeVisible();
    await reviewer.goto(link({ permission }));
    await reviewer.getByLabel("Decisión del permiso").selectOption("approve");
    await reviewer.getByLabel("Motivo del permiso").fill("Evidencia revisada");
    await reviewer.getByRole("button", { name: "Registrar decisión del permiso" }).click();
    await expect(reviewer.getByText("Aprobado", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Actualizar permiso" }).click();
    for (const file of [eventFile, secondEventFile]) {
      const digest = createHash("sha256").update(file.buffer).digest("hex");
      const source = page.locator("details").filter({ hasText: digest.slice(0, 12) });
      await source.getByText(/^Fuente ·/).click();
      await source.getByLabel("Cargar archivo autorizado").setInputFiles(file);
      await source.getByRole("button", { name: "Cargar evidencia" }).click();
      await expect(source.getByText("Evidencia cargada.")).toBeVisible();
    }
    const create = page.getByRole("button", { name: "Crear análisis offline" });
    await expect(create).toBeDisabled();
    await page.getByLabel("Escenario sintético de cobertura").setInputFiles({
      name: "escenario.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(coverageScenario)),
    });
    await create.click();
    await expect(page.getByRole("option", { name: "Inferencia local" })).toHaveCount(0);
    await page.getByRole("button", { name: "Avanzar siguiente paso" }).click();
    await expect(page.getByText("En espera de revisión", { exact: true })).toBeVisible();
    await reviewer.goto(link({ analysis }));
    await expect(reviewer.getByText(/1 de 2 controles evaluados detectados/)).toBeVisible();
    const matrix = reviewer.getByRole("region", { name: "Matriz de cobertura" });
    const hit = matrix.getByRole("row").filter({ has: reviewer.getByRole("rowheader", { name: /^hit/ }) });
    await expect(hit.getByText("Detectado", { exact: true })).toBeVisible();
    await hit.getByText("1 SHA-256").click();
    await expect(hit.getByText(createHash("sha256").update(eventContent).digest("hex"))).toBeVisible();
    await expect(matrix.getByText("No detectado", { exact: true })).toBeVisible();
    await expect(matrix.getByText("Sin datos suficientes", { exact: true })).toBeVisible();
  } finally {
    await reviewer.close();
  }
});

test("reanuda un paso en curso y distingue el bloqueo de la asistencia ausente", async ({ page }) => {
  const scenario = fixture();
  await scenario.install(page, "operator");
  scenario.markProcessing();
  await page.goto(link({ analysis }));
  await expect(page.getByText(/Paso en curso. El estado/)).toBeVisible();
  await page.reload();
  await expect(page.getByText(/Paso en curso. El estado/)).toBeVisible();
  scenario.finishProcessing();
  await expect(page.getByText(/Se conservó el resultado determinista/)).toBeVisible();
  scenario.block();
  await page.getByRole("button", { name: "Actualizar análisis" }).click();
  await expect(page.getByRole("list", { name: "Recibos de pasos" }).getByText("Bloqueado", { exact: true })).toBeVisible();
  await expect(page.getByText("El mandato o el alcance del plan cambió.")).toBeVisible();
  await page.getByRole("combobox", { name: "Proyecto", exact: true }).selectOption(anotherProject);
  await expect(page.getByRole("heading", { name: "Abrir análisis offline" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Estado del análisis" })).toHaveCount(0);
});

test("la cancelación exige confirmación y se recupera al recargar", async ({ page }) => {
  const scenario = fixture();
  await scenario.install(page, "operator");
  scenario.markProcessing();
  await page.goto(link({ analysis }));
  await page.getByRole("button", { name: "Cancelar análisis", exact: true }).click();
  await page.getByRole("button", { name: "Volver", exact: true }).click();
  await expect(page.getByText("En curso", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Cancelar análisis", exact: true }).click();
  await page.getByRole("button", { name: "Confirmar cancelación" }).click();
  await expect(page.getByText("Cancelado", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("Cancelado", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Avanzar siguiente paso" })).toHaveCount(0);
});
