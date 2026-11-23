import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { z } from "zod";
import { api, listOptions, type Models, type Page } from "../api";
import { Button, Card } from "../ui";
import { failure, Form, required, slug, uuid, type Field } from "./forms";

export type ViewContext = {
  user: string; csrf: string; org: string; project: string;
  permissions: string[]; orgAdmin: boolean; platformAdmin: boolean; pilot: boolean;
};

export const options = (names: string[]) => names.map((value) => ({ value, label: value }));
const text = (name: string, label: string, rule = required): Field => ({ name, label, rule });

export async function write<T>(csrf: string, path: string, body?: unknown, method = "POST"): Promise<T> {
  const json = body !== undefined && !(body instanceof File);
  return api<T>(path, {
    method,
    headers: {
      "X-CSRF-Token": csrf,
      ...(json ? { "Content-Type": "application/json" } : body instanceof File ? { "Content-Type": "application/pdf" } : {}),
    },
    body: json ? JSON.stringify(body) : body instanceof File ? body : undefined,
  });
}

export function contextPath(path: string, org: string): string {
  return path + "?" + new URLSearchParams({ org_id: org });
}

export function Administration({ ctx }: { ctx: ViewContext }) {
  const cache = useQueryClient();
  const [createdAccount, setCreatedAccount] = useState("");
  const customers = useQuery({
    queryKey: ["customers", ctx.user, ctx.org], enabled: ctx.orgAdmin && Boolean(ctx.org),
    queryFn: ({ signal }) => listOptions<Models["Customer"]>("/customers", { org_id: ctx.org }, signal),
  });
  const update = () => { void cache.invalidateQueries(); };
  return <div className="feature-grid">
    {ctx.platformAdmin && <Form title="Nueva organización" fields={[
      text("slug", "Identificador de organización", slug), text("admin_id", "UUID del administrador inicial", uuid),
    ]} label="Crear organización" action={(body) => write(ctx.csrf, "/organizations", body)} completed={update} />}
    {ctx.platformAdmin && ctx.pilot && <div><Form title="Cuenta local del piloto" fields={[
      text("username", "Nombre de usuario", z.string().regex(/^[a-z][a-z0-9_-]{2,31}$/, "Usa de 3 a 32 caracteres válidos.")),
      { name: "password", label: "Contraseña de la cuenta", rule: z.string().min(12).max(128), type: "password" },
    ]} label="Crear cuenta local" action={(body) => write<Models["Account"]>(ctx.csrf, "/auth/local/accounts", body)}
      completed={(data) => setCreatedAccount((data as Models["Account"]).user_id)} />
      {createdAccount && <p role="status" className="result-line">UUID de la cuenta: <code>{createdAccount}</code></p>}</div>}
    {ctx.orgAdmin && <>
      <Form title="Nuevo cliente" fields={[text("slug", "Identificador del cliente", slug), text("name", "Nombre del cliente")]}
        label="Crear cliente" action={(body) => write(ctx.csrf, contextPath("/customers", ctx.org), body)} completed={update} />
      {customers.data?.length ? <Form title="Nuevo proyecto" fields={[
        text("slug", "Identificador del proyecto", slug),
        { name: "customer_id", label: "Cliente", rule: uuid, options: customers.data.map((item) => ({ value: item.id, label: item.name })) },
        text("environment", "Entorno", z.string().regex(/^[a-z][a-z0-9_-]{0,63}$/, "Introduce un entorno válido.")),
      ]} label="Crear proyecto" action={(body) => write(ctx.csrf, contextPath("/projects", ctx.org), body)} completed={update} />
      : <Card className="form-card"><h2>Proyectos</h2><p>Crea un cliente antes de registrar un proyecto.</p></Card>}
      <MembershipForm ctx={ctx} />
      {ctx.project && <MembershipForm key={ctx.project} ctx={ctx} project />}
    </>}
    {!ctx.platformAdmin && !ctx.orgAdmin && <Card className="form-card"><p>Tu rol permite consultar los proyectos asignados.</p></Card>}
  </div>;
}

function MembershipForm({ ctx, project }: { ctx: ViewContext; project?: boolean }) {
  const params = new URLSearchParams({ org_id: ctx.org });
  if (project) params.set("project_id", ctx.project);
  const path = "/memberships?" + params;
  const [problem, setProblem] = useState("");
  const query = useQuery({
    queryKey: ["members", ctx.user, ctx.org, project ? ctx.project : ""],
    queryFn: ({ signal }) => api<Page<Models["Membership"]>>(path, { signal }),
  });
  const remove = async (id: string) => {
    try {
      await write(ctx.csrf, "/memberships/" + id + "?" + params, undefined, "DELETE");
      setProblem("");
      await query.refetch();
    } catch (error) {
      setProblem(failure(error as Error));
    }
  };
  return <div><Form title={project ? "Membresía de proyecto" : "Membresía de organización"} fields={[
    text("user_id", "UUID del usuario", uuid),
    { name: "role_id", label: "Rol", rule: required,
      options: options(project ? ["viewer", "operator", "approver", "project_admin"] : ["member", "org_admin"]) },
  ]} label="Guardar membresía" action={(body) => write(ctx.csrf, path, body, "PUT")}
    completed={() => { void query.refetch(); }} />
    {problem && <p role="alert">{problem}</p>}
    {query.data?.items.length ? <ul className="membership-list">{query.data.items.map((item) => <li key={item.user_id}>
      <span><code>{item.user_id}</code><small>{item.role_id}</small></span>
      {item.user_id !== ctx.user && <Button onClick={() => { void remove(item.user_id); }}>Quitar</Button>}
    </li>)}</ul> : null}</div>;
}

export function NewTarget({ ctx, complete }: { ctx: ViewContext; complete: () => void }) {
  return <Form title="Nuevo activo" fields={[
    text("slug", "Identificador del activo", slug), text("address", "Host, IP o URL"), text("environment", "Entorno"),
    { name: "attribution", label: "Titularidad", rule: required, options: options(["first_party", "third_party", "shared", "unknown"]) },
    text("third_party_id", "Identificador del tercero (opcional)", z.string().max(160)),
  ]} label="Registrar activo" action={(values) => write(ctx.csrf, contextPath("/projects/" + ctx.project + "/targets", ctx.org),
      { ...values, third_party_id: values.third_party_id || null })} completed={complete} />;
}

export function NewAssessment({ ctx, complete }: { ctx: ViewContext; complete: () => void }) {
  return <Form title="Nueva evaluación" fields={[text("label", "Nombre de la evaluación")]}
    label="Registrar evaluación" action={(values) => write(ctx.csrf, contextPath("/projects/" + ctx.project + "/assessments", ctx.org), values)}
    completed={complete} />;
}
