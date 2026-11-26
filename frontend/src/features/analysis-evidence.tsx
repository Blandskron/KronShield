import { useMutation, useQuery } from "@tanstack/react-query";
import { useId, useState } from "react";
import { api, type Models } from "../api";
import { Status } from "../records";
import { Button, Card } from "../ui";
import { analysisFailure, analysisPath, createWithReceipt, plannerLink, sha256 } from "./analysis-links";
import { type ViewContext, write } from "./administration";
import { Form, required } from "./forms";

const MAX_BYTES = 1024 * 1024;
const BLUE_RULE = "identity-login-failure-v1";
type Permission = Models["PermissionDetail"];
type Source = Models["Source"];

export function RequestEvidence({ ctx, plan }: { ctx: ViewContext; plan: Models["Plan"] }) {
  const [target, setTarget] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [classification, setClassification] = useState<Models["Classification"]>("internal");
  const [localInference, setLocalInference] = useState(false);
  const scope = ["project-data", ctx.user, ctx.org, ctx.project];
  const selection = useQuery({
    queryKey: [...scope, "team-selection"],
    queryFn: ({ signal }) => api<Models["TeamSelection"]>(analysisPath(ctx, "team-selection"), { signal }),
  });
  const catalog = useQuery({
    queryKey: [...scope, "team-modes"],
    queryFn: ({ signal }) => api<Models["TeamModes"]>(analysisPath(ctx, "team-modes"), { signal }),
  });
  const chosen = selection.data?.selection;
  const mode = catalog.data?.items.find((entry) => entry.digest === chosen?.mode_digest &&
    entry.manifest.id === chosen.mode_id && entry.manifest.version === chosen.mode_version);
  const blue = mode?.manifest.id === "blue";
  const purple = mode?.manifest.id === "purple";
  const events = blue || purple;
  const supported = events || mode?.manifest.id === "white";
  const targets = plan.targets.filter((item) => item.attribution === "first_party" && item.reason === "allowed");
  const submit = useMutation({
    mutationFn: async () => {
      if (!targets.some((item) => item.id === target) || !mode || !supported) {
        throw new Error("Selecciona un activo propio dentro del alcance y una especialidad disponible.");
      }
      if (!files.length || files.length > (purple ? 50 : 1) || files.some((file) => file.size < 1 || file.size > MAX_BYTES)) {
        throw new Error(purple ? "Selecciona entre 1 y 50 archivos JSON de hasta 1 MiB cada uno."
          : "Selecciona un archivo JSON de hasta 1 MiB.");
      }
      const sources: Models["Source"][] = [];
      for (const file of files) {
        const raw = await file.arrayBuffer();
        let content;
        try {
          content = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(raw));
        } catch {
          throw new Error("Cada archivo debe contener JSON válido en UTF-8.");
        }
        const validData = events ? Array.isArray(content?.events)
          : Array.isArray(content?.observations) && content.observations.length > 0;
        if (content?.target_id !== target || !validData) {
          throw new Error(events ? "El JSON debe incluir el UUID del activo seleccionado y la lista de eventos."
            : "El JSON debe incluir el UUID del activo seleccionado y sus observaciones.");
        }
        sources.push({ digest: await sha256(raw), size_bytes: file.size, target_id: target, classification,
          capability: events ? "event-review" : "scope-record-review",
          kind: events ? "event-batch-v1" : "control-observations-v1" });
      }
      if (new Set(sources.map(({ digest }) => digest)).size !== sources.length) {
        throw new Error("Selecciona archivos distintos.");
      }
      return createWithReceipt<Models["PermissionReceipt"]>(ctx, "evidence-permissions", {
        plan_id: plan.id, plan_hash: plan.hash, mode_id: mode.manifest.id, mode_version: mode.manifest.version,
        mode_digest: mode.digest, valid_from: plan.authorization.valid_from, valid_until: plan.authorization.valid_until,
        purpose: "offline-review", allow_local_inference: !events && classification === "internal" && localInference,
        sources,
      } satisfies Models["PermissionSpec"]);
    },
  });

  return <Card className="form-card plan-result">
    <h2>Solicitar permiso de evidencia</h2>
    {catalog.isError || selection.isError ? <div className="offline-actions"><p role="alert">No se pudo cargar la especialidad.</p>
      <Button onClick={() => { void selection.refetch(); void catalog.refetch(); }}>Actualizar especialidad</Button></div>
      : catalog.isPending || selection.isPending ? <p role="status">Cargando requisitos…</p>
      : !mode || !supported ? <p>Pide a un administrador que configure White Team, Blue Team o Purple Team.</p>
      : !targets.length ? <p>El plan necesita un activo propio dentro del alcance.</p>
      : <form onSubmit={(event) => {
        event.preventDefault();
        submit.mutate(undefined, { onSuccess: ({ id }) => { location.hash = plannerLink(ctx, { id: plan.id, permission: id }); } });
      }}>
        <p>{mode.manifest.label} · Versión {mode.manifest.version}</p>
        <ul>{mode.manifest.inputs.map((item) => <li key={item}>{item}</li>)}</ul>
        {blue && <p>Regla de triaje <code>{BLUE_RULE}</code> · Fallos de autenticación de <code>identity-audit</code>.</p>}
        <label className="input-field">Activo autorizado
          <select required value={target} onChange={(event) => setTarget(event.target.value)}>
            <option value="">Seleccionar</option>
            {targets.map((item) => <option key={item.id} value={item.id}>{item.canonical_address}</option>)}
          </select>
        </label>
        {target && <p>UUID del activo <code>{target}</code></p>}
        <EvidenceFile label={purple ? "Archivos JSON de eventos" : events ? "Archivo JSON de eventos" : "Archivo JSON de observaciones"}
          events={events} multiple={purple} onChange={setFiles} />
        <label className="input-field">Clasificación
          <select value={classification} onChange={(event) =>
            setClassification(event.target.value === "restricted" ? "restricted" : "internal")}>
            <option value="internal">Interna</option><option value="restricted">Restringida</option>
          </select>
        </label>
        {!events && classification === "internal" && <label className="check">
          <input type="checkbox" checked={localInference} onChange={(event) => setLocalInference(event.target.checked)} />
          Solicitar permiso de inferencia local
        </label>}
        <p>Un aprobador debe autorizar la solicitud antes de cargar el archivo.</p>
        <Button type="submit" variant="primary" disabled={submit.isPending}>{submit.isPending ? "Solicitando…" : "Solicitar permiso"}</Button>
        {submit.error && <p role="alert">{analysisFailure(submit.error)}</p>}
      </form>}
  </Card>;
}

function EvidenceFile({ label, events, multiple = false, onChange }: {
  label: string; events: boolean; multiple?: boolean; onChange: (files: File[]) => void;
}) {
  const id = useId();
  return <div className="input-field"><label htmlFor={id}>{label}</label>
    <input id={id} type="file" accept=".json,application/json" required multiple={multiple} aria-describedby={id + "-help"}
      onChange={(event) => onChange(Array.from(event.target.files ?? []))} />
    <small className="field-help" id={id + "-help"}>{events
      ? "JSON en UTF-8 con target_id, producer, window_start, window_end y events."
      : "JSON en UTF-8 con target_id y observations."} {multiple
      ? "Hasta 50 archivos de 1 MiB cada uno." : "Tamaño máximo de 1 MiB."}</small>
  </div>;
}

function UploadEvidence({ ctx, permission, source }: { ctx: ViewContext; permission: Permission; source: Source }) {
  const [file, setFile] = useState<File>();
  const upload = useMutation({
    mutationFn: async () => {
      if (!file || file.size !== source.size_bytes || file.size > MAX_BYTES ||
          await sha256(await file.arrayBuffer()) !== source.digest) {
        throw new Error("El archivo debe coincidir con el tamaño y SHA-256 del permiso.");
      }
      return api<Models["UploadReceipt"]>(analysisPath(ctx,
        `evidence-permissions/${permission.id}/revisions/${permission.revision}/sources/${source.digest}`), {
        method: "PUT", body: file,
        headers: { "Content-Type": "application/json", "X-CSRF-Token": ctx.csrf },
      });
    },
  });
  return <form onSubmit={(event) => { event.preventDefault(); upload.mutate(); }}>
    <EvidenceFile label="Cargar archivo autorizado" events={source.kind === "event-batch-v1"}
      onChange={([next]) => { upload.reset(); setFile(next); }} />
    <Button type="submit" disabled={upload.isPending}>{upload.isPending ? "Cargando…" : "Cargar evidencia"}</Button>
    {upload.isSuccess && <p role="status">Evidencia cargada.</p>}
    {upload.error && <p role="alert">{analysisFailure(upload.error)}</p>}
  </form>;
}

export function EvidencePermission({ ctx, id, planId, frozen }: {
  ctx: ViewContext; id: string; planId?: string; frozen: boolean;
}) {
  const [scenarioFile, setScenarioFile] = useState<File>();
  const path = `evidence-permissions/${id}`;
  const permission = useQuery({
    queryKey: ["project-data", ctx.user, ctx.org, ctx.project, "evidence-permission", id],
    queryFn: ({ signal }) => api<Permission>(analysisPath(ctx, path), { signal }),
    retry: false,
  });
  const selection = useQuery({
    queryKey: ["project-data", ctx.user, ctx.org, ctx.project, "team-selection"],
    queryFn: ({ signal }) => api<Models["TeamSelection"]>(analysisPath(ctx, "team-selection"), { signal }),
    enabled: !frozen && ctx.permissions.includes("evidence:request"),
  });
  const draft = useMutation({
    mutationFn: async (record: Permission) => {
      const selected = selection.data?.selection;
      if (!selected || !selection.data?.version || selected.mode_digest !== record.spec.mode_digest) {
        throw new Error("La especialidad vigente debe coincidir con la del permiso.");
      }
      let scenario: Models["CoverageScenario"] | undefined;
      if (record.spec.mode_id === "purple") {
        if (!scenarioFile || scenarioFile.size > 32 * 1024) throw new Error("Selecciona un escenario JSON de hasta 32 KiB.");
        try {
          scenario = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(await scenarioFile.arrayBuffer()));
        } catch {
          throw new Error("El escenario debe contener JSON válido en UTF-8.");
        }
        if (!scenario || !Array.isArray(scenario.checks) || !scenario.checks.length)
          throw new Error("El escenario debe incluir al menos un control.");
      }
      return createWithReceipt<Models["AnalysisCreated"]>(ctx, "analyses", {
        permission_id: record.id, permission_revision: record.revision, selection_version: selection.data.version,
        sources: record.spec.sources.map(({ digest }) => digest).sort(),
        ...(record.spec.mode_id === "blue" ? { event_rule: BLUE_RULE } : {}),
        ...(scenario ? { coverage_scenario: scenario } : {}),
      } satisfies Models["AnalysisDraft"]);
    },
  });
  const record = permission.data;
  if (permission.isError) return <Card className="form-card"><h2>Permiso de evidencia</h2>
    <p role="alert">{analysisFailure(permission.error)}</p><Button onClick={() => { void permission.refetch(); }}>Actualizar permiso</Button>
  </Card>;
  if (!record) return <p role="status">Cargando permiso de evidencia…</p>;
  if (planId && record.spec.plan_id !== planId) return <Card className="form-card">
    <p role="alert">El permiso corresponde a otro plan.</p></Card>;
  const current = !frozen && record.status === "approved" &&
    Date.parse(record.spec.valid_from) <= Date.now() && Date.now() < Date.parse(record.spec.valid_until);
  const owner = isEvidenceRequester(ctx, record);
  const canDecide = !frozen && ctx.permissions.includes("evidence:decide") &&
    record.status !== "revoked" && record.requester_id !== ctx.user;
  return <div className="section-stack">
    <Card className="form-card plan-result">
      <div className="panel-title"><h2>Permiso de evidencia</h2><Status state={record.status} /></div>
      <p>Revisión {record.revision} · <code>{record.id}</code></p>
      <p>{record.spec.allow_local_inference ? "Con permiso para inferencia local" : "Solo revisión determinista"}</p>
      <div className="offline-actions">
        <Button asChild><a href={plannerLink(ctx, { id: record.spec.plan_id })}>Consultar plan de origen</a></Button>
        <Button onClick={() => { void permission.refetch(); if (owner) void selection.refetch(); }}>Actualizar permiso</Button>
      </div>
      {record.status === "pending" && <p role="status">En espera de aprobación del permiso.</p>}
      {record.status === "approved" && !current && <p role="status">La carga y la creación requieren un proyecto activo y un permiso vigente.</p>}
      {record.spec.sources.map((source) => <details key={source.digest}>
        <summary>Fuente · {source.digest.slice(0, 12)} · {source.classification === "internal" ? "Interna" : "Restringida"}</summary>
        <p>SHA-256 <code>{source.digest}</code></p>
        <p>{source.kind === "legacy-reference-v1" ? "Referencia de importación"
          : source.kind === "event-batch-v1" ? "Archivo de eventos JSON" : "Archivo de observaciones JSON"}</p>
        {owner && current && source.kind !== "legacy-reference-v1" &&
          <UploadEvidence key={record.revision + source.digest} ctx={ctx} permission={record} source={source} />}
      </details>)}
      {owner && current && <div className="offline-actions">
        {record.spec.sources.some((source) => source.kind !== "legacy-reference-v1") &&
          <p>Carga los archivos autorizados antes de crear el análisis.</p>}
        {record.spec.mode_id === "purple" && <label className="input-field">Escenario sintético de cobertura
          <input type="file" accept=".json,application/json" onChange={(event) => setScenarioFile(event.target.files?.[0])} />
        </label>}
        <Button variant="primary" disabled={draft.isPending || selection.isPending ||
          (record.spec.mode_id === "purple" && !scenarioFile)} onClick={() => draft.mutate(record, {
          onSuccess: ({ id: analysis }) => { location.hash = plannerLink(ctx, { id: record.spec.plan_id, permission: id, analysis }); },
        })}>Crear análisis offline</Button>
        {draft.error && <p role="alert">{analysisFailure(draft.error)}</p>}
      </div>}
    </Card>
    {canDecide && <Form title="Decidir permiso de evidencia" fields={[
      { name: "decision", label: "Decisión del permiso", rule: required,
        options: [...(record.status === "pending" ? [{ value: "approve", label: "Aprobar" }] : []),
          { value: "revoke", label: "Revocar" }] },
      { name: "reason", label: "Motivo del permiso", rule: required.max(500) },
    ]} label="Registrar decisión del permiso" action={({ decision, reason }) =>
      write(ctx.csrf, analysisPath(ctx, path + "/decisions"), { revision: record.revision, decision, reason })
    } completed={() => { void permission.refetch(); }} />}
  </div>;
}

function isEvidenceRequester(ctx: ViewContext, record: Permission) {
  return ctx.permissions.includes("evidence:request") && record.requester_id === ctx.user;
}
