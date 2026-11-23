# Plan de evolución de BLANDSKRON Pentest Agent

La planificación parte de la auditoría sobre `61e08eae0b7674d9046050ee8313457fc60fa27c`. El repositorio ya ofrece un piloto offline con API, web, CLI, PostgreSQL y simulaciones guardadas. Para saber cuáles son las funciones disponibles, consulta el [estado del proyecto](../STATUS.md). Las secciones de arquitectura objetivo describen fases futuras.

| Documento | Contenido |
|---|---|
| [AUDIT_REPORT.md](AUDIT_REPORT.md) | Evidencia de la línea base, arquitectura efectiva, riesgos y verificaciones. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Capas, servicios, Mermaid, distribución Docker y flujo clone→web/CLI. |
| [GAP_ANALYSIS.md](GAP_ANALYSIS.md) | Brechas priorizadas y puntos de reutilización. |
| [SECURITY_CAPABILITIES.md](SECURITY_CAPABILITIES.md) | Estándares, 50 capacidades, criterios y adaptadores. |
| [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md) | Diez analistas, herramientas permitidas, presupuestos y revisión. |
| [FRONTEND_SPEC.md](FRONTEND_SPEC.md) | Wireframes, 18 módulos y consola de operaciones tipadas. |
| [API_SPEC.md](API_SPEC.md) | Contratos FastAPI/OpenAPI, identidad, SSE y equivalencia web/CLI. |
| [DATABASE_DESIGN.md](DATABASE_DESIGN.md) | Entidades, migraciones, RLS, índices y legado. |
| [SECURITY_MODEL.md](SECURITY_MODEL.md) | Alcance, autorizaciones, límites, egress, supervisión y custodia. |
| [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) | Entregas, costos, dependencias y condiciones por versión. |
| [TASK_BACKLOG.md](TASK_BACKLOG.md) | 46 tareas verificables con dependencias y versiones. |
| [IMPLEMENTATION_ORDER.md](IMPLEMENTATION_ORDER.md) | Rutas críticas, primeras 10 tareas, gates y estrategia de pruebas. |

**Hito verificado del piloto.** Compose inicia la plataforma; la web y la CLI comparten la revisión de alcance, el plan persistido y el informe descargable. Para instalarlo o restaurarlo, consulta la [guía operativa](../OPERATIONS.md).

**Dependencias críticas.** Transporte y política antes de workers. RLS y autorización persistida antes de la API de jobs. Egress y cancelación antes de pruebas de red. Custodia, SSO, evaluación de aislamiento y restauración antes de habilitar clientes externos.
