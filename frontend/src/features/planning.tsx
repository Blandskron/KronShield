import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { z } from "zod";
import { api, listOptions, type Models } from "../api";
import { Button, Card } from "../ui";
import { failure, Form, required, uuid } from "./forms";
import { contextPath, options, type ViewContext, write } from "./administration";

const statusText: Record<string, string> = {
  blocked: "Bloqueado", reviewed: "Revisado", allowed: "Dentro del alcance", excluded: "Excluido por regla",
  expired: "Autorización vencida", revoked: "Autorización revocada", not_approved: "Autorización pendiente de aprobación",
  not_yet_valid: "La autorización aún no entra en vigor", authorization_superseded: "La revisión fue reemplazada",
  project_archived: "Proyecto archivado", organization_kill_switch: "Organización en pausa",
  environment_mismatch: "El entorno del activo no coincide", no_allow_rule: "El activo no tiene una regla aplicable",
  unknown_attribution: "Titularidad sin verificar", third_party_not_allowed: "Tercero fuera del alcance",
};

export function AuthorizationForms({ ctx, records, complete, open }: {
  ctx: ViewContext; records: Models["Authorization"][]; complete: () => void; open: boolean;
}) {
  const [pdf, setPdf] = useState<File>();
  const base = "/projects/" + ctx.project;
  return <div className="feature-grid">
    {open && ctx.permissions.includes("authorizations:request") && <div>
      <label className="input-field evidence-input"><span>Documento PDF del mandato</span><input type="file"
        accept="application/pdf,.pdf" onChange={(event) => setPdf(event.target.files?.[0])} /></label>
      <Form title="Solicitar autorización" fields={[
        { name: "delegator_id", label: "UUID de quien delega", rule: uuid },
        { name: "valid_from", label: "Inicio de vigencia", rule: required, type: "datetime-local" },
        { name: "valid_until", label: "Fin de vigencia", rule: required, type: "datetime-local" },
        { name: "kind", label: "Tipo de alcance", rule: required, options: options(["fqdn", "subdomain", "ip", "cidr", "application"]) },
        { name: "destination", label: "Destino autorizado", rule: required },
        { name: "exclude", label: "Exclusión del mismo tipo (opcional)", rule: z.string().trim() },
      ]} label="Registrar solicitud" action={async (values) => {
        if (!pdf || pdf.size > 1024 * 1024) throw new Error("Selecciona un PDF de hasta 1 MiB.");
        const from = new Date(values.valid_from);
        const until = new Date(values.valid_until);
        if (until <= from || until.getTime() <= Date.now()) throw new Error("La vigencia debe terminar en el futuro y después del inicio.");
        const document = await write<Models["Document"]>(ctx.csrf, contextPath(base + "/authorization-documents", ctx.org), pdf);
        return write(ctx.csrf, contextPath(base + "/authorizations", ctx.org), {
          document_evidence_id: document.id, delegator_id: values.delegator_id,
          valid_from: from.toISOString(), valid_until: until.toISOString(), limits: {},
          scope_rules: [{ effect: "allow", kind: values.kind, destination: values.destination },
            ...(values.exclude ? [{ effect: "deny", kind: values.kind, destination: values.exclude }] : [])],
        });
      }} completed={complete} />
    </div>}
    {records.length > 0 && <Card className="form-card plan-result"><h2>Mandatos y alcance</h2>
      {records.map((record) => <details key={record.id}>
        <summary>{record.id.slice(0, 8)} · rev. {record.revision}</summary>
        <p>Vigencia desde {new Date(record.valid_from).toLocaleString("es")} hasta {new Date(record.valid_until).toLocaleString("es")}.</p>
        <ul>{record.scope_rules.map((rule, index) => <li key={index}>
          {rule.effect === "allow" ? "Permitir" : "Excluir"} · {rule.destination}
          {rule.path_prefix ? "/" + rule.path_prefix.join("/") : ""}
        </li>)}</ul>
        <p>SHA-256 <code>{record.document_digest}</code></p>
        {record.document_evidence_id && (ctx.permissions.includes("authorizations:decide") || record.requester_id === ctx.user) &&
          <a className="button" href={"/api/v1" + contextPath(base + "/authorization-documents/" + record.document_evidence_id, ctx.org)}>
            Descargar mandato PDF
          </a>}
      </details>)}
    </Card>}
    {ctx.permissions.includes("authorizations:decide") && (["approve", "revoke"] as const).map((decision) => {
      const eligible = records.filter((record) => record.requester_id !== ctx.user && (decision === "approve"
        ? open && record.status === "draft" && Date.parse(record.valid_until) > Date.now()
        : record.status === "approved"));
      if (!eligible.length) return null;
      return <Form key={decision} title={decision === "approve" ? "Aprobar autorización" : "Revocar autorización"} fields={[
        { name: "id", label: "Autorización", rule: uuid, options: eligible
          .map((item) => ({ value: item.id, label: item.id.slice(0, 8) + " · rev. " + item.revision })) },
        { name: "reason", label: "Motivo", rule: required.max(500) },
      ]} label="Registrar decisión" action={(values) => {
        const selected = eligible.find((item) => item.id === values.id);
        if (!selected) throw new Error("La autorización ya no está disponible.");
        return write(ctx.csrf, contextPath(base + "/authorizations/" + selected.id + "/decisions", ctx.org),
          { revision: selected.revision, decision, reason: values.reason });
      }} completed={complete} />;
    })}
  </div>;
}

export function planLocation(): { org: string; project: string; id: string } | null {
  if (!location.hash.startsWith("#plan?")) return null;
  const params = new URLSearchParams(location.hash.slice(6));
  const org = params.get("org"), project = params.get("project"), id = params.get("id");
  return org && project && id ? { org, project, id } : null;
}

export function quoteCommand(argv: string[], shell: "bash" | "powershell") {
  return (shell === "powershell" ? "& " : "") + argv.map((arg) => "'" +
    arg.replaceAll("'", shell === "powershell" ? "''" : "'\"'\"'") + "'").join(" ");
}

export function Planner({ ctx, frozen }: { ctx: ViewContext; frozen: boolean }) {
  const selection = planLocation();
  const [selected, setSelected] = useState<string[]>([]);
  const pending = useRef<{ payload: string; key: string } | null>(null);
  const [verified, setVerified] = useState("");
  const root = "/projects/" + ctx.project;
  const params = { org_id: ctx.org };
  const canCreate = !frozen && ctx.permissions.includes("assessments:manage");
  const list = <T,>(segment: string) => ({ queryKey: ["planner", ctx.user, ctx.org, ctx.project, segment], enabled: canCreate,
    queryFn: ({ signal }: { signal: AbortSignal }) => listOptions<T>(root + "/" + segment, params, signal) });
  const assessments = useQuery(list<Models["Assessment"]>("assessments"));
  const authorizations = useQuery(list<Models["Authorization"]>("authorizations"));
  const targets = useQuery(list<Models["Target"]>("targets"));
  const matching = selection?.org === ctx.org && selection.project === ctx.project;
  const plan = useQuery({ queryKey: ["plan", ctx.user, ctx.org, ctx.project, selection?.id], enabled: Boolean(matching),
    queryFn: ({ signal }) => api<Models["Plan"]>(contextPath(root + "/plans/" + selection?.id, ctx.org), { signal }) });

  const detail = plan.data;
  const args = detail ? [
    "pentest-agent", "plan", "show", "--org-id", ctx.org, "--project-id", ctx.project, "--plan-id", detail.id,
  ] : [];
  const verify = async () => {
    try {
      await write(ctx.csrf, contextPath(root + "/plans/" + detail?.id + "/verify", ctx.org), { hash: detail?.hash });
      setVerified("La revisión sigue vigente.");
    } catch (error) {
      setVerified(failure(error as Error));
    }
  };

  return <div className="feature-grid">
    {selection && !matching && <Card className="form-card"><p role="alert">El plan pertenece a un proyecto que no está seleccionado o no está disponible.</p></Card>}
    {matching && plan.isPending && <p role="status">Cargando el plan…</p>}
    {plan.error && <Card className="form-card"><p role="alert">{failure(plan.error)}</p></Card>}
    {detail && <Card className="form-card plan-result"><h2>Plan {detail.id}</h2>
      <p role="status">{statusText[detail.status]}</p>
      <p>Revisión de autorización: {detail.authorization.revision}. Ejecución deshabilitada.</p>
      <p>SHA-256 del plan <code>{detail.hash}</code></p>
      {detail.denials.length > 0 && <ul>{detail.denials.map((denial) => <li key={denial}>{statusText[denial] ?? denial}</li>)}</ul>}
      <ul>{detail.targets.map((target) => <li key={target.id}>{target.canonical_address} · {statusText[target.reason] ?? target.reason}</li>)}</ul>
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => { void verify(); }}>Verificar vigencia</Button>
        <Button asChild><a href={"/api/v1" + contextPath(root + "/plans/" + detail.id + "/report", ctx.org)}>
          Descargar informe HTML
        </a></Button>
      </div>
      {verified && <p role="status">{verified}</p>}
      <details><summary>Comandos de consulta</summary>
        {(["bash", "powershell"] as const).map((shell) => <div key={shell}><strong>{shell}</strong>
          <pre>{quoteCommand(args, shell)}</pre>
          <Button onClick={() => { void navigator.clipboard.writeText(quoteCommand(args, shell)); }}>Copiar {shell}</Button>
        </div>)}</details>
    </Card>}
    {canCreate && <div>
      <Card className="form-card"><fieldset><legend>Activos del plan</legend>
        {targets.data?.map((item) => <label key={item.id} className="check">
          <input type="checkbox" checked={selected.includes(item.id)}
            onChange={(event) => {
              setSelected((previous) => event.target.checked ? [...previous, item.id] : previous.filter((id) => id !== item.id));
            }} />{item.slug}
        </label>)}
        {!targets.data?.length && <p>Registra al menos un activo en el proyecto.</p>}
      </fieldset></Card>
      {assessments.data?.length && authorizations.data?.length ? <Form title="Nueva revisión de alcance" fields={[
        { name: "assessment_id", label: "Evaluación", rule: uuid, options: assessments.data.map((item) => ({ value: item.id, label: item.label })) },
        { name: "authorization_id", label: "Revisión de autorización", rule: uuid,
          options: authorizations.data.map((item) => ({ value: item.id, label: item.id.slice(0, 8) + " · rev. " + item.revision })) },
      ]} label="Simular plan" action={async (values) => {
        if (!selected.length || selected.length > 50) throw new Error("Selecciona entre 1 y 50 activos.");
        const auth = authorizations.data!.find((item) => item.id === values.authorization_id)!;
        const payload = JSON.stringify({ ...values, authorization_revision: auth.revision, target_ids: [...selected].sort() });
        if (pending.current?.payload !== payload) pending.current = { payload, key: crypto.randomUUID() };
        return api<Models["Plan"]>(contextPath(root + "/plans", ctx.org), {
          method: "POST", headers: { "X-CSRF-Token": ctx.csrf, "Content-Type": "application/json", "Idempotency-Key": pending.current.key },
          body: payload,
        });
      }} completed={(result) => {
        const id = (result as Models["Plan"]).id;
        location.hash = "plan?" + new URLSearchParams({ org: ctx.org, project: ctx.project, id });
        pending.current = null;
      }} /> : <Card className="form-card"><p>Registra una evaluación y una autorización para preparar el plan.</p></Card>}
      {[targets.error, assessments.error, authorizations.error].some(Boolean) && <p role="alert">No se pudo cargar el inventario del plan.</p>}
    </div>}
    {!selection && !canCreate && <Card className="form-card"><p>Abre un enlace de plan de tu proyecto para consultarlo.</p></Card>}
  </div>;
}
