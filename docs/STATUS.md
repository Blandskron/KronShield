# Estado de KronShield

Revisión del 26 de noviembre de 2026. El selector de especialidad y la gobernanza de evidencias parten del commit [a79d61a](https://github.com/Blandskron/KronShield/commit/a79d61a810a17f213408debb355700d29f850add). Los números del roadmap identifican hitos funcionales. La versión del paquete Python en `pyproject.toml` es `0.2.0`.

El recorrido actual permite iniciar sesión en el piloto, configurar una organización y un proyecto, registrar activos y evaluaciones, gestionar autorizaciones con aprobación separada y simular el alcance. La web y la CLI consultan el mismo plan guardado. El informe HTML refleja la instantánea histórica de la revisión. La ejecución activa está deshabilitada.

| Área | Disponible |
|---|---|
| CLI local | Vista previa de destinos, análisis de capturas HTTP guardadas, persistencia en JSON y SQLite e informes locales. |
| Piloto | Docker Compose, gateway en loopback, PostgreSQL, login local con bootstrap de un solo uso y cliente Typer. |
| API y web | OIDC configurable, membresías, inventario, mandatos PDF cifrados, evaluaciones, revisión de alcance e importación legada. |
| Análisis offline | Selección de especialidad por proyecto, permisos de evidencia, revisión determinista de registros de alcance, inferencia local optativa, aprobación y descarga del informe. |
| Blue Team | Importación de lotes autorizados y triaje determinista de fallos de autenticación en el planificador, con revisión humana e informe. |
| Trazabilidad | SHA-256 del mandato y del plan, revisiones inmutables, decisiones y eventos de la simulación. |
| Entrega | Contrato OpenAPI v1, tipos TypeScript generados, CI de Python, PostgreSQL, accesibilidad y paridad web/CLI. |

## Backlog verificado

| Tareas | Estado | Alcance |
|---|---|---|
| TASK-001–013 | Implementadas | Núcleo offline, empaquetado, PostgreSQL, aislamiento, autenticación e inventario con autorizaciones. |
| TASK-014 | Parcial | Evaluaciones, planes, idempotencia y evento con outbox de revisión. |
| TASK-015–020 | Implementadas en el piloto | Importación legada, contrato, web, altas, Compose y cliente CLI. El modo OIDC de CLI consume un access token emitido por el proveedor. |
| TASK-021–024 | Pendientes | Infraestructura y control operativo previstos en el roadmap. |
| TASK-025 | Parcial | Recorrido de simulación, descarga y exportación de informes HTML deterministas. |
| TASK-026–040 | Pendientes | Capacidades, custodia, integraciones y validación empresarial del roadmap. |
| TASK-041 | Parcial | Copia y ensayo de recuperación de PostgreSQL y de la clave de documentos en un piloto aislado. |
| TASK-042–043 | Pendientes | Integraciones de terceros y certificación del piloto multiempresa. |
| TASK-044 | Parcial | Guías operativas y de desarrollo del piloto actual. |
| TASK-045–046 | Pendientes | Validación de producción y entrega versionada. |

La prueba del piloto verifica que un plan creado por CLI abre en la web y conserva el hash y los bytes del informe después de reiniciar. Consulta las ejecuciones por commit en [GitHub Actions](https://github.com/Blandskron/KronShield/actions).

- [Inicio y comandos](../README.md)
- [Desarrollo y validación](DEVELOPMENT.md)
- [Operación y recuperación](OPERATIONS.md)
- [Backlog detallado](planning/TASK_BACKLOG.md)
