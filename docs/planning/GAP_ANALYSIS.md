# Brechas y orden de cierre

| Área | Situación de la línea base | Estado que debe demostrarse | Tareas y primera versión |
|---|---|---|---|
| Alcance | URL superficial y aceptación de redes privadas por defecto | Decisión denegatoria, reglas versionadas, ventana, exclusiones, DNS/IP fijada y transporte controlado | TASK-002–006 · v0.2.0 |
| Caja de herramientas | GET, TCP, XSS y SQLi heurísticos | Catálogo con contrato, permisos, presupuesto y evidencia | TASK-006, TASK-021–025, TASK-029–034 · v0.5.0/v0.7.0 |
| Identidad y datos | CLI local, SQLite y JSON por dominio | Login, roles, membresías, RLS, migraciones y conservación de legados | TASK-011–015 · v0.3.0 |
| Instalación | Instalación Python dependiente del CWD | Compose reproducible desde clone, bootstrap seguro, health checks, stack local y laboratorio | TASK-019, TASK-025, TASK-041 · v0.4.0/v0.5.0/v0.9.0 |
| Interfaz | CLI de auditoría y reporte | Panel responsive, inventario, autorización y consola tipada sobre API compartida | TASK-017–020, TASK-024 · v0.4.0/v0.5.0 |
| Operación | Un proceso serial y sin cancelación | Cola durable, aislamiento, cuotas y revocación verificable | TASK-021–025 · v0.5.0 |
| IA | Groq global, texto a payload y resumen libre | Salidas estructuradas, presupuesto, redacción, trazabilidad y revisión | TASK-026–028 · v0.6.0 |
| Evidencia e informes | Hallazgos sin cadena de custodia, HTML con campo sin escapar | Evidencia cifrada y verificable, estados revisables, informe versionado y riesgo trazable | TASK-007, TASK-035–038 · v0.8.0 |
| Empresa | Sin SSO, respaldo automatizado ni observabilidad | Integración OIDC corporativa, restauración ensayada, SLO y gates de release | TASK-039–046 · v0.9.0/v1.0.0 |

## Decisiones de alcance

- Conservar las firmas conceptuales de `Finding`, `audit run` y `report generate` cuando el contrato pueda preservar la seguridad. Los nombres de comandos se mantienen como alias en la transición. La URL arbitraria y las claves en argumentos se retiran con un mensaje de migración.
- El primer recorrido integrado usa un laboratorio incluido y verificaciones HTTP de bajo impacto. DNS, TLS, TCP, análisis de artefactos y reportes crecen por perfiles. La equivalencia web/CLI se mide por permisos, parámetros y estados del mismo caso de uso.
- Empresas con redes internas despliegan runners dedicados en un segmento acordado. La evaluación de identidad, lógica de negocio y explotación queda supervisada. La cobertura de una categoría se publica por técnica, con limitaciones y fixture.
- La licencia MIT cubre el repositorio propio. Motores, imágenes, firmas, plantillas, reglas y feeds mantienen sus términos y versiones.
