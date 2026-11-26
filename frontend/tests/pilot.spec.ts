import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const origin = process.env.PENTEST_AGENT_E2E_ORIGIN;
const bootstrap = process.env.PENTEST_AGENT_E2E_BOOTSTRAP;
const compose = process.env.PENTEST_AGENT_E2E_PROJECT;
const password = "Fixture-only-passphrase_123!";
const repository = fileURLToPath(new URL("../..", import.meta.url));

function cli(args: string[], input?: string) {
  return JSON.parse(execFileSync("docker", [
    "compose", "-p", compose!, "run", "--rm", "-T", "cli", ...args,
  ], { cwd: repository, input, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"] }));
}

function panel(page: Page, name: string) {
  return page.locator("section").filter({ has: page.getByRole("heading", { name, exact: true }) });
}

async function signIn(page: Page, username: string) {
  await page.getByLabel("Usuario", { exact: true }).fill(username);
  await page.getByLabel("Contraseña", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Iniciar sesión", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Resumen", exact: true })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Cerrar sesión" }).click();
  await expect(page.getByRole("heading", { name: "Accede a tu espacio" })).toBeVisible();
}

async function go(page: Page, name: string) {
  await page.getByRole("navigation").getByRole("link", { name, exact: true }).click();
}

test("piloto real: altas, vigencia, roles y el mismo plan en web y CLI", async ({ page }) => {
  test.skip(!origin || !bootstrap || !compose, "Requiere un Compose piloto nuevo");
  test.setTimeout(180_000);
  page.setDefaultTimeout(15_000);
  await page.goto(origin!);
  await page.getByRole("button", { name: "Primer acceso" }).click();
  await page.getByLabel("Código inicial").fill(bootstrap!);
  await page.getByLabel("Usuario", { exact: true }).fill("platform");
  await page.getByLabel("Contraseña", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Crear primer administrador" }).click();
  await expect(page.getByRole("heading", { name: "Resumen", exact: true })).toBeVisible();
  await go(page, "Gestión");

  const account = panel(page, "Cuenta local del piloto");
  async function accountId(username: string) {
    await account.getByLabel("Nombre de usuario").fill(username);
    await account.getByLabel("Contraseña de la cuenta").fill(password);
    const response = page.waitForResponse((result) =>
      result.url().endsWith("/api/v1/auth/local/accounts") && result.request().method() === "POST");
    await account.getByRole("button", { name: "Crear cuenta local" }).click();
    const result = await response;
    expect(result.status()).toBe(201);
    return (await result.json()).user_id as string;
  }
  const admin = await accountId("orgadmin");
  const operator = await accountId("operator");
  const approver = await accountId("approver");
  const organization = panel(page, "Nueva organización");
  await organization.getByLabel("Identificador de organización").fill("pilot-lab");
  await organization.getByLabel("UUID del administrador inicial").fill(admin);
  const orgCreated = page.waitForResponse((response) =>
    response.url().endsWith("/api/v1/organizations") && response.request().method() === "POST");
  await organization.getByRole("button", { name: "Crear organización" }).click();
  const orgResponse = await orgCreated;
  expect(orgResponse.status()).toBe(201);
  const org = (await orgResponse.json()).id as string;

  await signOut(page);
  await signIn(page, "orgadmin");
  await go(page, "Gestión");
  const customer = panel(page, "Nuevo cliente");
  await customer.getByLabel("Identificador del cliente").fill("internal");
  await customer.getByLabel("Nombre del cliente").fill("Equipo piloto");
  await customer.getByRole("button", { name: "Crear cliente" }).click();
  const project = panel(page, "Nuevo proyecto");
  await project.getByLabel("Identificador del proyecto").fill("pilot-review");
  await project.getByLabel("Cliente", { exact: true }).selectOption({ label: "Equipo piloto" });
  await project.getByLabel("Entorno").fill("lab");
  const projectCreated = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/api/v1/projects") && response.request().method() === "POST");
  await project.getByRole("button", { name: "Crear proyecto" }).click();
  const projectResponse = await projectCreated;
  expect(projectResponse.status()).toBe(201);
  const projectId = (await projectResponse.json()).id as string;
  await expect(panel(page, "Membresía de proyecto")).toBeVisible();

  async function assign(group: string, user: string, role: string) {
    const form = panel(page, group);
    await form.getByLabel("UUID del usuario").fill(user);
    await form.getByLabel("Rol", { exact: true }).selectOption(role);
    const response = page.waitForResponse((result) =>
      new URL(result.url()).pathname.endsWith("/api/v1/memberships") && result.request().method() === "PUT");
    await form.getByRole("button", { name: "Guardar membresía" }).click();
    expect((await response).status()).toBe(200);
  }
  await assign("Membresía de organización", operator, "member");
  await assign("Membresía de organización", approver, "member");
  await assign("Membresía de proyecto", operator, "operator");
  await assign("Membresía de proyecto", approver, "approver");

  await signOut(page);
  await signIn(page, "operator");
  await go(page, "Activos");
  const target = panel(page, "Nuevo activo");
  await target.getByLabel("Identificador del activo").fill("inventory-asset");
  await target.getByLabel("Host, IP o URL").fill("https://lab.example/");
  await target.getByLabel("Entorno").fill("lab");
  await target.getByLabel("Titularidad").selectOption("first_party");
  await target.getByRole("button", { name: "Registrar activo" }).click();
  await expect(page.getByRole("cell", { name: "inventory-asset" })).toBeVisible();

  await go(page, "Evaluaciones");
  await page.getByLabel("Nombre de la evaluación").fill("Validación documental");
  await page.getByRole("button", { name: "Registrar evaluación" }).click();
  await expect(page.getByRole("cell", { name: "Validación documental" })).toBeVisible();

  await go(page, "Autorizaciones");
  await page.getByLabel("Documento PDF del mandato").setInputFiles({
    name: "pilot.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\nSynthetic pilot\n%%EOF"),
  });
  await page.getByLabel("UUID de quien delega").fill(admin);
  const local = (offset: number) => new Date(Date.now() + offset * 3600_000).toISOString().slice(0, 16);
  await page.getByLabel("Inicio de vigencia").fill(local(-2));
  await page.getByLabel("Fin de vigencia").fill(local(-1));
  await page.getByLabel("Tipo de alcance").selectOption("fqdn");
  await page.getByLabel("Destino autorizado").fill("lab.example");
  await page.getByRole("button", { name: "Registrar solicitud" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "La vigencia debe terminar en el futuro" })).toBeVisible();
  await page.getByLabel("Fin de vigencia").fill(local(2));
  await page.getByRole("button", { name: "Registrar solicitud" }).click();
  await expect(page.getByText("Borrador", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Aprobar autorización" })).toHaveCount(0);

  const list = async (resource: string) => {
    const response = await page.request.get(origin + "/api/v1/projects/" + projectId + "/" + resource + "?org_id=" + org);
    expect(response.ok()).toBeTruthy();
    return (await response.json()).items;
  };
  const auth = (await list("authorizations"))[0];
  const evaluation = (await list("assessments"))[0];
  const asset = (await list("targets"))[0];
  await go(page, "Planificador");
  await page.getByLabel("inventory-asset").check();
  await page.getByLabel("Evaluación", { exact: true }).selectOption(evaluation.id);
  await page.getByLabel("Revisión de autorización").selectOption(auth.id);
  await page.getByRole("button", { name: "Simular plan" }).click();
  await expect(page.getByText("Autorización pendiente de aprobación", { exact: true }).first()).toBeVisible();

  await signOut(page);
  await signIn(page, "approver");
  await go(page, "Autorizaciones");
  await expect(page.getByRole("heading", { name: "Solicitar autorización" })).toHaveCount(0);
  await page.getByLabel("Autorización", { exact: true }).selectOption(auth.id);
  await page.getByLabel("Motivo").fill("Documento del piloto revisado");
  await page.getByRole("button", { name: "Registrar decisión" }).click();
  await expect(page.getByRole("heading", { name: "Revocar autorización" })).toBeVisible();

  expect(cli(["status"]).ready.status).toBe("ready");
  expect(cli(["auth", "login", "--username", "operator", "--password-stdin"], password + "\n").session).toBe("active");
  const exampleArgs = ["lab", "seed", "--org-id", org, "--project-id", projectId];
  expect(cli(exampleArgs).id).toBe(asset.id);
  expect(cli(exampleArgs).id).toBe(asset.id);
  const plan = cli(["plan", "create", "--org-id", org, "--project-id", projectId, "--assessment-id", evaluation.id,
    "--authorization-id", auth.id, "--revision", "1", "--target-id", asset.id]);
  expect(plan.status).toBe("reviewed");
  await page.goto(plan.browser_url);
  await expect(page.getByRole("heading", { name: "Plan " + plan.id })).toBeVisible();
  await expect(page.getByText("Revisado", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Simular plan" })).toHaveCount(0);
  expect(cli(["plan", "show", "--org-id", org, "--project-id", projectId, "--plan-id", plan.id]).hash).toBe(plan.hash);
  const link = page.getByRole("link", { name: "Descargar informe HTML" });
  await expect(link).toBeVisible();
  const reportPath = (await link.getAttribute("href"))!;
  const stored = await page.request.get(origin + reportPath);
  expect(stored.ok()).toBeTruthy();
  expect(await stored.text()).toContain(plan.hash);

  await signOut(page);
  await signIn(page, "orgadmin");
  const teamArgs = ["--org-id", org, "--project-id", projectId];
  const selectionUrl = origin + "/api/v1/projects/" + projectId + "/team-selection?org_id=" + org;
  const denied = await page.request.put(selectionUrl, {
    headers: { Origin: origin!, "If-Match": '"0"' }, data: { mode_id: "red" },
  });
  expect(denied.status()).toBe(403);
  expect((await denied.json()).code).toBe("csrf_denied");
  await page.getByLabel("Elegir especialidad").selectOption("red");
  await page.getByRole("button", { name: "Guardar especialidad" }).click();
  await expect(page.getByText("Selección guardada · Red Team")).toBeVisible();
  expect(cli(["project", "team-show", ...teamArgs]).selection.mode_id).toBe("red");
  expect(cli(["auth", "login", "--username", "orgadmin", "--password-stdin"], password + "\n").session).toBe("active");
  const rainbow = cli(["project", "team-select", ...teamArgs, "--mode", "rainbow", "--version", "1"]);
  expect(rainbow.selection.mode_id).toBe("rainbow");
  await page.reload();
  await expect(page.getByText("Selección guardada · Rainbow Team")).toBeVisible();
  await page.getByLabel("Elegir especialidad").selectOption("blue");
  await page.getByRole("button", { name: "Guardar especialidad" }).click();
  await expect(page.getByText("Selección guardada · Blue Team")).toBeVisible();
  expect(cli(["auth", "login", "--username", "operator", "--password-stdin"], password + "\n").session).toBe("active");
  await page.goto(plan.browser_url);
  await expect(page.getByRole("heading", { name: "Plan " + plan.id })).toBeVisible();

  const repeat = await page.request.post(origin + "/api/v1/bootstrap/redeem", {
    headers: { Origin: origin! }, data: { code: bootstrap, username: "secondadmin", password },
  });
  expect(repeat.status()).toBe(409);
  const docker = (...args: string[]) => execFileSync("docker", args, {
    cwd: repository, encoding: "utf8", stdio: ["pipe", "pipe", "pipe"], timeout: 90_000,
  });
  const prefix = ["compose", "-p", compose!];
  const database = docker(...prefix, "ps", "-q", "postgres").trim();
  const ports = JSON.parse(docker("inspect", database, "--format", "{{json .NetworkSettings.Ports}}"));
  expect(ports["5432/tcp"]).toBeNull();
  docker(...prefix, "down");
  docker(...prefix, "up", "-d", "--wait", "--wait-timeout", "60");

  const persisted = await page.request.get(origin + "/api/v1/projects/" + projectId + "/plans/" + plan.id + "?org_id=" + org);
  expect(persisted.ok()).toBeTruthy();
  expect((await persisted.json()).hash).toBe(plan.hash);
  const reportAfterRestart = await page.request.get(origin + reportPath);
  expect(await reportAfterRestart.body()).toEqual(await stored.body());
  expect(cli(["project", "team-show", ...teamArgs]).selection.mode_id).toBe("blue");
  const verifyResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname.endsWith("/plans/" + plan.id + "/verify"));
  await page.getByRole("button", { name: "Verificar vigencia" }).click();
  const verified = await verifyResponse;
  expect(verified.status()).toBe(200);
  expect(await verified.json()).toMatchObject({ status: "verified", execution: "disabled", hash: plan.hash });
  expect(cli(["auth", "whoami"]).user_id).toBe(operator);
  expect(cli(["auth", "logout"]).session).toBe("closed");

  await go(page, "Resumen");
  await page.getByLabel("Elegir especialidad").selectOption("white");
  await page.getByRole("button", { name: "Guardar especialidad" }).click();
  await expect(page.getByText("Selección guardada · White Team")).toBeVisible();
  await signOut(page);
  await signIn(page, "operator");
  await page.goto(plan.browser_url);
  const evidence = { name: "observaciones.json", mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify({ target_id: asset.id, observations: [{ control: "logging", result: "observed" }] })) };
  await page.getByLabel("Activo autorizado").selectOption(asset.id);
  await page.getByLabel("Archivo JSON de observaciones").setInputFiles(evidence);
  await page.getByRole("button", { name: "Solicitar permiso", exact: true }).click();
  await expect(page.getByText("En espera de aprobación del permiso.")).toBeVisible();
  const permissionUrl = page.url();

  await signOut(page);
  await signIn(page, "approver");
  await page.goto(permissionUrl);
  await page.getByLabel("Decisión del permiso").selectOption("approve");
  await page.getByLabel("Motivo del permiso").fill("Observaciones autorizadas");
  await page.getByRole("button", { name: "Registrar decisión del permiso" }).click();
  await expect(page.getByText("Aprobado", { exact: true })).toBeVisible();

  await signOut(page);
  await signIn(page, "operator");
  await page.goto(permissionUrl);
  await page.getByText(/^Fuente ·/).click();
  await page.getByLabel("Cargar archivo autorizado").setInputFiles(evidence);
  await page.getByRole("button", { name: "Cargar evidencia" }).click();
  await expect(page.getByText("Evidencia cargada.")).toBeVisible();
  await page.getByRole("button", { name: "Crear análisis offline" }).click();
  await expect(page.getByLabel("Modo de análisis")).toHaveValue("deterministic");
  await page.getByRole("button", { name: "Avanzar siguiente paso" }).click();
  await expect(page.getByText("En espera de revisión", { exact: true })).toBeVisible();
  const analysisUrl = page.url();
  await page.reload();
  await expect(page.getByText("Paso confirmado", { exact: true })).toBeVisible();

  await signOut(page);
  await signIn(page, "approver");
  await page.goto(analysisUrl);
  await page.getByLabel("Decisión de la conclusión").selectOption("approve");
  await page.getByLabel("Motivo de la decisión").fill("Control revisado en el piloto");
  await page.getByRole("button", { name: "Registrar decisión", exact: true }).click();
  await page.getByRole("button", { name: "Publicar informe" }).click();
  await expect(page.getByText(/Informe publicado · SHA-256/)).toBeVisible();

  await signOut(page);
  await signIn(page, "operator");
  await page.goto(analysisUrl);
  await expect(page.getByText("Publicado", { exact: true })).toBeVisible();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Descargar informe publicado" }).click();
  expect((await downloaded).suggestedFilename()).toMatch(/^analysis-.+\.html$/);

  await test.info().attach("persisted-plan", { body: JSON.stringify({ org, project: projectId, plan: plan.id }),
    contentType: "application/json" });
});
