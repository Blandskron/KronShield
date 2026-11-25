import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Box, ChevronDown, ChevronRight, ClipboardList, LayoutDashboard, LogOut, Settings, ShieldCheck } from "lucide-react";
import { StrictMode, useEffect, useId, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { api, ApiError, listOptions, type Models, usePages } from "./api";
import { Button, Card } from "./ui";
import { Administration, NewAssessment, NewTarget, type ViewContext } from "./features/administration";
import { AuthorizationForms, planLocation, Planner } from "./features/planning";
import { SignIn } from "./features/signin";
import { TeamSelection } from "./features/team-selection";
import blandskronLogo from "./assets/blandskron-horizontal.png";
import "./styles.css";

const sections = {
  resumen: { name: "Resumen", icon: LayoutDashboard },
  activos: { name: "Activos", icon: Box },
  evaluaciones: { name: "Evaluaciones", icon: ClipboardList },
  autorizaciones: { name: "Autorizaciones", icon: ShieldCheck },
  planificador: { name: "Planificador", icon: ClipboardList },
  gestion: { name: "Gestión", icon: Settings },
};
type Section = keyof typeof sections;
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });

function currentSection(hash: string): Section {
  const name = hash.slice(1);
  if (name.startsWith("plan?")) return "planificador";
  return Object.hasOwn(sections, name) ? name as Section : "resumen";
}

function Brand() {
  return <div className="brand">
    <img src={blandskronLogo} alt="Blandskron" width={640} height={132} />
    <span>Gestión de auditorías</span>
  </div>;
}

function Select({ label, value, options, change }: {
  label: string; value: string; options: { id: string; slug: string }[]; change: (v: string) => void;
}) {
  const id = useId();
  return <div className="select-field"><label htmlFor={id}>{label}</label><span className="select-control">
    <select id={id} value={value} onChange={(event) => change(event.target.value)}>
      {options.length === 0 && <option value="">Sin opciones</option>}
      {options.map((option) => <option key={option.id} value={option.id}>{option.slug}</option>)}
    </select><ChevronDown size={15} aria-hidden />
  </span></div>;
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="empty"><ClipboardList size={25} aria-hidden /><p>{children}</p></div>;
}

function Status({ state }: { state: string }) {
  const labels: Record<string, string> = {
    active: "Activo", archived: "Archivado", draft: "Borrador", scheduled: "Programada",
    expired: "Vencida", revoked: "Revocada",
  };
  return <span className={"status-pill " + (state === "active" ? "active" : "")}>{labels[state] ?? state}</span>;
}

function Records<T>({ title, items, columns, cells, more, empty }: {
  title: string; items: T[]; columns: string[]; cells: (row: T) => { key: string; values: ReactNode[] };
  more?: () => void; empty: string;
}) {
  return <Card><div className="card-head"><h2>{title}</h2></div>
    {items.length ? <div className="table-wrap"><table aria-label={title}>
      <thead><tr>{columns.map((column) => <th key={column} scope="col">{column}</th>)}</tr></thead>
      <tbody>{items.map((row) => { const item = cells(row); return <tr key={item.key}>
        {item.values.map((field, index) => <td key={columns[index]}>{field}</td>)}
      </tr>; })}</tbody>
    </table></div> : <Empty>{empty}</Empty>}
    {more && <div className="card-footer"><Button onClick={more}>Cargar más</Button></div>}
  </Card>;
}

function ProjectContent({ user, org, project, section, ctx }: {
  user: string; org: string; project: Models["Project"]; section: Section; ctx: ViewContext;
}) {
  const targetQuery = usePages<Models["Target"]>(user, org, project.id, "targets");
  const assessmentQuery = usePages<Models["Assessment"]>(user, org, project.id, "assessments");
  const authorizationQuery = usePages<Models["Authorization"]>(user, org, project.id, "authorizations");
  const queries = [targetQuery, assessmentQuery, authorizationQuery];
  const targets = targetQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const assessments = assessmentQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const authorizations = authorizationQuery.data?.pages.flatMap((page) => page.items) ?? [];
  const date = (value: string) => new Intl.DateTimeFormat("es", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(value));
  if (queries.some((query) => query.isError)) return <Card><div className="notice" role="alert">
    <p>No se pudieron cargar los datos de este proyecto.</p>
    <Button onClick={() => { for (const query of queries) void query.refetch(); }}>Reintentar</Button>
  </div></Card>;
  if (queries.some((query) => query.isPending)) return <p role="status">Cargando el proyecto…</p>;

  const assessmentTable = (overview: boolean) => <Records title="Evaluaciones registradas"
    items={overview ? assessments.slice(0, 5) : assessments} columns={["Evaluación", "Fecha (UTC)"]}
    cells={(item) => ({ key: item.id, values: [item.label, date(item.created_at)] })}
    empty="Todavía no hay evaluaciones en este proyecto."
    more={!overview && assessmentQuery.hasNextPage && !assessmentQuery.isFetchingNextPage
      ? () => { void assessmentQuery.fetchNextPage(); } : undefined} />;

  const open = project.state === "active";
  if (section === "activos") return <div className="section-stack">
  {open && ctx.permissions.includes("targets:manage") && <NewTarget ctx={ctx} complete={() => { void targetQuery.refetch(); }} />}
  <Records title="Inventario de activos" items={targets}
    columns={["Activo", "Dirección", "Entorno"]}
    cells={(item) => ({ key: item.id, values: [item.slug, item.canonical_address, item.environment] })}
    empty="Todavía no hay activos en este proyecto."
    more={targetQuery.hasNextPage && !targetQuery.isFetchingNextPage ? () => { void targetQuery.fetchNextPage(); } : undefined} /></div>;
  if (section === "evaluaciones") return <div className="section-stack">
    {open && ctx.permissions.includes("assessments:manage") && <NewAssessment ctx={ctx} complete={() => { void assessmentQuery.refetch(); }} />}
    {assessmentTable(false)}</div>;
  if (section === "autorizaciones") return <div className="section-stack">
    {(open || ctx.permissions.includes("authorizations:decide")) &&
      <AuthorizationForms ctx={ctx} open={open} records={authorizations} complete={() => { void authorizationQuery.refetch(); }} />}
  <Records title="Registro de autorizaciones" items={authorizations}
    columns={["Revisión", "Estado", "Vigencia hasta (UTC)"]}
    cells={(item) => ({ key: item.id, values: [item.revision, <Status state={item.effective_status} />, date(item.valid_until)] })}
    empty="Todavía no hay autorizaciones en este proyecto."
    more={authorizationQuery.hasNextPage && !authorizationQuery.isFetchingNextPage
      ? () => { void authorizationQuery.fetchNextPage(); } : undefined} /></div>;

  const metrics = [
    { key: "activos", count: targets.length, more: targetQuery.hasNextPage, detail: "En el inventario" },
    { key: "evaluaciones", count: assessments.length, more: assessmentQuery.hasNextPage, detail: "Registradas" },
    { key: "autorizaciones", count: authorizations.length, more: authorizationQuery.hasNextPage, detail: "Revisiones actuales" },
  ] as const;
  return <><div className="metrics">{metrics.map(({ key, count, more, detail }) => {
    const { icon: Icon, name } = sections[key];
    return <a className="card metric" key={key} href={"#" + key}>
      <div className="metric-head"><span><Icon size={19} aria-hidden /></span><ChevronRight size={18} aria-hidden /></div>
      <h2>{name}</h2><strong className="metric-number">{count}{more ? "+" : ""}</strong><p>{detail}</p>
    </a>;
  })}</div><div className="section-stack">
    <TeamSelection ctx={ctx} frozen={!open} />
    {assessmentTable(true)}
  </div></>;
}

function Workspace({ session }: { session: Models["SessionInfo"] }) {
  const cache = useQueryClient();
  const [hash, setHash] = useState(() => location.hash);
  const section = currentSection(hash);
  const [orgChoice, setOrg] = useState(() => planLocation()?.org ?? "");
  const [projectChoice, setProject] = useState(() => planLocation()?.project ?? "");
  useEffect(() => {
    const update = () => {
      setHash(location.hash);
      const linked = planLocation();
      if (linked) {
        setOrg(linked.org);
        setProject(linked.project);
      }
    };
    addEventListener("hashchange", update);
    return () => removeEventListener("hashchange", update);
  }, []);
  const organizations = useQuery({
    queryKey: ["orgs", session.user_id],
    queryFn: ({ signal }) => listOptions<Models["Organization"]>("/organizations", {}, signal),
  });
  const orgs = organizations.data?.filter((item) => item.state === "active") ?? [];
  const org = orgs.find((item) => item.id === orgChoice) ?? orgs[0];
  const projects = useQuery({
    queryKey: ["projects", session.user_id, org?.id], enabled: Boolean(org),
    queryFn: ({ signal }) => listOptions<Models["Project"]>("/projects", { org_id: org?.id ?? "" }, signal),
  });
  const projectList = projects.data ?? [];
  const project = projectList.find((item) => item.id === projectChoice) ?? projectList[0];
  const mode = useQuery({ queryKey: ["auth-mode"], queryFn: ({ signal }) => api<Models["AuthMode"]>("/auth/mode", { signal }) });
  const organizationAccess = useQuery({
    queryKey: ["org-access", session.user_id, org?.id], enabled: Boolean(org),
    queryFn: ({ signal }) => api<Models["SessionInfo"]>("/me?" + new URLSearchParams({ org_id: org?.id ?? "" }), { signal }),
  });
  const projectAccess = useQuery({
    queryKey: ["project-access", session.user_id, org?.id, project?.id], enabled: Boolean(org && project),
    queryFn: ({ signal }) => api<Models["SessionInfo"]>("/me?" + new URLSearchParams({
      org_id: org?.id ?? "", project_id: project?.id ?? "",
    }), { signal }),
  });
  const ctx: ViewContext = {
    user: session.user_id, csrf: session.csrf_token ?? "", org: org?.id ?? "", project: project?.id ?? "",
    permissions: projectAccess.data?.permissions ?? [],
    platformAdmin: session.platform_admin, orgAdmin: organizationAccess.data?.organization_role === "org_admin",
    pilot: mode.data?.mode === "pilot",
  };
  const logout = useMutation({
    mutationFn: () => api<void>("/auth/logout", { method: "POST", headers: { "X-CSRF-Token": session.csrf_token ?? "" } }),
    onSuccess: () => { cache.clear(); location.assign("/"); },
  });

  return <div className="shell">
    <a className="skip" href="#main">Saltar al contenido</a>
    <aside className="sidebar"><Brand /><nav aria-label="Navegación principal">
      {Object.entries(sections).map(([key, { name, icon: Icon }]) => <a key={key} href={"#" + key}
        aria-current={section === key ? "page" : undefined}><Icon size={19} aria-hidden />{name}</a>)}
    </nav><div className="sidebar-footer"><Activity size={17} aria-hidden />Sesión activa</div></aside>
    <div className="area"><header className="topbar"><div className="selectors">
      <Select label="Organización" options={orgs} value={org?.id ?? ""} change={(next) => {
        cache.removeQueries({ queryKey: ["project-data"] });
        if (planLocation()) location.hash = "planificador";
        setOrg(next); setProject("");
      }} />
      <Select label="Proyecto" options={projectList} value={project?.id ?? ""} change={(next) => {
        cache.removeQueries({ queryKey: ["project-data"] });
        if (planLocation()) location.hash = "planificador";
        setProject(next);
      }} />
    </div><Button aria-label="Cerrar sesión" disabled={logout.isPending} onClick={() => logout.mutate()}>
      <LogOut size={17} aria-hidden /><span>Cerrar sesión</span>
    </Button></header>
    <main id="main" tabIndex={-1}>
      <div className="page-head"><div><h1>{sections[section].name}</h1>{project && <p>{project.slug} <span>·</span> {project.environment}</p>}</div>
        {project && <Status state={project.state} />}
      </div>
      {logout.isError && <p role="alert">La sesión no se pudo cerrar. Vuelve a intentarlo.</p>}
      {organizations.isError || projects.isError
        ? <Card><div className="notice" role="alert"><p>No se pudieron cargar las organizaciones o proyectos.</p>
            <Button onClick={() => { void organizations.refetch(); if (org) void projects.refetch(); }}>Reintentar</Button>
          </div></Card>
        : organizations.isPending || (org && projects.isPending) ? <p role="status">Cargando el espacio…</p>
        : section === "gestion" ? <Administration key={ctx.org} ctx={ctx} />
        : project && org && section === "planificador" ? <Planner key={ctx.org + ctx.project} ctx={ctx} frozen={project.state !== "active"} />
        : project && org ? <ProjectContent key={ctx.org + ctx.project} user={session.user_id} org={org.id} project={project} section={section} ctx={ctx} />
        : <Card><Empty>{org ? "Todavía no tienes acceso a un proyecto en esta organización."
            : "Tu cuenta todavía no tiene una organización activa."}</Empty></Card>}
    </main></div>
  </div>;
}

function App() {
  const session = useQuery({ queryKey: ["session"], queryFn: ({ signal }) => api<Models["SessionInfo"]>("/me", { signal }) });
  if (session.isPending) return <main className="entry" role="status">Comprobando la sesión…</main>;
  if (session.error instanceof ApiError && session.error.status === 401) return <SignIn brand={<Brand />} />;
  if (!session.data) return <main className="entry"><p role="alert">No se pudo conectar con la API.</p>
    <Button onClick={() => { void session.refetch(); }}>Reintentar</Button></main>;
  return <Workspace key={session.data.user_id} session={session.data} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode><QueryClientProvider client={queryClient}><App /></QueryClientProvider></StrictMode>,
);
