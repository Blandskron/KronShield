# Orden de implementación y puertas

Las dependencias del [backlog](TASK_BACKLOG.md) determinan el orden válido. Los números son IDs, no fechas. Para visualizar la ruta crítica de planificación, pesos relativos S=1, M=2, L=3, XL=5 y capacidad ideal para ramas paralelas. Los puntos comparan rutas; el calendario depende de recursos, revisiones y laboratorio.

- Hasta el primer recorrido funcional, TASK-002 → 005 → 010 → 011 → 012 → 013 → 014 → 016 → 017 → 019 → 021 → 022 → 023 → 024 → 025.
- Hasta v1.0.0, TASK-002 → 005 → 010 → 011 → 012 → 013 → 014 → 016 → 017 → 019 → 021 → 022 → 023 → 024 → 025 → 035 → 036 → 037 → 038 → 043 → 045 → 046.
- Ramas que convergen en piloto: datos aislados y autorizaciones, egress/cancelación, informes/evidencia, SSO, herramientas/identidad y observabilidad. Los pesos pueden cambiar la rama crítica al asignar especialistas. Las dependencias no cambian.

| Fase | Paralelización posible | Definición de terminado y bloqueos |
|---|---|---|
| Núcleo | Fixtures y renderer en paralelo al dominio y transporte. Empaquetado después de fijar config. | Casos SSRF, redirects, inyección, presupuesto y entradas legadas cerrados. TASK-006 bloquea todas las entradas de red activas. |
| Datos/API | Diseño de persistencia y cliente de identidad se preparan en paralelo; merges siguen 011→012→013/014. | Migrar en DB nueva, matriz tenant+proyecto y contratos OpenAPI. Contexto de identidad requerido antes de montar rutas. |
| Frontend/Compose | Permisos y layout primero; catálogo y UI de planificación junto a Docker. | Clon limpio con login y alta. Portales y CLI comparten modelo. API y UI no permiten jobs activos hasta la puerta siguiente. |
| Ejecución | SSE, pruebas de egress y laboratorio se preparan juntos. Integración 021→022→023→024→025. | Confirmar RLS en ejecución, bitácora persistida con actor/revisión/técnica/objetivo/resultado, acceso restringido y objetos cifrados, deny/redirección, cancelación y kill switch. En v0.5.0 solo red de laboratorio. |
| IA | Proveedores y catálogos de permisos se preparan con datos sintéticos. | Pruebas de tool calling, referencias, presupuesto, inyección, salida externa y revisión. Los datos nuevos de v0.7 se conectan mediante contratos certificados. |
| Capacidades | Recon/red, artefactos/cloud y perfiles WSTG/identidad pueden avanzar en ramas tras el aislamiento. | Evidencia por fila de matriz, licencia y versión, fixture positivo/negativo, salida comprobada. R3 solo fixture sintetizado y especialista. |
| Evidencia | Custodia puede comenzar tras v0.5 en paralelo a adaptadores. Correlación y riesgos requieren hallazgos revisados y fuente. | Evidencia cifrada, retención, anclaje externo, revisión, informe y comparación reproducibles. |
| Empresa | SSO, CI y logs/backup avanzan en paralelo con dependencias satisfechas. | Restore, revocación, métricas, licencias de proveedores y smoke en Windows/Linux. Acceso a redes de cliente aún cerrado. |
| Estable | Piloto y revisión con guía de instalación ya verificable. | SLO medidos, publicación firmada, P0/P1 resueltos y permiso explícito para R1 de instalación. Multitenancy, egress y retención validados en la topología real. |

## Primeras diez tareas

- **TASK-001** · Fijar línea base y convertir tests en herméticos.
- **TASK-002** · Modelar autorización y decisión de política.
- **TASK-003** · Canonicalizar destinos y resolver DNS seguro.
- **TASK-004** · Construir transporte HTTP/TCP fijado a IP.
- **TASK-005** · Imponer presupuesto y esquema de configuración.
- **TASK-006** · Eliminar el camino activo legado sin política.
- **TASK-007** · Cerrar inyección HTML y rutas derivadas de URL.
- **TASK-008** · Calibrar clasificación de XSS y SQLi.
- **TASK-009** · Preservar resultados offline con transacciones.
- **TASK-010** · Empaquetar núcleo y fijar dependencias.

## Estrategia de calidad

| Nivel | Suite y gates |
|---|---|
| Unit | Pytest/Vitest para reglas, hashing, límites, clasificación, config y estados. Usar relojes inyectados y bloqueo de red por fixture. |
| Integración | PostgreSQL real, Redis, egress y runner en red aislada. RLS por rol/membresía, up/down, redelivery, cuotas, cancelación, bloqueo de metadatos y aplicaciones DNS/redirect hostiles. |
| Contrato | OpenAPI/generación TS, versiones de payload SSE y manifests. CLI y web sobre misma API con contraejemplos. Validar parsing de salidas de cada herramienta por digest. |
| E2E | Playwright y CLI desde clon. Windows Docker Desktop/Linux. Dos tenants, autorización, planes R1/R2, reanudación del stream, kill y reportes. Accesibilidad WCAG 2.2 AA y teclado. |
| Precisión | Fixtures web/API positivos y negativos, codificación y controles diferenciales. Medir falsos positivos por técnica y tratar timeouts como inconclusos. |
| Seguridad | Probar manipulación de HTML, credenciales en logs, salida de runner, vulnerabilidades de supply chain, revocación y reconstrucción de evidencia. No usar objetivos públicos. |
| IA | Prompts indirectos, tool calls no permitidos, referencias falsas, tokens, redacción y cita de evidencia. PR con proveedor simulado y suite controlada para modelos habilitados. |
| Release | Compilación reproducible, pruebas, lint y tipos, contract diff, análisis de dependencias, SAST/SCA/secret scan, SBOM, artefactos firmados, rollback y restauración. |

La evidenciación de gates conserva en CI hashes de artefactos, resultados por perfil, exenciones con responsable y caducidad y enlace a regresión. Cualquier fallo de laboratorio se reproduce con el mismo digest y dataset.
