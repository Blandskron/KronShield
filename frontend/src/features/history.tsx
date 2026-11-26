import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Download, FileClock, Search } from "lucide-react";
import { api, ApiError, type Models } from "../api";
import { Empty, Records, Status } from "../records";
import { Button, Card } from "../ui";
import { contextPath, type ViewContext } from "./administration";
import { uuid } from "./forms";

type Kind = "plan" | "legacy";

export function History({ ctx }: { ctx: ViewContext }) {
  const [kind, setKind] = useState<Kind>("plan");
  const [reference, setReference] = useState("");
  const [lookup, setLookup] = useState<{ kind: Kind; id: string }>();
  const [invalid, setInvalid] = useState(false);
  const root = "/projects/" + ctx.project;
  const result = useQuery({
    enabled: Boolean(lookup),
    queryKey: ["project-data", ctx.user, ctx.org, ctx.project, "history", lookup],
    queryFn: async ({ signal }) => {
      if (!lookup) throw new Error("Missing history reference");
      if (lookup.kind === "legacy") {
        const batch = await api<Models["ImportDetail"]>(contextPath(root + "/legacy-imports/" + lookup.id, ctx.org), { signal });
        return { kind: lookup.kind, batch };
      }
      const path = root + "/plans/" + lookup.id;
      const [plan, events] = await Promise.all([
        api<Models["Plan"]>(contextPath(path, ctx.org), { signal }),
        api<Models["PlanEvents"]>(contextPath(path + "/events", ctx.org), { signal }),
      ]);
      return { kind: lookup.kind, plan, events: events.items, report: "/api/v1" + contextPath(path + "/report", ctx.org) };
    },
  });
  return <div className="section-stack">
    <Card className="form-card">
      <h2>Consultar un registro</h2>
      <form onSubmit={(event) => {
        event.preventDefault();
        const parsed = uuid.safeParse(reference.trim());
        if (!parsed.success) {
          setInvalid(true);
          setLookup(undefined);
          return;
        }
        setInvalid(false);
        if (lookup?.kind === kind && lookup.id === parsed.data) void result.refetch();
        else setLookup({ kind, id: parsed.data });
      }}>
        <div className="form-fields history-fields">
          <label className="input-field">Tipo de registro
            <select value={kind} onChange={(event) => {
              setKind(event.target.value === "legacy" ? "legacy" : "plan");
              setReference(""); setLookup(undefined); setInvalid(false);
            }}>
              <option value="plan">Plan e informe</option>
              <option value="legacy">Hallazgos importados</option>
            </select>
          </label>
          <label className="input-field">UUID del registro
            <input value={reference} onChange={(event) => { setReference(event.target.value); setInvalid(false); }}
              aria-invalid={invalid} aria-describedby={invalid ? "reference-error" : undefined}
              autoComplete="off" spellCheck={false} required />
          </label>
        </div>
        {invalid && <p id="reference-error" role="alert">Introduce un UUID válido.</p>}
        <Button type="submit" variant="primary"><Search size={16} aria-hidden /> Consultar</Button>
      </form>
    </Card>
    {!lookup && <Card><Empty>Usa el UUID de un plan guardado o el recibo de una importación del proyecto.</Empty></Card>}
    {lookup && result.isPending && <p role="status">Cargando registro…</p>}
    {result.isError && <p role="alert">{result.error instanceof ApiError && result.error.status === 404
      ? "El registro no está disponible en este proyecto." : "No se pudo cargar el registro. Intenta consultarlo otra vez."}</p>}
    {result.data?.kind === "plan" && <div className="section-stack">
      <Card className="form-card">
        <div className="panel-title"><h2>Informe de revisión</h2><Status state={result.data.plan.status} /></div>
        <p className="result-line"><code>{result.data.plan.hash}</code></p>
        <div className="flex flex-wrap gap-2">
          <Button asChild><a href={result.data.report}><Download size={16} aria-hidden /> Descargar informe HTML</a></Button>
          <Button asChild><a href={"#plan?" + new URLSearchParams({
            org: ctx.org, project: ctx.project, id: result.data.plan.id,
          })}>Abrir revisión original</a></Button>
        </div>
      </Card>
      <Records title="Registro de auditoría" items={result.data.events} columns={["Evento", "Fecha (UTC)"]}
        cells={(item) => ({ key: item.id, values: ["Revisión de alcance registrada",
          new Intl.DateTimeFormat("es", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(new Date(item.created_at))] })}
        empty="Este plan todavía no tiene eventos registrados." />
    </div>}
    {result.data?.kind === "legacy" && <>
      <p className="inline-state"><FileClock size={18} aria-hidden /> Históricos importados · confianza sin verificar</p>
      <Records title="Hallazgos importados" items={result.data.batch.findings} columns={["Tipo", "Detalle"]}
        search={(item) => item.type + " " + item.detail}
        cells={(item) => ({ key: item.record_key, values: [item.type, item.detail] })}
        empty="La importación no contiene hallazgos." />
    </>}
  </div>;
}
