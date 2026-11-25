import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, type Models } from "../api";
import { Button, Card } from "../ui";
import type { ViewContext } from "./administration";
import { failure } from "./forms";

type Selection = Models["TeamSelection"];
type ModeId = Models["TeamId"];

export function TeamSelection({ ctx, frozen }: { ctx: ViewContext; frozen: boolean }) {
  const id = useId();
  const cache = useQueryClient();
  const [draft, setDraft] = useState<{ mode: ModeId; version: number } | null>(null);
  const prefix = "/projects/" + ctx.project;
  const suffix = "?" + new URLSearchParams({ org_id: ctx.org });
  const key = ["project-data", ctx.user, ctx.org, ctx.project, "team-selection"];
  const catalog = useQuery({
    queryKey: ["project-data", ctx.user, ctx.org, ctx.project, "team-modes"],
    queryFn: ({ signal }) => api<Models["TeamModes"]>(prefix + "/team-modes" + suffix, { signal }),
  });
  const selection = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => api<Selection>(prefix + "/team-selection" + suffix, { signal }),
  });
  const save = useMutation({
    mutationFn: ({ mode, version }: { mode: ModeId; version: number }) =>
      api<Selection>(prefix + "/team-selection" + suffix, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "If-Match": '"' + version + '"', "X-CSRF-Token": ctx.csrf },
        body: JSON.stringify({ mode_id: mode } satisfies Models["SelectionInput"]),
      }),
    onSuccess: async (value) => {
      await cache.cancelQueries({ queryKey: key, exact: true });
      cache.setQueryData(key, value);
      setDraft(null);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 412) {
        setDraft(null);
        return cache.invalidateQueries({ queryKey: key, exact: true });
      }
    },
  });
  const canEdit = !frozen && ctx.permissions.includes("project:manage");
  const items = catalog.data?.items ?? [];
  const selected = selection.data?.selection;
  const current = items.find(({ manifest, digest }) => selected && manifest.id === selected.mode_id &&
    manifest.version === selected.mode_version && digest === selected.mode_digest);
  const preview = draft ? items.find(({ manifest }) => manifest.id === draft.mode) : current;
  const canSave = canEdit && draft && preview && preview.digest !== selected?.mode_digest && !save.isPending;

  return <Card className="form-card" aria-labelledby={id + "-heading"}>
    <h2 id={id + "-heading"}>Especialidad del proyecto</h2>
    {catalog.isError || selection.isError ? <div role="alert">
      <p>No se pudo cargar la especialidad del proyecto.</p>
      <Button onClick={() => { void catalog.refetch(); void selection.refetch(); }}>Reintentar</Button>
    </div> : !catalog.data || !selection.data ? <p role="status">Cargando especialidades…</p>
      : <>
          <p>{current ? "Selección guardada · " + current.manifest.label : selected
            ? "Selección guardada · " + selected.mode_id + " (versión histórica)"
            : "Todavía no hay una especialidad configurada."}</p>
          <form onSubmit={(event) => {
            event.preventDefault();
            if (canSave) save.mutate(draft);
          }}>
            <div className="input-field">
              <label htmlFor={id + "-mode"}>{canEdit ? "Elegir especialidad" : "Consultar especialidad"}</label>
              <select id={id + "-mode"} value={draft?.mode ?? current?.manifest.id ?? ""}
                disabled={save.isPending} onChange={(event) => {
                  save.reset();
                  const mode = items.find(({ manifest }) => manifest.id === event.target.value)?.manifest.id;
                  if (mode && selection.data) setDraft({ mode, version: selection.data.version });
                }}>
                <option value="" disabled>Seleccionar</option>
                {items.map(({ manifest }) => <option key={manifest.id} value={manifest.id}>{manifest.label}</option>)}
              </select>
            </div>
            {canEdit && <>
              <p>La selección se comparte con el proyecto y se aplicará a los análisis futuros cuando el modo esté disponible.</p>
              <Button variant="primary" type="submit" aria-disabled={!canSave}>
                {save.isPending ? "Guardando…" : "Guardar especialidad"}
              </Button>
            </>}
          </form>
          {save.isSuccess && <p role="status">Especialidad guardada.</p>}
          {save.error && <p role="alert">{save.error instanceof ApiError && save.error.status === 412
            ? "Otra persona cambió la selección. Elige la especialidad de nuevo." : failure(save.error)}</p>}
          {preview && <details>
            <summary>Ver capacidades de {preview.manifest.label}</summary>
            <p>{preview.manifest.purpose} · Versión {preview.manifest.version}</p>
            <p>{preview.eligible_for_analysis ? "Disponible para análisis" : "Análisis pendiente de habilitación"}</p>
            <h3>Entradas requeridas</h3>
            <ul>{preview.manifest.inputs.map((requirement) => <li key={requirement}>{requirement}</li>)}</ul>
            <h3>Flujo previsto</h3>
            <ul>{preview.manifest.workflow.map((step) => <li key={step.id}>{step.kind === "team"
              ? items.find(({ manifest }) => manifest.id === step.team)?.manifest.label ?? step.team
              : step.tool}{step.after?.length ? " · depende de " + step.after.join(", ") : ""}</li>)}</ul>
            {preview.manifest.resources?.length ? <p>Referencias · {preview.manifest.resources.join(", ")}</p> : null}
            <p>Resultado esperado · {preview.manifest.output}</p>
          </details>}
        </>}
  </Card>;
}
