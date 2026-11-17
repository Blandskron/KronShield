# Especificación del frontend

Aplicación React/TypeScript/Vite, Tailwind CSS y componentes shadcn/ui, TanStack Query para caché, React Hook Form con Zod para formularios y Recharts para tendencias. Transporte SSE del mismo origen. El contrato OpenAPI genera tipos de API, mientras Zod valida formularios y eventos al entrar. La autorización visible se obtiene de `/me`; la API hace cumplir las decisiones. Reiniciar caché y streams cuando cambien organización, proyecto o sesión.

## Wireframes

```text
Escritorio
┌ BLANDSKRON ── Organización ▾  Proyecto ▾ ── Sesión ▾ ┐
│ Resumen                                             │
│ ┌ Hallazgos por riesgo ───┐ ┌ Estado de auditorías ┐ │
│ │ Barras y tabla accesible│ │  Actividad por fecha │ │
│ └─────────────────────────┘ └─────────────────────┘ │
│ ┌ Ejecuciones recientes ─────────────────────────┐ │
│ └─────────────────────────────────────────────────┘ │
└  Resumen  Proyectos  Auditorías  Hallazgos  Ajustes ┘

Planificador
┌ Proyecto > Auditorías > Nuevo plan ────────────────┐
│ Objetivos [selección]    Autorización [revisión ▾]   │
│ Perfil [web-baseline ▾]  Límite efectivo [lectura]  │
│ [Validar plan]   Alcance, ventana, denegaciones     │
│ [Solicitar aprobación] / [Ejecutar] [Copiar CLI]    │
└─────────────────────────────────────────────────────┘

Consola
┌ Job / estado / duración / [Cancelar] ───────────────┐
│ [Nivel ▾] [Pausar autoscroll] [Copiar ID]            │
│ 12:00:00   Alcance verificado                       │
│ 12:00:01   GET completado                           │
│ 12:00:02   Evidencia registrada                     │
│ Reconectando… cursor 42        [Ver hallazgos]      │
└─────────────────────────────────────────────────────┘

Móvil
┌ BLANDSKRON  Proyecto ▾ ───┐
│ Estado y acción principal │
│ Tarjetas en una columna   │
│ Filtros en panel          │
└ Resumen / Jobs / Más ─────┘
```

## Pantallas y comportamientos

| # | Ruta / módulo | Vista, flujo y estados especiales | Versión |
|---|---|---|---|
| 1 | `/dashboard` · ejecutivo | Riesgos, evaluaciones y estado reciente. Cada KPI abre lista filtrada. HTML tabular alternativo por gráfico. | v0.4/v0.8 |
| 2 | `/organizations` | Selector, admins y retención. Acceso de plataforma para alta. Advertir cambio de contexto sin guardar. | v0.4 |
| 3 | `/customers` | Tabla, búsqueda, alta y proyectos relacionados. Validación por campo. | v0.4 |
| 4 | `/projects` | Tarjetas/tabla, filtros y detalle con tabs Inventario, Alcance y Actividad. | v0.4 |
| 5 | `/projects/:p/authorizations` | Documento, tercero, ventanas, exclusiones, reglas y aprobación/revocación con motivo. Mostrar vigencia en UTC y zona local. | v0.4 |
| 6 | `/projects/:p/targets` | Inventario, entorno, titular y relación con alcance. Resaltar entradas excluidas. | v0.4 |
| 7 | `/projects/:p/assessments` | Crear evaluación, elegir objetivo y revisión. Historial de ejecuciones. | v0.4 |
| 8 | `/projects/:p/plans/:id` | Simular; ver presupuesto, autorizaciones y permisos. Aprobación independiente, revalidación al ejecutar. | v0.4/v0.5 |
| 9 | `/projects/:p/jobs/:id` | Eventos filtrables, estados terminales, cursor y evidencia parcial. Cancelación requiere motivo y muestra solicitud y confirmación. | v0.5 |
| 10 | `/projects/:p/analysis` | Proveedor, tipo de analista, evidencia que se compartirá, costo y revisión de borrador con citas. | v0.6 |
| 11 | `/projects/:p/findings` | Tabla filtrada por confianza, gravedad, CWE y estado. Detalle con historial y decisión del revisor. | v0.8 |
| 12 | `/projects/:p/evidence` | Metadatos, digest, clasificación, expiración y descarga autorizada. Binarios como attachment. | v0.8 |
| 13 | `/projects/:p/risk` | Distribución de impacto y probabilidad, CVSS y contexto. Tabla con motivo y conteos. | v0.8 |
| 14 | `/projects/:p/reports` | Generar/exportar, comparar borrador con publicado, revisar y publicar. | v0.5/v0.8 |
| 15 | `/projects/:p/history` | Selección de ejecutados comparables e historial por huella. Mostrar diferencias por cambio de perfil/alcance. | v0.8 |
| 16 | `/settings/access` | Usuarios, roles, alcance de membresía, auditoría de cambios y estado SSO. | v0.4/v0.9 |
| 17 | `/settings/tools` | Catálogo, versión, riesgo, perfiles disponibles y motivo de indisponibilidad. | v0.5/v0.7 |
| 18 | `/settings/integrations` | Configuración por organización, salud, referencias de secretos y costos. Nunca devolver valores de secretos. | v0.6/v0.9 |

## Operaciones compartidas entre web y CLI

Consola de ejecución con entrada por formularios de operación. Botón «Copiar CLI» con selector Bash/PowerShell, parámetros canónicos públicos y nunca tokens ni secretos. «Ejecutar» presenta objetivo, ventana, técnicas y límites del plan de la API. El operador confirma el plan y la UI envía ID, hash e idempotencia. La web y CLI pueden abrir el mismo job y ver la misma secuencia. El historial registra el origen. Las operaciones quedan limitadas al catálogo. La consola muestra salida estructurada y redactada como texto. Las secuencias de control se eliminan antes de emitir eventos.

## Sistema visual y accesibilidad

Wordmark BLANDSKRON, fondo grafito `#0B1020`, panel `#172138`, texto `#F1F5F9`, acento `#67E8F9`, advertencia `#FBBF24`. Geist para UI, IBM Plex Mono para IDs y eventos. Malla de degradado de baja intensidad detrás de paneles opacos con transparencia limitada. Navegación flotante compacta y rejilla de 12 columnas en escritorio, 6 en tablet y 1 en móvil. En job, prioridad a estado, cancelación y salida. Reducir motion según preferencia. Accesibilidad objetivo WCAG 2.2 AA: foco visible, contraste medido, navegación teclado, controles con nombres, estados por icono/texto además de color, orden de tabulación y objetivo táctil suficiente. Usar live region para transiciones; pausar autoscroll al seleccionar o desplazarse.

Cada pantalla tiene cargando, vacío, sin permiso, error recuperable y estado operativo. Si SSE cae, retener eventos, retroceder exponencialmente con jitter y recargar estado si expira el cursor. Mostrar actividad terminal antes de detener la reconexión. Probar 360, 768 y 1440 px, zoom 200%, teclado y prueba con lector. E2E cubre alta de proyecto/target/autorización, simulación, aprobación, job desde UI y lectura por CLI, cancelación, reporte y denegación de un segundo tenant.
