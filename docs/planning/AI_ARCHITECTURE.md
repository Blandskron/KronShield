# Arquitectura del motor de IA

## Separación de autoridad

Un servicio de análisis recibe una solicitud autenticada sobre proyecto, evaluación y evidencia. Construye una vista redactada de tamaño acotado. Políticas de clasificación deterministas gobiernan qué información sale a un proveedor externo. Organización elige proveedor y modelo en allowlist, con modo local disponible. Por defecto IA apagada y ejecución determinista disponible. Para proveedor remoto se requiere habilitación de organización, verificación de términos de tratamiento/retención y selección explícita de campos. La respuesta es borrador con referencias. Una revisión humana aprueba su publicación. El LLM no posee credenciales, llamada a shell, acceso a red, cuotas de runner, control de estado ni permiso para aprobar.

| Agente | Entradas y herramientas de solo lectura | Salida y revisión |
|---|---|---|
| Reconnaissance Analyst | `list_assets`, `get_observations` de inventario y TLS | Tecnologías candidatas y exposición observada. Operador revisa identidades. |
| Network Security Analyst | `get_observations` TCP/UDP, evidencia de configuración | Servicios y segmentación documentada. Revisor valida alcance/certeza. |
| Web Application Security Analyst | `list_findings`, `get_evidence_excerpt` de respuestas redactadas | Hipótesis WSTG/CWE y parámetros referenciados. Revisor distingue detección y validación. |
| API Security Analyst | Inventario OpenAPI y fixtures, `list_findings` | Candidatos de auth, esquema y límites. Especialista verifica pares de identidades. |
| Identity Security Analyst | Resultados redactados de políticas y simulación sintética | Riesgo de control y brechas de detección. Nunca recibe contraseñas o tickets. |
| Cloud Security Analyst | Snapshot autorizado y minimizado, `get_observations` | Recursos y controles CIS candidatos. Analista valida contexto. |
| Vulnerability Correlation Analyst | `lookup_catalog` desde caché, evidencia de versión | Candidatos CVE/CWE con regla, rango y fuente. Confirmación sobre inventario. |
| Risk Assessment Agent | Hallazgos revisados, scoring validado y criticidad declarada | Motivo contextual y controles compensatorios. Revisor aprueba puntuación. |
| Remediation Advisor | Hallazgos confirmados, guías permitidas | Pasos de mitigación y criterios de re-test. Propietario revisa impacto. |
| Executive Report Agent | Impacto aprobado, métricas y hallazgos revisados | Borrador técnico/ejecutivo por audiencia. Publicación por aprobador. |

## Contratos y flujo

`AnalysisRequest(org_id, project_id, assessment_id, agent_id, evidence_ids, policy_version)` se crea en servidor con identidad efectiva. Cada herramienta declara schema Pydantic, handler de lectura, límites de paginación y clasificación. Un gateway valida cada tool call, permiso, proyecto y campos, aplica el presupuesto y produce un evento; referencias ajenas o tools desconocidas se rechazan. Mantener un grafo fijo de tareas: contexto → candidatos → reconciliación determinista → revisión → borrador. Analistas intercambian solo objetos validados. Un agente puede sugerir ID de técnica para un plan futuro y su justificación, que el operador revisa y crea mediante la API. La salida de análisis no ingresa a una cola de escaneo.

`AnalysisResult(schema_version, agent_id, claims[], limitations[], usage)`, con cada `Claim(kind, summary, evidence_refs[], confidence, candidate_ids[])`. Validar refs contra contexto entregado, enum, intervalos, tamaño, e IDs CWE/CVE con snapshot del catálogo. Si falla: un intento de reparación estructurada dentro de presupuesto o estado `failed_validation`. Confianza baja/media/alta se calibra con fixtures y reglas de corroboración; confirmación exige evidencia técnica/revisor. La salida se renderiza como texto y se escapa en reportes.

Separar instrucciones de sistema y datos. Sanitizar controles y limitar campos, fragmentos y contenido de documentos. Nunca colocar secretos, cabeceras completas, URLs con query o datos de cuentas. Tratar instrucciones en evidencia como datos sin autoridad. Citar IDs recuperables por revisión. Las herramientas nunca evalúan texto como expresiones ni aceptan endpoint del modelo. Las pruebas usan evidencia con órdenes inyectadas, enlaces/IDs ajenos, salida gigante y secretos sintéticos. Todo intento de ampliar privilegios falla y queda contabilizado.

Interfaz de proveedor: `invoke(messages, json_schema, budget, deadline) -> result,usage`. Adaptar Groq, endpoint local administrado y segundo proveedor compatible tras prueba de contrato. Elegir proveedor/modelo desde registro del servidor, autenticar con secreto referenciado y permitir salida solo a destinos fijos. Por defecto máximo 6 llamadas, 12 000 tokens de entrada, 3 000 de salida total y 120 s por análisis como valores iniciales configurables. Contabilizar tokens reales por modelo, tarifa/versionado y límite monetario por org, reservar presupuesto antes de invocar y reconciliar uso tras respuesta; si se desconoce el uso, cargar la reserva provisional. Registrar IDs, modelo, versión de schema/prompt, uso, costo, latencia y resultado sin prompt crudo por defecto. Local requiere capacidad y aislamiento GPU/CPU. Tarifas por proveedor se consultan al activar y se guardan con vigencia. [Modelos y costos de Groq](https://console.groq.com/docs/models).
