import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowDownToLine, ArrowRight, Box, ChevronDown, ClipboardList, FileClock, FolderKanban, LayoutDashboard, LogOut, Settings2, ShieldCheck } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { api, ApiError, listOptions, type Models, usePages } from "./api";
import { Button, Card } from "./ui";
import { Brand, ThemeControl } from "./brand";
import { Empty, Records, Status, statusLabel } from "./records";
import { Administration, NewAssessment, NewTarget, type ViewContext } from "./features/administration";
import { AuthorizationForms, Planner } from "./features/planning";
import { planLocation } from "./features/analysis-links";
import { TeamSelection } from "./features/team-selection";
import { History } from "./features/history";
import shieldField from "./assets/kronshield-field.svg";

const sections = {
  resumen: { name: "Resumen", icon: LayoutDashboard },
  proyectos: { name: "Proyectos", icon: FolderKanban },
  activos: { name: "Activos", icon: Box },
  evaluaciones: { name: "Evaluaciones", icon: ClipboardList },
  autorizaciones: { name: "Autorizaciones", icon: ShieldCheck },
  planificador: { name: "Planificador", icon: Activity },
  historial: { name: "Historial", icon: FileClock },
  gestion: { name: "Gestión", icon: Settings2 },
};
type Section = keyof typeof sections;

function currentSection(hash: string): Section {
  const name = hash.slice(1);
  if (name.startsWith("plan?")) return "planificador";
  return Object.hasOwn(sections, name) ? name as Section : "resumen";
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

function ProjectContent({ user, org, project, section, ctx }: {
  user: string; org: string; project: Models["Project"]; section: Section; ctx: ViewContext;
}) {
  const targetQuery = usePages<Models["Target"]>(user, org, project.id, "targets");
  const assessmentQuery = usePages<Models["Assessment"]>(user, org, project.id, "assessments");
  const authorizationQuery = usePages<Models["Authorization"]>(user, org, project.id, "authorizations");
  const queries = section === "activos" ? [targetQuery] : section === "evaluaciones" ? [assessmentQuery]
    : section === "autorizaciones" ? [authorizationQuery] : [targetQuery, assessmentQuery, authorizationQuery];
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
    search={overview ? undefined : (item) => item.label}
    cells={(item) => ({ key: item.id, values: [item.label, date(item.created_at)] })}
    empty="Todavía no hay evaluaciones en este proyecto."
    more={!overview && assessmentQuery.hasNextPage && !assessmentQuery.isFetchingNextPage
      ? () => { void assessmentQuery.fetchNextPage(); } : undefined} />;

  const open = project.state === "active";
  if (section === "activos") return <div className="section-stack">
  {open && ctx.permissions.includes("targets:manage") && <NewTarget ctx={ctx} complete={() => { void targetQuery.refetch(); }} />}
  <Records title="Inventario de activos" items={targets}
    columns={["Activo", "Dirección", "Entorno"]}
    search={(item) => [item.slug, item.canonical_address, item.environment].join(" ")}
    cells={(item) => ({ key: item.id, values: [item.slug, <code>{item.canonical_address}</code>, item.environment] })}
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
    search={(item) => [item.revision, statusLabel(item.effective_status), date(item.valid_until)].join(" ")}
    cells={(item) => ({ key: item.id, values: [item.revision, <Status state={item.effective_status} />, date(item.valid_until)] })}
    empty="Todavía no hay autorizaciones en este proyecto."
    more={authorizationQuery.hasNextPage && !authorizationQuery.isFetchingNextPage
      ? () => { void authorizationQuery.fetchNextPage(); } : undefined} /></div>;

  const metrics = [
    { key: "activos", count: targets.length, more: targetQuery.hasNextPage, detail: "En el inventario" },
    { key: "evaluaciones", count: assessments.length, more: assessmentQuery.hasNextPage, detail: "Registradas" },
    { key: "autorizaciones", count: authorizations.length, more: authorizationQuery.hasNextPage, detail: "Revisiones actuales" },
  ] as const;
  const active = authorizations.filter((item) => item.effective_status === "active").length;
  return <>
    <section className="overview-hero" aria-label="Control del proyecto">
      <img src={shieldField} alt="" width="520" height="332" />
      <div className="hero-content">
        <span className="hero-tag"><ShieldCheck size={16} aria-hidden /> Revisión offline</span>
        <h2>Control de alcance</h2>
        <p>Verifica los activos y mandatos de este proyecto y consulta sus revisiones guardadas.</p>
        <div className="hero-actions">
          <Button variant="primary" asChild><a href="#planificador">Abrir planificador <ArrowRight size={16} aria-hidden /></a></Button>
          <Button asChild><a href="#historial"><ArrowDownToLine size={16} aria-hidden /> Consultar informe</a></Button>
        </div>
      </div>
    </section>
    <div className="metrics">{metrics.map(({ key, count, more, detail }) => {
    const { icon: Icon, name } = sections[key];
    return <a className="card metric" key={key} href={"#" + key}>
      <div className="metric-head"><span><Icon size={19} aria-hidden /></span><ArrowRight size={16} aria-hidden /></div>
      <h2>{name}</h2><strong className="metric-number">{count}{more ? "+" : ""}</strong><p>{detail}</p>
    </a>;
  })}</div><div className="dashboard-grid">
    {assessmentTable(true)}
    <div className="section-stack">
      <TeamSelection ctx={ctx} frozen={!open} />
      <Card className="form-card coverage-card">
      <div className="panel-title"><h2>Vigencia de mandatos</h2><ShieldCheck size={20} aria-hidden /></div>
      {authorizations.length ? <>
        <strong className="metric-number">{active}<span> / {authorizations.length}</span></strong>
        <progress aria-label="Mandatos activos entre los cargados" value={active} max={authorizations.length} />
        <p>Mandatos activos entre los cargados.</p>
      </> : <p>Este proyecto aún no tiene autorizaciones registradas.</p>}
      <a className="card-link" href="#autorizaciones">Ver autorizaciones <ArrowRight size={16} aria-hidden /></a>
      </Card>
    </div>
  </div></>;
}

export default function Workspace({ session }: { session: Models["SessionInfo"] }) {
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
  function chooseProject(next: string) {
    cache.removeQueries({ queryKey: ["project-data"] });
    if (planLocation()) location.hash = "planificador";
    setProject(next);
  }

  return <div className="shell">
    <a className="skip" href="#main" onClick={(event) => {
      const main = document.getElementById("main");
      if (main) { event.preventDefault(); main.focus(); }
    }}>Saltar al contenido</a>
    <aside className="sidebar"><Brand /><nav aria-label="Navegación principal">
      {Object.entries(sections).map(([key, { name, icon: Icon }]) => <a key={key} href={"#" + key}
        aria-current={section === key ? "page" : undefined}><Icon size={19} aria-hidden />{name}</a>)}
    </nav><div className="sidebar-footer"><span className="session-indicator"><Activity size={16} aria-hidden /> Sesión activa</span>
      <span>Open Source · By BLANDSKRON</span></div></aside>
    <div className="area"><header className="topbar"><div className="selectors">
      <Select label="Organización" options={orgs} value={org?.id ?? ""} change={(next) => {
        cache.removeQueries({ queryKey: ["project-data"] });
        if (planLocation()) location.hash = "planificador";
        setOrg(next); setProject("");
      }} />
      <Select label="Proyecto" options={projectList} value={project?.id ?? ""} change={chooseProject} />
    </div><div className="topbar-actions"><ThemeControl />
      <Button className="logout" aria-label="Cerrar sesión" disabled={logout.isPending} onClick={() => logout.mutate()}>
        <LogOut size={17} aria-hidden /><span>Cerrar sesión</span>
      </Button>
    </div></header>
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
        : section === "proyectos" ? <Records key={ctx.org} title="Proyectos de la organización"
            items={projectList} columns={["Proyecto", "Entorno", "Estado", "Acción"]}
            search={(item) => [item.slug, item.environment, statusLabel(item.state)].join(" ")}
            cells={(item) => ({ key: item.id, values: [item.slug, item.environment, <Status state={item.state} />,
              <Button asChild><a href="#resumen" aria-label={"Abrir proyecto " + item.slug}
                onClick={() => chooseProject(item.id)}>Abrir <ArrowRight size={14} aria-hidden /></a></Button>] })}
            empty="No hay proyectos disponibles en la organización seleccionada." />
        : project && org && section === "historial" ? <History key={ctx.org + ctx.project} ctx={ctx} />
        : project && org && section === "planificador" ? <Planner key={ctx.org + ctx.project} ctx={ctx} frozen={project.state !== "active"} />
        : project && org ? <ProjectContent key={ctx.org + ctx.project} user={session.user_id} org={org.id} project={project} section={section} ctx={ctx} />
        : <Card><Empty>{org ? "Todavía no tienes acceso a un proyecto en esta organización."
            : "Tu cuenta todavía no tiene una organización activa."}</Empty></Card>}
    </main></div>
  </div>;
}
