import { api, ApiError } from "../api";
import { contextPath, type ViewContext } from "./administration";
import { failure, uuid } from "./forms";

export type PlannerReference = {
  org: string;
  project: string;
  id?: string;
  permission?: string;
  analysis?: string;
};

export function planLocation(): PlannerReference | null {
  if (!location.hash.startsWith("#plan?")) return null;
  const params = new URLSearchParams(location.hash.slice(6));
  const org = params.get("org"), project = params.get("project"), id = params.get("id");
  const permission = uuid.safeParse(params.get("permission")).data;
  const analysis = uuid.safeParse(params.get("analysis")).data;
  return org && project && (id || permission || analysis)
    ? { org, project, id: id || undefined, permission, analysis } : null;
}

export function plannerLink(ctx: ViewContext, refs: Omit<PlannerReference, "org" | "project">) {
  const params = new URLSearchParams({ org: ctx.org, project: ctx.project });
  for (const [key, value] of Object.entries(refs)) if (value) params.set(key, value);
  return "#plan?" + params;
}

export function analysisPath(ctx: ViewContext, path: string) {
  return contextPath("/projects/" + encodeURIComponent(ctx.project) + "/" + path, ctx.org);
}

export async function sha256(value: ArrayBuffer) {
  const bytes = await crypto.subtle.digest("SHA-256", value);
  return Array.from(new Uint8Array(bytes), (part) => part.toString(16).padStart(2, "0")).join("");
}

export async function createWithReceipt<T>(ctx: ViewContext, path: string, body: unknown) {
  const serialized = JSON.stringify(body);
  const digest = await sha256(new TextEncoder().encode(serialized).buffer);
  const entry = ["kronshield-create", ctx.user, ctx.org, ctx.project, path, digest].join("/");
  let key: string = crypto.randomUUID();
  try {
    key = sessionStorage.getItem(entry) ?? key;
    sessionStorage.setItem(entry, key);
  } catch {
    // An unavailable browser store does not block the request.
  }
  const result = await api<T>(analysisPath(ctx, path), {
    method: "POST", headers: { "X-CSRF-Token": ctx.csrf, "Content-Type": "application/json", "Idempotency-Key": key },
    body: serialized,
  });
  try { sessionStorage.removeItem(entry); } catch { /* Storage is optional. */ }
  return result;
}

const explanations: Record<string, string> = {
  analysis_busy: "Hay un paso en curso. Consulta el estado antes de reintentar.",
  analysis_project_busy: "El proyecto alcanzó el límite de análisis en curso. Intenta más tarde.",
  analysis_review_unavailable: "La revisión estará disponible al terminar el análisis.",
  analysis_review_not_found: "La revisión no está disponible para tu cuenta.",
  analysis_not_found: "El análisis no está disponible para tu cuenta en este proyecto.",
  analysis_publication_not_found: "El informe aún no se publicó o tu cuenta ya no tiene acceso.",
  analysis_transition_invalid: "El estado cambió. Actualiza el análisis antes de avanzar.",
  analysis_step_timeout: "La reserva del paso venció. El resultado se descartó.",
  analysis_budget_exceeded: "El paso supera el presupuesto del análisis.",
  analysis_evidence_missing: "Falta evidencia autorizada para este paso.",
  analysis_capability_unavailable: "La capacidad offline de este paso aún no está disponible.",
  analysis_event_review_deterministic: "El triaje de eventos solo admite el modo determinista.",
  analysis_event_rule_not_applicable: "La regla de eventos corresponde a Blue Team.",
  analysis_coverage_deterministic: "La cobertura de detección solo admite el modo determinista.",
  analysis_coverage_scenario_required: "Adjunta el escenario sintético de cobertura.",
  analysis_coverage_scenario_not_applicable: "El escenario de cobertura corresponde a Purple Team.",
  analysis_coverage_source_mismatch: "Los lotes Blue deben corresponder al activo del escenario.",
  analysis_selection_changed: "La selección del proyecto cambió. Actualiza el planificador antes de crear un análisis.",
  analysis_cancelled: "Este análisis está cancelado.",
  analysis_already_published: "El análisis ya está publicado.",
  analysis_decisions_incomplete: "Registra una decisión para cada conclusión antes de publicar.",
  analysis_decision_conflict: "La conclusión ya tiene una decisión registrada.",
  analysis_stop_changed: "El interruptor de la organización cambió desde la creación.",
  evidence_disposed: "La evidencia fue retirada o venció.",
  evidence_not_found: "Falta una fuente autorizada. Carga el archivo si corresponde.",
  evidence_permission_inactive: "El permiso de evidencia ya no está vigente.",
  evidence_permission_not_found: "El permiso no está disponible para tu cuenta en este proyecto.",
  evidence_revision_changed: "Cambió la revisión del permiso. Actualiza el permiso antes de continuar.",
  evidence_purpose_denied: "El permiso no incluye el uso de esta evidencia para inferencia local.",
  plan_state_changed: "El mandato o el alcance del plan cambió.",
  project_archived: "El proyecto está archivado.",
  proposal_dependency_missing: "El proveedor de inferencia local no está disponible.",
  proposal_provider_timeout: "El proveedor de inferencia local superó el tiempo de espera.",
  proposal_provider_failed: "El proveedor de inferencia local falló.",
  proposal_budget_exceeded: "La propuesta superó el presupuesto permitido.",
  proposal_invalid: "La propuesta de inferencia no pasó la validación.",
};

export function analysisError(code: string) {
  return explanations[code] ?? "El servidor rechazó este paso del análisis.";
}

export function analysisFailure(error: Error) {
  return error instanceof ApiError && explanations[error.code] ? analysisError(error.code) : failure(error);
}
