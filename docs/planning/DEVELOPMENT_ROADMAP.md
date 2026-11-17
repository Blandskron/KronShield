# Roadmap por versiones

El número de versión indica una puerta de validación. La primera versión funcional de extremo a extremo es **v0.5.0 de laboratorio**. Con un clon y Docker Compose, un operador puede iniciar sesión, sembrar el laboratorio, autorizar el objetivo, validar el plan, iniciar desde web o CLI, seguir SSE, cancelar y descargar un informe HTML determinista. Hasta v1.0.0 los jobs activos solo usan fixtures y redes de laboratorio. En v1.0.0 el perfil autorizado R1 requiere puesta en servicio por instalación y evidencia de que el runner, egress y el control operativo cumplen las reglas. R2 se entrega para laboratorio con aprobación, mientras R3 permanece restringido a validación supervisada de laboratorio en esta versión.

| Versión | Tareas | Entrega y condición de salida |
|---|---|---|
| v0.2.0 | TASK-001–010 | Configuración tipada, transporte controlado, hallazgos calibrados, informes seguros y núcleo en pruebas. Entradas antiguas activas bloqueadas. |
| v0.3.0 | TASK-011–016 | API autenticada, modelo de organización/proyecto, migración, RLS, registro verificable y plan dry-run. Ensayo con dos tenants. |
| v0.4.0 | TASK-017–020 | UI navegable, Compose base, identidad local y CLI cliente. Clon→login→alta→validación de plan con revisión visible. |
| v0.5.0 | TASK-021–025 | Worker, egress, cancelación, bitácora inicial y laboratorio integral con informe determinista. Flujo web/CLI probado. |
| v0.6.0 | TASK-026–028 | Analistas con contratos tipados, cuotas y herramientas de lectura. Revisiones humanas y pruebas de inyección. |
| v0.7.0 | TASK-029–034 | Recon/TLS/red, web/API, artefactos/cloud e identidad. R2/R3 supervisado según catálogo lab. |
| v0.8.0 | TASK-035–038 | Cadena de custodia con anclaje, hallazgos, CVE/CWE/CVSS, informes de auditoría revisados y comparación. |
| v0.9.0 | TASK-039–042 | SSO empresarial, quality gates, observabilidad, recuperación, adaptadores de terceros bajo perfiles. |
| v1.0.0 | TASK-043–046 | Piloto multiempresa, carga, documentación ensayada y distribución firmada. R1 aprobado por instalación. |

## Dependencias, costos y supuestos

| Dependencia | Necesidad y costo a validar |
|---|---|
| Docker Desktop/Engine + Compose v2 | Linux y Windows con backend Linux como objetivos de piloto, ARM sujeto a imágenes comprobadas. Registrar mínimos reproducibles al pasar CI. Revisar condiciones del runtime elegido. |
| PostgreSQL, Redis y almacenamiento S3 compatible | CPU, RAM, disco, IO, backups, objetos, réplicas si hay SLO y mantenimiento. Validar versión/licencia de cada imagen y alternativa compatible antes de congelar el lock de infraestructura. |
| OIDC y KMS/secret store | IdP en producción, MFA y ciclo de baja. Costo por usuarios/operaciones y rotación. Proveedor de prueba o bootstrap para piloto. |
| Egress y runners | Host/red dedicada por entorno, capacidad cgroup, segmentación, operación, logs y pruebas de cierre. El presupuesto de tráfico remota depende de autorización. |
| Herramientas/reglas/feeds | Imágenes, actualizaciones, SBOM y revisión de licencias. Escáneres grandes pueden exigir servicios dedicados, almacenamiento de feed y horas operativas. |
| IA local/remota | Tokens, límites API/región y retención del proveedor externo, o CPU/GPU y operación local. Uso mensual estimado = tokens de entrada y salida por modelo × tarifa vigente + infraestructura. IA opcional. |
| Personal y QA | Revisión de permisos/requisitos, verificación de evidencia, mantenimiento de adaptadores/fixtures, atención de alertas y pruebas de restauración. R2/R3 necesita especialista y tiempo de supervisión. |

Metas iniciales propuestas para el piloto: disponibilidad de API leída 99,5% mensual, restauración RPO 24 h / RTO 4 h, p95 de GET y creación de plan de laboratorio <500 ms excluyendo acciones de red, primer evento del job en <5 s cuando hay capacidad, 0 pérdida de eventos confirmados tras reconexión y cancelación lab <2 s desde revocación confirmada. Validar en TASK-041/045 con topología y carga documentadas. Estimar costos con inventario de recursos y tarifas vigentes en instalación. No se ha fijado presupuesto, región ni proveedor comercial.
