import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Link, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, type Models } from "../api";
import { Status } from "../records";
import { Button, Card } from "../ui";
import { type ViewContext, write } from "./administration";
import { EvidencePermission, RequestEvidence } from "./analysis-evidence";
import { analysisError, analysisFailure, analysisPath, plannerLink, type PlannerReference } from "./analysis-links";
import { Form, required, uuid } from "./forms";

type Strategy = NonNullable<Models["AnalysisAdvance"]["strategy"]>;
const strategyNames: Record<Strategy, string> = { deterministic: "Determinista", assisted: "Inferencia local" };
const resultNames: Record<Models["AnalysisConclusion"]["status"], string> = {
  observed: "Observado", missing: "No observado", inconclusive: "Inconcluso",
};
const stepLabel = (id: string) => id === "scope-record-review" ? "Revisión de registros de alcance" : id;

export function OfflineAnalysis({ ctx, reference, plan, frozen }: {
  ctx: ViewContext; reference: PlannerReference | null; plan?: Models["Plan"]; frozen: boolean;
}) {
  const canRequest = ctx.permissions.includes("evidence:request");
  const canReview = ctx.permissions.includes("analyses:publish");
  const { id, permission, analysis } = reference ?? {};
  const region = useRef<HTMLElement>(null);
  const resource = analysis ?? permission;
  const previousResource = useRef(resource);
  useEffect(() => {
    if (resource && previousResource.current !== resource) region.current?.focus();
    previousResource.current = resource;
  }, [resource]);
  if (!ctx.permissions.includes("project:read") || (reference && (reference.org !== ctx.org || reference.project !== ctx.project))) return null;

  return <section ref={region} tabIndex={-1} className="section-stack offline-flow" aria-label="Análisis offline">
    {plan?.status === "reviewed" && !permission && !analysis && canRequest && !frozen && <RequestEvidence key={plan.id} ctx={ctx} plan={plan} />}
    {plan?.status === "blocked" && !permission && !analysis && canRequest && <Card className="form-card">
      <p>El plan está bloqueado. Se requiere un plan revisado para solicitar evidencia.</p>
    </Card>}
    {!analysis && !permission && <div className="feature-grid">
      <Form title="Abrir análisis offline" fields={[{ name: "id", label: "UUID del análisis", rule: uuid }]}
        label="Abrir análisis" action={async ({ id: selected }) => { location.hash = plannerLink(ctx, { id, analysis: selected }); }} />
      {(canRequest || canReview) && <Form title="Abrir permiso de evidencia"
        fields={[{ name: "id", label: "UUID del permiso", rule: uuid }]} label="Abrir permiso"
        action={async ({ id: selected }) => { location.hash = plannerLink(ctx, { id, permission: selected }); }} />}
    </div>}
    {permission && !analysis && (canRequest || canReview) && <>
      <div><ShareLink href={plannerLink(ctx, { id, permission })} label="Copiar enlace del permiso" /></div>
      <EvidencePermission key={permission} ctx={ctx} id={permission} planId={id} frozen={frozen} />
    </>}
    {permission && !analysis && !canRequest && !canReview && <Card className="form-card">
      <h2>Permiso de evidencia</h2><p>Tu rol no permite consultar solicitudes de evidencia.</p>
    </Card>}
    {analysis && <div className="section-stack">
      <Card className="form-card plan-result">
        <h2>Análisis offline</h2>
        <p>UUID del análisis <code>{analysis}</code></p>
        <div className="offline-actions">
          <ShareLink href={plannerLink(ctx, { analysis })} label="Copiar enlace del análisis" />
          {permission && canRequest && <Button asChild><a href={plannerLink(ctx, { id, permission })}>Volver al permiso de evidencia</a></Button>}
        </div>
      </Card>
      {canRequest && <AnalysisRun key={analysis} ctx={ctx} id={analysis} permissionId={permission} frozen={frozen} />}
      {canReview && <AnalysisReview key={analysis} ctx={ctx} id={analysis} />}
      <DownloadReport key={"report-" + analysis} ctx={ctx} id={analysis} />
    </div>}
  </section>;
}

function ShareLink({ href, label }: { href: string; label: string }) {
  const copy = useMutation({ mutationFn: () => navigator.clipboard.writeText(new URL(href, location.href).href) });
  return <>
    <Button onClick={() => copy.mutate()}><Link size={16} aria-hidden /> {label}</Button>
    {copy.isSuccess && <span role="status">Enlace copiado.</span>}
    {copy.error && <span role="alert">Copia el enlace desde la barra de direcciones.</span>}
  </>;
}

function AnalysisRun({ ctx, id, permissionId, frozen }: { ctx: ViewContext; id: string; permissionId?: string; frozen: boolean }) {
  const [strategy, setStrategy] = useState<Strategy>("deterministic");
  const [confirmCancellation, setConfirmCancellation] = useState(false);
  const cache = useQueryClient();
  const key = ["project-data", ctx.user, ctx.org, ctx.project, "offline-analysis", id];
  const path = `analyses/${id}`;
  const run = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => api<Models["AnalysisDetail"]>(analysisPath(ctx, path), { signal }),
    refetchInterval: (query) => query.state.data?.state === "processing" ? 2_000 : false,
    retry: false,
  });
  const permission = useQuery({
    queryKey: ["project-data", ctx.user, ctx.org, ctx.project, "evidence-permission", permissionId],
    enabled: Boolean(permissionId),
    queryFn: ({ signal }) => api<Models["PermissionDetail"]>(analysisPath(ctx, `evidence-permissions/${permissionId}`), { signal }),
    retry: false,
  });
  const refresh = () => cache.invalidateQueries({ queryKey: key, exact: true });
  const advance = useMutation({
    mutationFn: ({ step, selected }: { step: string; selected: Strategy }) => api<Models["AnalysisStepReceipt"]>(
      analysisPath(ctx, `${path}/steps/${encodeURIComponent(step)}`), {
        method: "POST", body: JSON.stringify({ strategy: selected } satisfies Models["AnalysisAdvance"]),
        headers: { "Content-Type": "application/json", "X-CSRF-Token": ctx.csrf,
          "Idempotency-Key": `offline-${id}-${step}-${selected}` },
      }),
    onSettled: refresh,
  });
  const cancel = useMutation({
    mutationFn: () => write(ctx.csrf, analysisPath(ctx, path + "/cancellation"), undefined, "PUT"),
    onSettled: refresh,
  });
  const detail = run.data;
  if (run.isError) return <Card className="form-card"><p role="alert">{analysisFailure(run.error)}</p>
    <Button onClick={() => { void run.refetch(); }}>Actualizar análisis</Button></Card>;
  if (!detail) return <p role="status">Cargando análisis…</p>;
  const runnable = !frozen && (detail.state === "draft" || detail.state === "ready") && detail.next_step;
  const allowInference = !permission.isError && permission.data?.spec.allow_local_inference &&
    permission.data.spec.plan_id === detail.plan_id && permission.data.spec.plan_hash === detail.plan_hash &&
    permission.data.status === "approved" && Date.parse(permission.data.spec.valid_until) > Date.now() &&
    Date.parse(permission.data.spec.valid_from) <= Date.now();
  const selected = allowInference ? strategy : "deterministic";
  const busy = advance.isPending || cancel.isPending;
  const mode = detail.mode_id.charAt(0).toUpperCase() + detail.mode_id.slice(1) + " Team";
  return <Card className="form-card plan-result">
    <div className="panel-title"><h2>Estado del análisis</h2><Status state={detail.state} /></div>
    <p>Especialidad guardada · {mode} · Versión {detail.mode_version}</p>
    <div className="offline-actions">
      <Button asChild><a href={plannerLink(ctx, { id: detail.plan_id })}>Consultar plan de origen</a></Button>
      <Button onClick={() => { void run.refetch(); }}><RefreshCw size={16} aria-hidden /> Actualizar análisis</Button>
    </div>
    {detail.state === "processing" && <p role="status">Paso en curso. El estado se actualizará automáticamente.</p>}
    {detail.state === "awaiting_review" && <p role="status">Comparte el enlace con el aprobador del permiso para revisar las conclusiones.</p>}
    {frozen && <p>El proyecto archivado no admite avances.</p>}
    {detail.steps.length > 0 && <ol className="offline-steps" aria-label="Recibos de pasos">
      {detail.steps.map((step) => <li key={step.reservation_id ?? step.step_id + step.created_at}>
        <div className="panel-title"><strong>{stepLabel(step.step_id)}</strong><Status state={step.state} /></div>
        <p>{strategyNames[step.strategy]}</p>
        {step.reason && <p role="status">{analysisError(step.reason)}</p>}
        {step.proposal_error && <p role="status">{analysisError(step.proposal_error)} Se conservó el resultado determinista.</p>}
      </li>)}
    </ol>}
    {runnable && <div className="offline-actions">
      <label className="input-field">Modo de análisis
        <select value={selected} disabled={busy} onChange={(event) => {
          advance.reset();
          setStrategy(event.target.value === "assisted" ? "assisted" : "deterministic");
        }}>
          <option value="deterministic">Determinista</option>
          {allowInference && <option value="assisted">Inferencia local</option>}
        </select>
      </label>
      <Button variant="primary" disabled={busy} onClick={() => advance.mutate({ step: runnable, selected })}>
        {advance.isPending ? "Avanzando…" : "Avanzar siguiente paso"}
      </Button>
    </div>}
    {(detail.state === "draft" || detail.state === "ready" || detail.state === "processing" || detail.state === "awaiting_review") &&
      <div className="offline-actions">{confirmCancellation ? <>
        <p>Se descartará cualquier paso en curso.</p>
        <Button disabled={cancel.isPending} onClick={() => cancel.mutate(undefined, {
          onSuccess: () => setConfirmCancellation(false),
        })}>Confirmar cancelación</Button>
        <Button disabled={cancel.isPending} onClick={() => setConfirmCancellation(false)}>Volver</Button>
      </> : <Button onClick={() => setConfirmCancellation(true)}>Cancelar análisis</Button>}</div>}
    {(advance.error || cancel.error) && <p role="alert">{analysisFailure((advance.error || cancel.error)!)}</p>}
  </Card>;
}

function AnalysisReview({ ctx, id }: { ctx: ViewContext; id: string }) {
  const cache = useQueryClient();
  const key = ["project-data", ctx.user, ctx.org, ctx.project, "analysis-review", id];
  const path = `analyses/${id}`;
  const review = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => api<Models["AnalysisReview"]>(analysisPath(ctx, path + "/review"), { signal }),
    retry: false,
  });
  const publish = useMutation({
    mutationFn: () => write<Models["AnalysisPublication"]>(ctx.csrf, analysisPath(ctx, path + "/publication"), undefined, "PUT"),
  });
  const data = review.data;
  const publication = !review.isError ? publish.data ?? data?.publication : null;
  const waiting = review.error instanceof ApiError && review.error.code === "analysis_review_unavailable";
  return <div className="section-stack">
    <Card className="form-card plan-result">
      <h2>Revisión humana</h2>
      {review.isPending && <p role="status">Cargando conclusiones…</p>}
      {review.error && <p role={waiting ? "status" : "alert"}>{analysisFailure(review.error)}</p>}
      {data && !review.isError && <p>{data.decisions.length} de {data.conclusions.length} conclusiones con decisión.</p>}
      <div className="offline-actions">
        <Button onClick={() => { void review.refetch(); }}>Actualizar revisión</Button>
        {!publication && data && !review.isError && data.conclusions.length > 0 && data.decisions.length === data.conclusions.length &&
          <Button variant="primary" onClick={() => publish.mutate()} disabled={publish.isPending}>
            {publish.isPending ? "Publicando…" : "Publicar informe"}
          </Button>}
      </div>
      {publish.error && <p role="alert">{analysisFailure(publish.error)}</p>}
      {publication && <p role="status">Informe publicado · SHA-256 <code>{publication.report_digest}</code></p>}
    </Card>
    {!review.isError && data?.conclusions.map((conclusion) => {
      const decision = data.decisions.find((item) => item.conclusion_id === conclusion.id);
      return <Card className="form-card plan-result" key={conclusion.id}>
        <h2>{conclusion.observation ? "Control · " + conclusion.observation.control : "Observación del alcance"}</h2>
        <p>{resultNames[conclusion.status]} · {stepLabel(conclusion.provenance.tool)}</p>
        {conclusion.citations.length > 0 && <details><summary>Referencias de evidencia ({conclusion.citations.length})</summary>
          <ul>{conclusion.citations.map((citation) => <li key={citation}><code>{citation}</code></li>)}</ul></details>}
        {decision ? <p>Decisión registrada · {decision.decision === "approve" ? "Aprobada" : "Rechazada"} · {decision.reason}</p>
          : <div className="offline-decision">
            <Form title={"Decidir conclusión · " + conclusion.id} fields={[
              { name: "decision", label: "Decisión de la conclusión", rule: required,
                options: [{ value: "approve", label: "Aprobar" }, { value: "reject", label: "Rechazar" }] },
              { name: "reason", label: "Motivo de la decisión", rule: required.max(500) },
            ]} label="Registrar decisión" action={({ decision: value, reason }) =>
              write(ctx.csrf, analysisPath(ctx, `${path}/review/decisions/${encodeURIComponent(conclusion.id)}`), { decision: value, reason }, "PUT")
            } completed={() => { void cache.invalidateQueries({ queryKey: key, exact: true }); }} />
          </div>}
      </Card>;
    })}
  </div>;
}

function DownloadReport({ ctx, id }: { ctx: ViewContext; id: string }) {
  const download = useMutation({
    mutationFn: async () => {
      const response = await fetch("/api/v1" + analysisPath(ctx, `analyses/${id}/publication/report`), { credentials: "same-origin" });
      if (!response.ok) {
        const problem = await response.json().catch(() => null) as { code?: string } | null;
        throw new ApiError(response.status, problem?.code);
      }
      if (!response.headers.get("content-type")?.startsWith("text/html")) throw new Error("El informe no tiene un formato válido.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `analysis-${id}.html`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  return <Card className="form-card">
    <h2>Informe de análisis</h2>
    <Button onClick={() => download.mutate()} disabled={download.isPending}>
      <Download size={16} aria-hidden /> {download.isPending ? "Descargando…" : "Descargar informe publicado"}
    </Button>
    {download.error && <p role="alert">{analysisFailure(download.error)}</p>}
  </Card>;
}
