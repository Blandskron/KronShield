# Backlog de implementación

El [estado del proyecto](../STATUS.md#backlog-verificado) registra qué tareas están implementadas, parciales o pendientes. Las fichas siguientes conservan el alcance objetivo y los criterios originales.

46 tareas. P0 bloquea su hito, P1 aporta capacidad comprometida en ese hito. S/M/L/XL son tamaños relativos. Un XL se descompone en PR por contrato y fixture sin alterar sus dependencias ni su aceptación. Dependencias describen requisitos de merge. Las pruebas de cada tarea deben ser herméticas y la validación activa ocurre en laboratorio propio.

### **TASK-001 — Fijar línea base y convertir tests en herméticos**

- Épica. Base.
- Objetivo. Fijar línea base y convertir tests en herméticos.
- Problema que resuelve. Las pruebas actuales pueden consultar DNS y el historial conserva rutas de datos.
- Archivos o módulos afectados. tests/, .github/, .gitignore.
- Dependencias. Ninguna.
- Implementación esperada. Fixtures HTTP/socket/Groq locales. Inventario de requisitos y metadatos históricos con revisión restringida; sin reescribir Git.
- Pruebas requeridas. Pytest con red bloqueada y escaneo de rutas generadas.
- Criterios de aceptación verificables. Suite pasa sin DNS, red ni credenciales; registro de exposición histórica y resultado de revisión.
- Riesgos. Falsa confianza por mocks demasiado amplios.
- Prioridad. P0.
- Estimación de complejidad. S.
- Versión objetivo. v0.2.0.

### **TASK-002 — Modelar autorización y decisión de política**

- Épica. Alcance.
- Objetivo. Modelar autorización y decisión de política.
- Problema que resuelve. La CLI acepta destinos sin permiso comprobable.
- Archivos o módulos afectados. domain/, application/policy.
- Dependencias. Ninguna.
- Implementación esperada. Definir autorización inmutable, exclusiones, ventana, clase de atribución de tercero, técnica y decisión tipo; reloj inyectado.
- Pruebas requeridas. Tablas de verdad de ventana, entorno, exclusión, tercero.
- Criterios de aceptación verificables. Sin regla positiva o con exclusión, deny con motivo incluso si existe inclusión.
- Riesgos. Ambigüedad de reglas administrativas.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.2.0.

### **TASK-003 — Canonicalizar destinos y resolver DNS seguro**

- Épica. Alcance.
- Objetivo. Canonicalizar destinos y resolver DNS seguro.
- Problema que resuelve. Autoridad superficial e IPv6 mal parseado.
- Archivos o módulos afectados. domain/targets, adapters/dns.
- Dependencias. TASK-002.
- Implementación esperada. Resolver con política de A/AAAA y CNAME; validar normalización, puertos, IP especial y secretos en URL.
- Pruebas requeridas. Casos parametrizados IDNA, usuario, IPv4/IPv6, CNAME y RR mixto.
- Criterios de aceptación verificables. Todos los casos ambiguos y rangos bloqueados dan deny antes de conectar.
- Riesgos. Diferencias entre parsers.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.2.0.

### **TASK-004 — Construir transporte HTTP/TCP fijado a IP**

- Épica. Alcance.
- Objetivo. Construir transporte HTTP/TCP fijado a IP.
- Problema que resuelve. Los requests siguen redirects y conectan tras resolución propia.
- Archivos o módulos afectados. adapters/transport, core/recon.py, core/scanner.py.
- Dependencias. TASK-003.
- Implementación esperada. API de transporte con destino tipado, pin y revisión de peer; TLS original. Redirect desactivado; implementación opcional acotada por salto tras pruebas.
- Pruebas requeridas. TLS/SNI, redirect interno, rebinding, proxy de entorno y cuerpo grande.
- Criterios de aceptación verificables. Canario fuera de alcance recibe 0 conexiones; certificados se validan.
- Riesgos. Soporte TLS y pools de clientes.
- Prioridad. P0.
- Estimación de complejidad. XL.
- Versión objetivo. v0.2.0.

### **TASK-005 — Imponer presupuesto y esquema de configuración**

- Épica. Alcance.
- Objetivo. Imponer presupuesto y esquema de configuración.
- Problema que resuelve. Timeout individual y YAML sin rangos.
- Archivos o módulos afectados. domain/budget, core/settings.py, config/.
- Dependencias. TASK-002.
- Implementación esperada. Modelo tipado, deadline monotónica, conteos y bytes, límite de concurrencia local, abortar antes de IO al agotar.
- Pruebas requeridas. Ráfagas, deadline, bytes y config inválida.
- Criterios de aceptación verificables. Cada operación se debita y el fixture recibe hasta el presupuesto exacto.
- Riesgos. Relojes y lectura fragmentada.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.2.0.

### **TASK-006 — Eliminar el camino activo legado sin política**

- Épica. Núcleo.
- Objetivo. Eliminar el camino activo legado sin política.
- Problema que resuelve. Orquestador ejecuta payload de IA y red sin contexto.
- Archivos o módulos afectados. application/audit_service.py, cli/audit.py, core/, gpt/.
- Dependencias. TASK-002, TASK-004, TASK-005.
- Implementación esperada. Inyectar autorización y transporte; registrar adaptadores deterministas; bloquear perfiles activos hasta v0.5 y retirar texto de IA ejecutable.
- Pruebas requeridas. Acceso desde CLI e import directo, mocks que fallan al tocar red.
- Criterios de aceptación verificables. Comandos activos legacy quedan cerrados, dry run y análisis offline disponibles.
- Riesgos. Ruptura deliberada de parámetros incompatibles.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.2.0.

### **TASK-007 — Cerrar inyección HTML y rutas derivadas de URL**

- Épica. Núcleo.
- Objetivo. Cerrar inyección HTML y rutas derivadas de URL.
- Problema que resuelve. Dominio literal y ruta controlable por netloc.
- Archivos o módulos afectados. reports/renderer, cli/report.py.
- Dependencias. TASK-001.
- Implementación esperada. Escapar todo contexto, IDs de fichero, escritura atómica, entrada JSON limitada e informe determinista sin IA.
- Pruebas requeridas. Markup hostil, traversal Windows/Linux, colisión y HTML con caracteres.
- Criterios de aceptación verificables. Artefacto autocontenido sin scripts ni rutas fuera de directorio.
- Riesgos. Compatibilidad con descargas antiguas.
- Prioridad. P0.
- Estimación de complejidad. M.
- Versión objetivo. v0.2.0.

### **TASK-008 — Calibrar clasificación de XSS y SQLi**

- Épica. Núcleo.
- Objetivo. Calibrar clasificación de XSS y SQLi.
- Problema que resuelve. Reflexión y palabras genéricas se sobrerrepresentan.
- Archivos o módulos afectados. core/xss.py, core/sqli.py, domain/models.py.
- Dependencias. TASK-001, TASK-006.
- Implementación esperada. Preparar validadores y fixtures offline con baseline, parámetros codificados y niveles de confianza.
- Pruebas requeridas. Reflejo escapado, error SQL estático, query existente, pérdida de respuesta.
- Criterios de aceptación verificables. Ambos falsos positivos quedan como observación/sospecha; clasificación cubierta.
- Riesgos. Datos de fixture no representativos.
- Prioridad. P1.
- Estimación de complejidad. M.
- Versión objetivo. v0.2.0.

### **TASK-009 — Preservar resultados offline con transacciones**

- Épica. Núcleo.
- Objetivo. Preservar resultados offline con transacciones.
- Problema que resuelve. JSON se sobreescribe y fallos quedan como éxito.
- Archivos o módulos afectados. infra/repository.py, cli/, domain/.
- Dependencias. TASK-006, TASK-007.
- Implementación esperada. IDs nuevos, escribir JSON de forma atómica, DB con URL observada separada; exit codes de fallo parcial.
- Pruebas requeridas. Disco lleno simulado, error de commit, repetición mismo dominio.
- Criterios de aceptación verificables. No se pisa evidencia anterior ni se reporta éxito en fallo.
- Riesgos. Doble escritura de legado.
- Prioridad. P1.
- Estimación de complejidad. M.
- Versión objetivo. v0.2.0.

### **TASK-010 — Empaquetar núcleo y fijar dependencias**

- Épica. Base.
- Objetivo. Empaquetar núcleo y fijar dependencias.
- Problema que resuelve. CWD y dependencias mínimas abiertas.
- Archivos o módulos afectados. pyproject.toml, lockfile, CI.
- Dependencias. TASK-001, TASK-005.
- Implementación esperada. Entry point Typer instalable, lock con hashes y matriz Python soportada, acciones por SHA.
- Pruebas requeridas. Instalar entorno limpio y probar help en Windows/Linux.
- Criterios de aceptación verificables. CLI funciona desde otro CWD y CI resuelve de forma reproducible.
- Riesgos. Dependencias sin wheel en plataformas.
- Prioridad. P0.
- Estimación de complejidad. M.
- Versión objetivo. v0.2.0.

### **TASK-011 — Crear PostgreSQL, Alembic e aislamiento RLS**

- Épica. Backend.
- Objetivo. Crear PostgreSQL, Alembic e aislamiento RLS.
- Problema que resuelve. SQLite no modela tenant ni membresía.
- Archivos o módulos afectados. migrations/, adapters/persistence.
- Dependencias. TASK-002, TASK-010.
- Implementación esperada. Inicializar org, identidad, cliente, proyecto, autorización y objetivo; FK compuestas y rol no propietario.
- Pruebas requeridas. Upgrade limpio y fixtures 2 org/2 proyectos con pool reutilizado.
- Criterios de aceptación verificables. Lectura y escritura ajenas fallan en SQL y commit.
- Riesgos. Configuración RLS en worker.
- Prioridad. P0.
- Estimación de complejidad. XL.
- Versión objetivo. v0.3.0.

### **TASK-012 — Implementar sesión y permisos de proyecto**

- Épica. Backend.
- Objetivo. Implementar sesión y permisos de proyecto.
- Problema que resuelve. Faltan identidad y roles.
- Archivos o módulos afectados. adapters/api/auth, application/access.
- Dependencias. TASK-011.
- Implementación esperada. OIDC contract, sesión web, CSRF, contexto CLI y roles mínimos por acción.
- Pruebas requeridas. Claims, token revocado, rotación, CSRF y cambios de membresía.
- Criterios de aceptación verificables. 403/404 según semántica y pruebas de matriz rol/acción.
- Riesgos. Diferencias con proveedores OIDC.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.3.0.

### **TASK-013 — Exponer gestión de clientes, activos y autorizaciones**

- Épica. Backend.
- Objetivo. Exponer gestión de clientes, activos y autorizaciones.
- Problema que resuelve. No hay inventario ni registro verificable.
- Archivos o módulos afectados. adapters/api/engagements, application/.
- Dependencias. TASK-011, TASK-012.
- Implementación esperada. CRUD org/proyecto/cliente/target, revisión inmutable, carga de documento en almacén cifrado, lectura restringida y decisiones de autorización.
- Pruebas requeridas. Contrato, rol, vigencia y referencias cruzadas.
- Criterios de aceptación verificables. Operador y aprobador distintos completan flujo con digest registrado.
- Riesgos. Gestión de documentos sensibles.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.3.0.

### **TASK-014 — Persistir evaluaciones, planes, jobs y outbox**

- Épica. Backend.
- Objetivo. Persistir evaluaciones, planes, jobs y outbox.
- Problema que resuelve. Hallazgo no tiene ejecución ni procedencia.
- Archivos o módulos afectados. migrations/, application/plans, persistence/.
- Dependencias. TASK-011, TASK-013.
- Implementación esperada. Modelar plan tipado y hash, job y eventos, idempotencia y outbox. Crear plan dry-run.
- Pruebas requeridas. Carreras, revisión de autorización, upgrade y FK.
- Criterios de aceptación verificables. Dos solicitudes iguales recuperan un job; cambio de hash deniega.
- Riesgos. Transacciones de alta concurrencia.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.3.0.

### **TASK-015 — Importar SQLite y JSON legados en solo lectura**

- Épica. Backend.
- Objetivo. Importar SQLite y JSON legados en solo lectura.
- Problema que resuelve. Escaneos anteriores pueden perder contexto.
- Archivos o módulos afectados. adapters/cli/import, persistence/, tests/fixtures.
- Dependencias. TASK-009, TASK-011, TASK-014.
- Implementación esperada. Importación acotada con schemas, dry run y deduplicación por origen; asignación explícita de proyecto.
- Pruebas requeridas. Fixture de cada formato y entrada corrupta.
- Criterios de aceptación verificables. Contadores preservados y repetir no duplica; origen y confianza se muestran.
- Riesgos. URL específica inexistente en SQLite.
- Prioridad. P1.
- Estimación de complejidad. M.
- Versión objetivo. v0.3.0.

### **TASK-016 — Publicar OpenAPI, errores y health checks**

- Épica. Backend.
- Objetivo. Publicar OpenAPI, errores y health checks.
- Problema que resuelve. Sin contrato estable para clientes.
- Archivos o módulos afectados. adapters/api/, contracts/, CI.
- Dependencias. TASK-012, TASK-013, TASK-014.
- Implementación esperada. Modelos estrictos, Problem Details, esquema versionado, generación TS y probes.
- Pruebas requeridas. Contrato, códigos, cursor y setup con DB ausente.
- Criterios de aceptación verificables. Cambio incompatible cae en CI; ready refleja migración.
- Riesgos. Versionado cliente/servidor.
- Prioridad. P0.
- Estimación de complejidad. M.
- Versión objetivo. v0.3.0.

### **TASK-017 — Construir shell web, sesión y Dashboard**

- Épica. Experiencia.
- Objetivo. Construir shell web, sesión y Dashboard.
- Problema que resuelve. Sin frontend.
- Archivos o módulos afectados. frontend/src/app, frontend/src/ui.
- Dependencias. TASK-016.
- Implementación esperada. Vite, Tailwind, shadcn/ui, Query, navegación y tokens accesibles, estados vacíos.
- Pruebas requeridas. Playwright responsive y axe sobre shell.
- Criterios de aceptación verificables. Navegación autenticada 360/768/1440 y foco visible.
- Riesgos. Tokens visuales y componentes actualizables.
- Prioridad. P1.
- Estimación de complejidad. L.
- Versión objetivo. v0.4.0.

### **TASK-018 — Implementar altas y planificador dry-run**

- Épica. Experiencia.
- Objetivo. Implementar altas y planificador dry-run.
- Problema que resuelve. El operador no puede ver ni preparar alcance.
- Archivos o módulos afectados. frontend/src/features/.
- Dependencias. TASK-013, TASK-014, TASK-017.
- Implementación esperada. Organizaciones, clientes, proyectos, membresías, autorizaciones, objetivos, evaluación y vista de plan. RHF/Zod.
- Pruebas requeridas. E2E alta→alcance→plan; expiración y dos roles.
- Criterios de aceptación verificables. Renderiza sólo operaciones aplicables y motivo si plan bloqueado.
- Riesgos. Formularios con reglas complejas.
- Prioridad. P1.
- Estimación de complejidad. XL.
- Versión objetivo. v0.4.0.

### **TASK-019 — Crear Compose base y bootstrap inicial**

- Épica. Distribución.
- Objetivo. Crear Compose base y bootstrap inicial.
- Problema que resuelve. Un clon exige instalación manual y clave Groq.
- Archivos o módulos afectados. compose.yaml, Dockerfiles, deploy/, .env.example, README.
- Dependencias. TASK-010, TASK-016, TASK-017.
- Implementación esperada. Gateway/API/migrate/Postgres/Redis/objects/CLI, redes privadas, anclar bases, bootstrap y auth local exclusiva del piloto, build web multietapa, health. Excluir secretos y evidencias del contexto de build y permitir versionar .env.example.
- Pruebas requeridas. Compose desde cero, reinicio y puerto DB inaccesible.
- Criterios de aceptación verificables. Clon→up→login y datos sobreviven down/up; sin API key externa.
- Riesgos. UID y permisos en Docker Desktop.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.4.0.

### **TASK-020 — Crear cliente Typer para los casos de uso web**

- Épica. Experiencia.
- Objetivo. Crear cliente Typer para los casos de uso web.
- Problema que resuelve. CLI mezcla persistencia y ejecución.
- Archivos o módulos afectados. adapters/cli, contracts/.
- Dependencias. TASK-010, TASK-016, TASK-019.
- Implementación esperada. Auth, estado, listar, alta lab, plan, datos JSON y representación de comandos.
- Pruebas requeridas. Pruebas de quoting Bash/PowerShell y contrato con API.
- Criterios de aceptación verificables. Un plan creado por CLI se abre en frontend con mismo ID/permisos.
- Riesgos. Almacenamiento de tokens del CLI efímero.
- Prioridad. P0.
- Estimación de complejidad. M.
- Versión objetivo. v0.4.0.

### **TASK-021 — Implementar dispatcher, Celery y lease**

- Épica. Ejecución.
- Objetivo. Implementar dispatcher, Celery y lease.
- Problema que resuelve. No hay ejecución durable.
- Archivos o módulos afectados. dispatcher/, worker/, adapters/celery.
- Dependencias. TASK-014, TASK-019.
- Implementación esperada. Outbox y publisher, leases con fencing, estados y política antes de IO, recuperación sin duplicar tráfico.
- Pruebas requeridas. Redis cae, redelivery, dos workers y pérdida de lease.
- Criterios de aceptación verificables. Job recupera antes del IO y se interrumpe sin replay tras IO.
- Riesgos. Semántica al menos una vez.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.5.0.

### **TASK-022 — Aislar runner, egress y cuotas compartidas**

- Épica. Ejecución.
- Objetivo. Aislar runner, egress y cuotas compartidas.
- Problema que resuelve. Los adaptadores podrían saltar scope o límites.
- Archivos o módulos afectados. runner/, egress/, worker/.
- Dependencias. TASK-004, TASK-005, TASK-006, TASK-021.
- Implementación esperada. Manifiesto, red cerrada, red por flujo, entorno mínimo, límites cgroup y buckets atómicos; sin socket Docker.
- Pruebas requeridas. Intento de metadata, salida directa, path, env y argumentos hostiles.
- Criterios de aceptación verificables. Probe externo bloqueado y concurrencia calculada globalmente.
- Riesgos. Aislamiento Compose difiere del entorno empresarial.
- Prioridad. P0.
- Estimación de complejidad. XL.
- Versión objetivo. v0.5.0.

### **TASK-023 — Implementar cancelación y kill switches**

- Épica. Ejecución.
- Objetivo. Implementar cancelación y kill switches.
- Problema que resuelve. Una auditoría activa no puede parar.
- Archivos o módulos afectados. application/, worker/, egress/, API.
- Dependencias. TASK-021, TASK-022.
- Implementación esperada. Estado durable, leases de salida revocados, TERM/KILL y invalidación por org/global.
- Pruebas requeridas. Jobs en cola, en conexión, en kill concurrente y supervisor perdido.
- Criterios de aceptación verificables. Sin IO nuevo tras revocación y runner lab muerto antes de 2 s o interrumpido.
- Riesgos. Ventana entre revocar y cerrar socket.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.5.0.

### **TASK-024 — Conectar web y CLI a jobs y SSE**

- Épica. Ejecución.
- Objetivo. Conectar web y CLI a jobs y SSE.
- Problema que resuelve. Falta consola y equivalencia de acciones.
- Archivos o módulos afectados. frontend/, adapters/api/, adapters/cli.
- Dependencias. TASK-018, TASK-020, TASK-021, TASK-023.
- Implementación esperada. Ejecutar plan, enviar idempotencia, ver estado y logs, reconectar y cancelar. Copiar representación CLI por shell.
- Pruebas requeridas. SSE corte, resume cursors, 410, RBAC y paridad.
- Criterios de aceptación verificables. Web inicia, CLI sigue/cancela, ambos muestran misma secuencia.
- Riesgos. Proxy buffering.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.5.0.

### **TASK-025 — Entregar recorrido clon a informe en laboratorio**

- Épica. Ejecución.
- Objetivo. Entregar recorrido clon a informe en laboratorio.
- Problema que resuelve. No hay primer producto utilizable.
- Archivos o módulos afectados. lab/, compose.yaml, tests/e2e, README.
- Dependencias. TASK-007, TASK-019, TASK-022, TASK-023, TASK-024.
- Implementación esperada. Fixture lab aislado, seed, web-baseline GET, límites, bitácora append-only por rol y evidencia cifrada, informe HTML determinista y descarga.
- Pruebas requeridas. E2E limpio Linux y Windows/Docker Desktop, fuera de alcance, reinicio y bitácora verificable.
- Criterios de aceptación verificables. Comandos documentados y UI completan flujo de laboratorio sin tráfico externo.
- Riesgos. Portabilidad y fixtures de red.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.5.0.

### **TASK-026 — Añadir proveedores tipados y presupuesto**

- Épica. IA.
- Objetivo. Añadir proveedores tipados y presupuesto.
- Problema que resuelve. Groq global con dependencia obligatoria.
- Archivos o módulos afectados. adapters/llm, application/analysis.
- Dependencias. TASK-006, TASK-012, TASK-019.
- Implementación esperada. Proveedor Groq y local, fallback determinista, cuota y ledger, referencias de secretos.
- Pruebas requeridas. Modelo simulado, límite, timeout, fallos y redacción.
- Criterios de aceptación verificables. Sin clave funciona flujo base; análisis excedido no invoca proveedor.
- Riesgos. Semántica de tokens y precios.
- Prioridad. P1.
- Estimación de complejidad. L.
- Versión objetivo. v0.6.0.

### **TASK-027 — Implementar gateway de contexto y herramientas**

- Épica. IA.
- Objetivo. Implementar gateway de contexto y herramientas.
- Problema que resuelve. Prompt incluye datos no confiables.
- Archivos o módulos afectados. application/analysis, domain/analysis.
- Dependencias. TASK-012, TASK-014, TASK-026.
- Implementación esperada. Redactar y limitar, allowlists de herramientas y datos, log de decisiones, outputs Pydantic.
- Pruebas requeridas. Inyección, referencias ajenas, secrets sintéticos y respuesta gigante.
- Criterios de aceptación verificables. Sin fuga en fixtures, sin tool calls fuera del contrato y sin planes ejecutados.
- Riesgos. Redacción imperfecta y modelos no deterministas.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.6.0.

### **TASK-028 — Implementar agentes de análisis y revisión humana**

- Épica. IA.
- Objetivo. Implementar agentes de análisis y revisión humana.
- Problema que resuelve. Sólo hay resumen Markdown libre.
- Archivos o módulos afectados. application/analysis, frontend/src/analysis.
- Dependencias. TASK-024, TASK-026, TASK-027.
- Implementación esperada. Grafo fijo, diez contratos de agentes, UI de presupuesto, aprobación y control de proveedor.
- Pruebas requeridas. Golden por agente, evidencia insuficiente y rutas de publicación.
- Criterios de aceptación verificables. Cada agente cita evidencia autorizada y su borrador exige revisión.
- Riesgos. Datos de algunas técnicas aún no disponibles.
- Prioridad. P1.
- Estimación de complejidad. XL.
- Versión objetivo. v0.6.0.

### **TASK-029 — Extender inventario DNS, TLS y fingerprint**

- Épica. Capacidades.
- Objetivo. Extender inventario DNS, TLS y fingerprint.
- Problema que resuelve. Recon actual sólo emite cabeceras y GET.
- Archivos o módulos afectados. adapters/tools/recon, lab/.
- Dependencias. TASK-022, TASK-025.
- Implementación esperada. DNS acotado y TLS pinneado, normalizar fingerprints y un adaptador testssl opcional.
- Pruebas requeridas. Certificado expirado, RR fuera de alcance, fixtures TLS.
- Criterios de aceptación verificables. REC-03/04/06 emiten evidencia y bloquean salidas no pactadas.
- Riesgos. SNI y licencia de herramienta.
- Prioridad. P1.
- Estimación de complejidad. L.
- Versión objetivo. v0.7.0.

### **TASK-030 — Integrar evaluación de red acotada**

- Épica. Capacidades.
- Objetivo. Integrar evaluación de red acotada.
- Problema que resuelve. Sondeo TCP simple y sin telemetría.
- Archivos o módulos afectados. adapters/tools/network, runner/, lab/.
- Dependencias. TASK-022, TASK-023, TASK-029.
- Implementación esperada. Nmap opcional sujeto a licencia, TCP/UDP compatibles con egress, configuración SSH/DNS/SMB y matriz de ACL.
- Pruebas requeridas. IP/puertos extra, timeout UDP, puertos abiertos y runner dedicado.
- Criterios de aceptación verificables. NET-01 a NET-04 generan salida normalizada y exclusiones verificadas.
- Riesgos. Privilegios UDP y redistribución NPSL.
- Prioridad. P1.
- Estimación de complejidad. XL.
- Versión objetivo. v0.7.0.

### **TASK-031 — Integrar análisis de artefactos y cloud de lectura**

- Épica. Capacidades.
- Objetivo. Integrar análisis de artefactos y cloud de lectura.
- Problema que resuelve. Sin SAST/SCA/SBOM/IaC ni cloud.
- Archivos o módulos afectados. adapters/tools/artifacts, adapters/tools/cloud.
- Dependencias. TASK-022, TASK-025.
- Implementación esperada. Trivy, Semgrep, Gitleaks, Checkov y Prowler bajo perfiles opt-in y schema por herramienta.
- Pruebas requeridas. Fixtures golden, secretos sintéticos, bloqueos de mutación y SBOM.
- Criterios de aceptación verificables. CLD y SRC emiten evidencia sin ejecutar imagen ni modificar cloud.
- Riesgos. RAM, fuentes, licencias de reglas y límites cloud.
- Prioridad. P1.
- Estimación de complejidad. XL.
- Versión objetivo. v0.7.0.

### **TASK-032 — Integrar perfiles web/API de laboratorio**

- Épica. Capacidades.
- Objetivo. Integrar perfiles web/API de laboratorio.
- Problema que resuelve. XSS/SQLi heurísticos y API ausente.
- Archivos o módulos afectados. adapters/tools/dast, lab/web-api, frontend/.
- Dependencias. TASK-008, TASK-022, TASK-023, TASK-025.
- Implementación esperada. ZAP y catálogo curado Nuclei, pruebas WSTG/API con baselines, cuentas sintéticas y aprobaciones. Dividir por perfil-versionado.
- Pruebas requeridas. Positivo/negativo por técnica, redirecciones, HTTP state y presupuestos.
- Criterios de aceptación verificables. Filas WEB/API asignadas a esta tarea trazadas por fixture y control.
- Riesgos. Comportamiento de spider y carga DAST.
- Prioridad. P1.
- Estimación de complejidad. XL.
- Versión objetivo. v0.7.0.

### **TASK-033 — Evaluar identidad empresarial y defensas sintéticas**

- Épica. Capacidades.
- Objetivo. Evaluar identidad empresarial y defensas sintéticas.
- Problema que resuelve. Sin MFA, bloqueo ni políticas AD.
- Archivos o módulos afectados. adapters/tools/identity, lab/identity.
- Dependencias. TASK-022, TASK-023, TASK-025.
- Implementación esperada. Registro de cuentas de prueba autoriza endpoint, cuentas y presupuesto. Defaults propuestos por escenario de R2: 5 intentos totales, 3 por cuenta, pausa 2 s, detener en 423/429/MFA o alerta. Config AD de lectura.
- Pruebas requeridas. Políticas LDAP/Kerberos, MFA, bloqueo y alerta de fixture.
- Criterios de aceptación verificables. IDN/AD aplicables producen métrica y bloquean cuentas fuera de lista.
- Riesgos. Riesgo de lockout incluso con bajo tráfico.
- Prioridad. P1.
- Estimación de complejidad. XL.
- Versión objetivo. v0.7.0.

### **TASK-034 — Crear flujo supervisado R3 y registro móvil manual**

- Épica. Capacidades.
- Objetivo. Crear flujo supervisado R3 y registro móvil manual.
- Problema que resuelve. Sin demostración controlada ni trazabilidad móvil.
- Archivos o módulos afectados. application/approvals, runner/, frontend/, lab/.
- Dependencias. TASK-023, TASK-024, TASK-032, TASK-033.
- Implementación esperada. Perfiles R3 apagados y activables sólo para lab piloto, doble aprobación, teardown. Casos sintéticos de simulación y registro MASVS/MASTG.
- Pruebas requeridas. Revocación concurrente, límites, limpieza y controles defensivos.
- Criterios de aceptación verificables. Sin aprobaciones o fixture sintético no arranca; efecto y cierre auditados.
- Riesgos. Especialistas y coste de laboratorio.
- Prioridad. P1.
- Estimación de complejidad. XL.
- Versión objetivo. v0.7.0.

### **TASK-035 — Cifrar, retener y anclar evidencia y operaciones**

- Épica. Evidencia.
- Objetivo. Cifrar, retener y anclar evidencia y operaciones.
- Problema que resuelve. Sin cadena de custodia ni protección de datos.
- Archivos o módulos afectados. adapters/storage, application/audit_log, migrations/.
- Dependencias. TASK-013, TASK-014, TASK-021, TASK-025.
- Implementación esperada. Objetos cifrados, SHA-256, ACL, comprobación de descarga, retención, hold, anclaje WORM externo.
- Pruebas requeridas. Corrupción, objeto huérfano, borrado, restauración y anclaje retrasado.
- Criterios de aceptación verificables. Evidencia verificable y eventos reconstruibles por actor/técnica/objetivo.
- Riesgos. Costos de almacenamiento y cumplimiento.
- Prioridad. P0.
- Estimación de complejidad. XL.
- Versión objetivo. v0.8.0.

### **TASK-036 — Revisar hallazgos y comparar historial**

- Épica. Evidencia.
- Objetivo. Revisar hallazgos y comparar historial.
- Problema que resuelve. Tipos carecen de certeza y contexto.
- Archivos o módulos afectados. domain/findings, adapters/api, frontend/.
- Dependencias. TASK-024, TASK-035.
- Implementación esperada. FSM, lineaje evidencia, diff por huella y filtros, trazabilidad de revisión.
- Pruebas requeridas. Negativos, scope distinto, diff y entradas compartidas.
- Criterios de aceptación verificables. Confirmación exige evidencia y decisión de revisor; comparaciones explican cobertura.
- Riesgos. Cambios de huella.
- Prioridad. P1.
- Estimación de complejidad. L.
- Versión objetivo. v0.8.0.

### **TASK-037 — Correlacionar catálogos y medir riesgo**

- Épica. Evidencia.
- Objetivo. Correlacionar catálogos y medir riesgo.
- Problema que resuelve. No hay fuentes CVE/CWE ni CVSS calculado.
- Archivos o módulos afectados. adapters/catalogs, domain/risk, frontend/.
- Dependencias. TASK-029, TASK-031, TASK-035, TASK-036.
- Implementación esperada. Importar snapshots CVE/NVD/CWE, reglas por versión y contexto, calcular CVSS 4.0 y visualizar riesgo.
- Pruebas requeridas. Fixtures upstream, cpe/version edge cases y vectores de referencia.
- Criterios de aceptación verificables. No promueve correlación ambigua a confirmación; conserva fuente.
- Riesgos. Versiones backport y cuotas de catálogo.
- Prioridad. P1.
- Estimación de complejidad. XL.
- Versión objetivo. v0.8.0.

### **TASK-038 — Publicar informe ejecutivo y técnico versionado**

- Épica. Evidencia.
- Objetivo. Publicar informe ejecutivo y técnico versionado.
- Problema que resuelve. Reporte textual sin revisión.
- Archivos o módulos afectados. reports/, API, frontend/, CLI.
- Dependencias. TASK-007, TASK-028, TASK-035, TASK-036, TASK-037.
- Implementación esperada. Snapshots, render HTML determinista, borrador IA opcional, aprobación, descarga y comparación.
- Pruebas requeridas. Escapes, revisión, idempotencia, equivalencia CLI/web.
- Criterios de aceptación verificables. Informe publicado rastreable a evidencia y reproducible por snapshot.
- Riesgos. Compatibilidad de plantillas.
- Prioridad. P1.
- Estimación de complejidad. L.
- Versión objetivo. v0.8.0.

### **TASK-039 — Integrar SSO corporativo y ciclo de identidad**

- Épica. Empresa.
- Objetivo. Integrar SSO corporativo y ciclo de identidad.
- Problema que resuelve. Bootstrap local no satisface identidad empresarial.
- Archivos o módulos afectados. adapters/api/auth, deploy/, frontend/.
- Dependencias. TASK-012, TASK-018, TASK-025.
- Implementación esperada. IdP externo OIDC, sesiones y auditoría de altas/bajas, rotación y servicios de alcance mínimo.
- Pruebas requeridas. Proveedor real de test, revocar identidad y credencial.
- Criterios de aceptación verificables. Usuarios con baja pierden API, CLI y stream en SLA definido.
- Riesgos. Variaciones de claims y flujo Device.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.9.0.

### **TASK-040 — Instalar quality gates de seguridad y release**

- Épica. Empresa.
- Objetivo. Instalar quality gates de seguridad y release.
- Problema que resuelve. CI parcial y sin builds verificados.
- Archivos o módulos afectados. .github/, tests/contract, tests/e2e.
- Dependencias. TASK-010, TASK-016, TASK-022, TASK-024.
- Implementación esperada. Lint/tipos, contratos, RLS, SSRF, SAST/SCA/secret scan, SBOM, firmas y atestaciones; orquestar CI sin objetivos externos.
- Pruebas requeridas. Inyectar regresión de cada gate sobre fixture aislado.
- Criterios de aceptación verificables. Pipeline bloquea release si falla guía o tests; licencia/dep inventariadas.
- Riesgos. Flakiness e imágenes transitorias.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.9.0.

### **TASK-041 — Instrumentar y ensayar recuperación**

- Épica. Empresa.
- Objetivo. Instrumentar y ensayar recuperación.
- Problema que resuelve. Sin métricas, restauración ni SLO.
- Archivos o módulos afectados. deploy/observability, docs/ops, tests/chaos.
- Dependencias. TASK-019, TASK-023, TASK-035, TASK-040.
- Implementación esperada. OTel, métricas/SLO, alertas de queue/kill/fuga y runbook de backup/restauración.
- Pruebas requeridas. Simular caída de worker/Redis y restaurar DB/objetos/anclajes.
- Criterios de aceptación verificables. Verifica interrupción, no replay y recuperación medidos.
- Riesgos. Capacidad de almacenamiento y cardinalidad.
- Prioridad. P0.
- Estimación de complejidad. L.
- Versión objetivo. v0.9.0.

### **TASK-042 — Validar integraciones de terceros en perfiles opt-in**

- Épica. Empresa.
- Objetivo. Validar integraciones de terceros en perfiles opt-in.
- Problema que resuelve. Sin decisión por licencia/digest, feeds e infraestructura.
- Archivos o módulos afectados. adapters/integrations, frontend/, deploy/.
- Dependencias. TASK-030, TASK-031, TASK-032, TASK-035, TASK-040.
- Implementación esperada. Configuración de catálogo y salud de integraciones, licencias, pinning y perfil Greenbone opcional, docs de actualización.
- Pruebas requeridas. Sandbox de instalación y salida adversaria por herramienta.
- Criterios de aceptación verificables. Cada habilitada tiene SBOM/licencia, fixture, hash y error seguro; Greenbone con decisión documentada.
- Riesgos. Términos y consumo de feed.
- Prioridad. P1.
- Estimación de complejidad. L.
- Versión objetivo. v0.9.0.

### **TASK-043 — Certificar piloto multiempresa y revisiones de seguridad**

- Épica. Estable.
- Objetivo. Certificar piloto multiempresa y revisiones de seguridad.
- Problema que resuelve. No existe evidencia de uso integrado.
- Archivos o módulos afectados. tests/e2e, docs/ops.
- Dependencias. TASK-034, TASK-038, TASK-039, TASK-040, TASK-041, TASK-042.
- Implementación esperada. Ensayo con dos organizaciones sobre lab, test de seguridad, accesibilidad y LLM; remediar P0/P1.
- Pruebas requeridas. E2E longitudinal, RLS, SSRF, kill, QoS y regresiones.
- Criterios de aceptación verificables. Cero P0/P1 abiertos y acta de aceptación con evidencia reproducible.
- Riesgos. Tiempo de especialistas y privacidad.
- Prioridad. P0.
- Estimación de complejidad. XL.
- Versión objetivo. v1.0.0.

### **TASK-044 — Documentar instalación, soporte y actualización**

- Épica. Estable.
- Objetivo. Documentar instalación, soporte y actualización.
- Problema que resuelve. Falta guía versionada para operador.
- Archivos o módulos afectados. README.md, docs/ops, deploy/.
- Dependencias. TASK-025, TASK-039, TASK-041, TASK-042.
- Implementación esperada. Guía clon/Linux/Windows, config, web/CLI, terceros y costos, upgrade/rollback, respaldo y límites de cobertura.
- Pruebas requeridas. Ejecutar guía por operador independiente y verificar comandos.
- Criterios de aceptación verificables. Instalación y actualización verificadas desde checkout limpio.
- Riesgos. Cambios en Docker Desktop y dispositivos ARM.
- Prioridad. P0.
- Estimación de complejidad. M.
- Versión objetivo. v1.0.0.

### **TASK-045 — Medir desempeño y validar presupuesto de producción**

- Épica. Estable.
- Objetivo. Medir desempeño y validar presupuesto de producción.
- Problema que resuelve. Capacidad y SLA sin referencia empírica.
- Archivos o módulos afectados. tests/load, deploy/, docs/ops.
- Dependencias. TASK-038, TASK-041, TASK-043.
- Implementación esperada. Prueba sostenida con 2 tenants y carga simulada, dimensionamiento y presupuesto; degradación segura.
- Pruebas requeridas. Carga, interrupción, restauración y duplicados.
- Criterios de aceptación verificables. SLO y coste medidos para topología ensayada y kill sigue funcionando.
- Riesgos. Generalización de carga lab a producción.
- Prioridad. P1.
- Estimación de complejidad. L.
- Versión objetivo. v1.0.0.

### **TASK-046 — Publicar entrega v1.0.0 reproducible**

- Épica. Estable.
- Objetivo. Publicar entrega v1.0.0 reproducible.
- Problema que resuelve. No existe distribución estable con soporte.
- Archivos o módulos afectados. .github/, deploy/, docs/ops.
- Dependencias. TASK-043, TASK-044, TASK-045.
- Implementación esperada. Release firmada, imágenes amd64/arm64 según verificación, notas, SBOM y procedimiento de actualización.
- Pruebas requeridas. Instalación desde tag, verificar firma/digest y ruta de rollback.
- Criterios de aceptación verificables. Tag e imágenes verificables y puente externo de compatibilidad publicado.
- Riesgos. Fallos de build multiarch.
- Prioridad. P0.
- Estimación de complejidad. M.
- Versión objetivo. v1.0.0.
