# Capacidades y trazabilidad metodológica

Referencias verificadas al 17 de noviembre de 2026. La implementación guarda por verificación el ID exacto de prueba/requisito y la versión, además de versión de regla, adaptador y fuente. Una matriz de cobertura versionada indica aplicado, excluido o inconcluso por objetivo.

| Referencia vigente observada | Cobertura en la línea base | Uso propuesto |
|---|---|---|
| PTES, siete fases. La copia experimental se etiqueta 1.1. No se confirmó una edición formal posterior en el portal original. [Repositorio PTES](https://github.com/pentest-standard/docs/blob/master/source/Main_Page) · [Copia experimental](https://pentest-standard.readthedocs.io/en/latest/tree.html) | Reconocimiento, sondeo y reporte parcial | Preacuerdo, ejecución y reporte diferenciados. REC/NET/EXP. |
| OWASP WSTG 4.2, 5.0 en desarrollo. [Publicaciones](https://owasp.org/projects/web-security-testing-guide) | Cabeceras, XSS y SQLi parciales | Casos WEB y fixtures negativos versionados. |
| OWASP ASVS 5.0.0 estable. [Releases](https://github.com/OWASP/ASVS/releases) | Sin requisitos mapeados | Criterios de verificación para plataforma, WEB e IDN. |
| OWASP API Security Top 10 2023. [Edición 2023](https://api-security.owasp.org/editions/2023/en/0x11-t10/) | Sin evaluación API | Clasificar API y priorizar acceso a objetos y consumo. |
| OWASP Top 10 2025. [Edición 2025](https://top10.owasp.org/) | Pruebas aisladas de inyección y configuración | Taxonomía Web, no equivale a cobertura de pruebas. |
| NIST SP 800-115 final (2008). [NIST](https://csrc.nist.gov/pubs/sp/800/115/final) | Sondeo e informe parcial | Plan, ejecución y cierre con reglas de compromiso. |
| MITRE ATT&CK 20.1. [Changelog](https://attack.mitre.org/resources/changelog.html) | Sin técnicas mapeadas | IDN/AD/EXP y correlación con señales defensivas. |
| MITRE CWE 5.0, esquema 8.0. [Catálogo CWE](https://cwe.mitre.org/data/) | Sin clasificación CWE | Mapear debilidad de causa raíz en WEB/API/SRC. |
| CVE catálogo continuo y NVD API 2.0. [CVE](https://www.cve.org/) · [API NVD](https://nvd.nist.gov/developers/vulnerabilities) | Sin correlación | Instantánea reproducible por fuente y fecha, enriquecer versión y condiciones. |
| CVSS v4.0. [FIRST](https://www.first.org/cvss/v4.0/specification-document) | Gravedad narrativa del LLM | Vector, fuente y versión verificados. Riesgo organizacional se justifica de manera independiente. |
| CIS Benchmarks por producto/edición. [Catálogo CIS](https://www.cisecurity.org/cis-benchmarks) | Sin controles asociados | Fijar benchmark a plataforma, versión e identificador exactos en CLD/NET/AD. |
| OSSTMM 3 público, 4 en acceso temprano. [ISECOM](https://isecom.org/osstmm.html) | Sin medición estructurada | Matriz de canales, observables y segmentación con evidencia controlada. |
| OWASP MASVS 2.1.0 y MASTG 2.0.0. [MASVS](https://github.com/OWASP/masvs/releases) · [MASTG](https://github.com/OWASP/mastg/releases) | Sin cobertura móvil | Importar pruebas manuales y mapearlas a requisitos. |

## Niveles de verificación

**Reconocimiento** inventaría; el contacto con objetivos requiere autorización R1. **Evaluación** observa o compara con reglas y puede producir sospechas. **Validación controlada** reproduce efecto observable en entorno acordado y controla impacto, con revisión independiente. **Simulación adversaria** comprueba controles y detección con un escenario aprobado y especialista responsable. Un hallazgo progresa `observed → suspected → validated → confirmed` con evidencia y decisiones verificables. Puede cerrarse `false_positive|accepted_risk` con motivo. Sistemas de producción de impacto potencial quedan sujetos a aprobación específica y ensayos previos en laboratorio.

A0 exige permiso de proyecto y procedencia. A1 exige autorización vigente de activo, ventana, técnica y límites. A2 añade aprobación independiente del plan. A3 añade aprobación por ejecución, especialista, evidencia y rollback. A = automatizable, S = semiautomático con revisión, M = supervisión manual. Rige el presupuesto más restrictivo entre plataforma, autorización y técnica. Los criterios siguientes se verifican con fixtures o documentos de laboratorio.

| ID | Categoría | Verificación | Referencia | Riesgo | Autorización | Autom. | Evidencia | Aceptación | Tarea |
|---|---|---|---|---|---|---|---|---|---|
| REC-01 | Reconocimiento | Inventario de activos y superficie | PTES/NIST | R0 | A0 | A | Registro de propiedad y exposición | Duplicado se consolida sin cruzar proyectos | TASK-013 |
| REC-02 | Reconocimiento | Host y servicio HTTP con fingerprint acotado | WSTG-INFO | R1 | A1 | A | Estado, cabeceras permitidas, fecha | Detecta servidor de fixture y oculta secretos | TASK-025 |
| REC-03 | Reconocimiento | DNS y enumeración acotada de subdominios | PTES | R1 | A1 | S | RR, CNAME, TTL y decisión | No consulta candidato fuera del dominio delegado | TASK-029 |
| REC-04 | Reconocimiento | TLS y SSL, certificados, protocolos y cifrados | WSTG-CRYP | R1 | A1 | A | Cadena, SNI, versión y cifrado | Fixture expirado distingue hostname y vigencia | TASK-029 |
| REC-05 | Reconocimiento | Configuraciones HTTP y cabeceras | WSTG-CONF | R1 | A1 | A | Cabeceras, contexto y regla | HSTS se evalúa según contexto HTTPS | TASK-025 |
| REC-06 | Reconocimiento | Versión, componentes y dependencias visibles | CVE/NVD | R1 | A1 | S | Fingerprint y fuente | Versión inferida queda como candidata | TASK-029 |
| NET-01 | Red | Descubrimiento TCP y UDP permitido | NIST/PTES | R1 | A1 | S | Puerto, protocolo y respuesta | Distingue UDP inconcluso de cerrado | TASK-030 |
| NET-02 | Red | Servicios expuestos y protocolos inseguros | PTES/CIS | R1 | A1 | A | Banner redactado y regla | Servicio desconocido permanece sin identificar | TASK-030 |
| NET-03 | Red | SSH, DNS y SMB | CIS/NIST | R2 | A2 | S | Parámetro, versión y configuración | Revisa fixtures sin autenticación real | TASK-030 |
| NET-04 | Red | Segmentación, ACL y firewall | OSSTMM/NIST | R2 | A2 | S | Matriz origen-destino y reglas | Compara permiso y denegación desde runner asignado | TASK-030 |
| NET-05 | Red | Criptografía y CVE de servicios | CIS/CVE | R1 | A1 | S | Huella, versión, regla y fuente | No confirma CVE a partir de banner ambiguo | TASK-037 |
| WEB-01 | Web | SQLi con controles diferenciales | WSTG-INPV | R2 | A2 | S | Baseline, variación y mensaje redactado | Texto SQL genérico queda sin confirmar | TASK-032 |
| WEB-02 | Web | XSS reflejado y DOM | WSTG-INPV/CLNT | R2 | A2 | S | Marcador, contexto, resultado del navegador | Reflexión escapada no confirma ejecución | TASK-032 |
| WEB-03 | Web | CSRF | WSTG-SESS | R2 | A2 | S | Atributos, token, origen y efecto sintético | Solicitud positiva y negativa sobre operación reversible | TASK-032 |
| WEB-04 | Web | SSRF | WSTG-INPV | R2 | A2 | S | Señal de canario propio | Fixture distingue resolución de acceso; metadata bloqueada | TASK-032 |
| WEB-05 | Web | IDOR y control de acceso | WSTG-ATHZ | R2 | A2 | S | Par de roles e IDs sintéticos | Usuario ajeno no puede leer ni mutar fixture | TASK-032 |
| WEB-06 | Web | Path traversal y file inclusion | WSTG-ATHZ/INPV | R2 | A2 | S | Acceso a archivo canario | Confirmación solo con dato sintético de referencia | TASK-032 |
| WEB-07 | Web | Carga de archivos insegura | WSTG-BUSL | R2 | A2 | S | MIME, validación y evento de limpieza | Fixture inerte, cuenta y almacenamiento dedicados | TASK-032 |
| WEB-08 | Web | Open redirect | WSTG-CLNT | R2 | A2 | A | Location y origen | Captura Location sin visitar origen externo | TASK-032 |
| WEB-09 | Web | Configuración y exposición sensible | WSTG-CONF/INFO | R1 | A1 | S | Tipo de secreto/archivo y fragmento redactado | El valor original queda fuera de reporte y eventos | TASK-025 |
| WEB-10 | Web | Autenticación y sesiones | WSTG-ATHN/SESS | R2 | A2 | S | Rotación, expiración y cookies redactadas | Sesión de fixture expira y no se reusa tras logout | TASK-032 |
| WEB-11 | Web | Deserialización y command injection | ASVS/WSTG-INPV | R3 | A3 | M | Efecto sintético bajo supervisión | Validar contra canario en sandbox sin acceso a host | TASK-034 |
| WEB-12 | Web | XXE | WSTG-INPV | R2 | A2 | S | Evidencia de parser sobre fixture | Entidades externas a canario propio exclusivamente | TASK-032 |
| WEB-13 | Web | Dependencias vulnerables | OWASP Top 10/CVE | R0 | A0 | S | SBOM, versión y regla de correlación | Diferenciar paquete detectado y uso verificable | TASK-037 |
| WEB-14 | Web | Lógica de negocio | WSTG-BUSL | R3 | A3 | M | Flujo e invariante con objetos sintéticos | Revisor reproduce sin usar operaciones irreversibles | TASK-034 |
| WEB-15 | Web | CORS y políticas del navegador | WSTG-CLNT/ASVS | R2 | A2 | S | Origin, ACAO y credenciales | Distingue reflejo de acceso cross-origin efectivo | TASK-032 |
| API-01 | API | REST y OpenAPI, esquema e inventario | API9/ASVS | R1 | A1 | A | Operaciones, esquema, versión y diferencias | Documento remoto referenciado requiere alcance propio | TASK-032 |
| API-02 | API | GraphQL y WebSocket | API4/API9 | R2 | A2 | S | Operación o suscripción, límite y autent. | No expande recursión ni suscripciones fuera de presupuesto | TASK-032 |
| API-03 | API | OAuth 2.0, OIDC y JWT | API2/ASVS | R2 | A2 | S | Flujo, issuer, aud y resultado sin tokens | Rechaza JWT expirado, aud incorrecta y firma inválida en fixture | TASK-032 |
| API-04 | API | Autorización por objeto, propiedad y función | API1/API3/API5 | R2 | A2 | S | Identidades y matriz de acceso | Medir casos propios/ajenos con cuentas de prueba | TASK-032 |
| API-05 | API | Exposición de datos y CORS | API3/API8 | R2 | A2 | S | Campos permitidos y origen | Comparar allowlist de esquema por rol | TASK-032 |
| API-06 | API | Rate limit y gestión de sesiones/tokens | API2/API4 | R2 | A2 | S | 429, TTL, revocación y contador | Presupuesto queda duro aun si el endpoint no limita | TASK-033 |
| IDN-01 | Identidad | Políticas de contraseñas, MFA y recuperación | ASVS/WSTG-ATHN | R2 | A2 | S | Configuración y resultado redactado | Solo cuentas de prueba, recuperación reversible | TASK-033 |
| IDN-02 | Identidad | Bloqueo, enumeración y repetición | WSTG-ATHN | R2 | A2 | S | Códigos, latencia y evento de bloqueo | Detener tras respuesta de bloqueo, sin ampliar ventana | TASK-033 |
| IDN-03 | Identidad | Escenarios de password spraying y credential stuffing | ATT&CK T1110 | R3 | A3 | M | Contadores, alerta y correlación de cuenta sintética | Presupuestos por cuenta/escenario y paro verificable | TASK-034 |
| IDN-04 | Identidad | Sesiones y detección de fallos | ASVS/ATT&CK | R2 | A2 | S | Eventos de intentos y alerta esperada | Correlacionar job/alerta con reloj consensuado | TASK-033 |
| CLD-01 | Cloud | AWS, Azure y GCP de solo lectura | CIS | R1 | A1 | S | Snapshot, cuenta y control versionado | Credenciales mínimas y llamadas de mutación denegadas | TASK-031 |
| CLD-02 | Cloud | Kubernetes y Docker | CIS | R1 | A1 | S | RBAC, manifiesto, exposición y control | Validar en clúster lab con permisos de lectura | TASK-031 |
| CLD-03 | Cloud | Terraform, IaC y CI/CD | CIS/NIST | R0 | A0 | A | Archivo, línea, regla y digest | Analiza archivo sin plan aplicado ni hooks | TASK-031 |
| CLD-04 | Cloud | IAM, secretos, almacenamiento y red | CIS | R1 | A1 | S | Política normalizada y hallazgo contextual | Reportar exposición verificada sin leer valores | TASK-031 |
| SRC-01 | Código | SAST y config | CWE/ASVS | R0 | A0 | A | Regla, ubicación, commit y confianza | Golden de positivos y negativos | TASK-031 |
| SRC-02 | Código | DAST controlado | WSTG | R2 | A2 | S | Solicitud y respuesta redactadas | Traza y whitelist, sin omitir política | TASK-032 |
| SRC-03 | Código | SCA, SBOM y dependencias | CVE/NVD | R0 | A0 | A | Identidad componente, versión y digest | SBOM validado y base con fecha | TASK-031 |
| SRC-04 | Código | Escaneo de secretos | CWE | R0 | A0 | A | Ubicación, commit y huella redactada | Canario detectado sin imprimir valor | TASK-031 |
| SRC-05 | Código | Análisis de imágenes | CIS/CVE | R0 | A0 | A | Digest, paquetes y hallazgos | Imagen no se ejecuta para inspección | TASK-031 |
| SRC-06 | Código | Exposición real y correlación | CVE/CWE/CVSS | R0 | A0 | S | Componente, condición y justificación | Versión sola no fija explotabilidad | TASK-037 |
| AD-01 | AD | Políticas, contraseñas y privilegios | CIS/ATT&CK | R1 | A1 | S | Snapshot y cuentas de servicio redactadas | Sin recuperar hashes ni secretos; permisos de lectura | TASK-033 |
| AD-02 | AD | LDAP/Kerberos, delegación, segmentación | CIS/ATT&CK | R2 | A2 | S | Configuración y grafo de permisos | Distingue riesgo de delegación y acceso certificado | TASK-033 |
| EXP-01 | Validación | Demostración acotada y simulación adversaria | PTES/ATT&CK | R3 | A3 | M | Aprobación, efecto de canario, limpieza y cierre | Un efecto autorizado se reproduce en lab con kill switch | TASK-034 |
| MOB-01 | Móvil | Almacenamiento, plataforma, red, auth y privacidad | MASVS/MASTG | R2 | A2 | M | ID MASVS/MASTG, versión, build y prueba | Especialista registra pruebas Android/iOS en dispositivos lab | TASK-034 |

## Evaluación de herramientas

La selección se congela por versión, licencia de código y datos, digest, procedencia y compatibilidad con Linux amd64/arm64. CI prueba formatos, salida, duración, denegación de salida y fijación de feeds. Las referencias son proyectos mantenedores. Revalidar actividad, imágenes, licencia concreta y avisos antes de fijar la release. Si un motor ignora el control de destino, queda bloqueado hasta contar con aislamiento y pruebas de red equivalentes.

| Adaptador y pertinencia | Contrato y limitación operacional | Distribución y mantenimiento |
|---|---|---|
| Nmap para NET | TCP connect con puertos acotados y XML. UDP/raw en runner dedicado tras evaluación. Fijar IP de destino. | NPSL, distribución condicionada. Opción instalada por operador hasta revisar redistribución. [Nmap](https://nmap.org/npsl/) |
| ZAP para WEB/API | Baseline con spider delimitado y alcance aplicado a cada solicitud. JSON. DAST activo solo con perfil R2. | Apache-2.0 para núcleo. Revisar add-ons y digests. [Licencia](https://github.com/zaproxy/zaproxy/blob/main/LICENSE) · [Docker](https://www.zaproxy.org/docs/docker/about/) |
| Nuclei para exposición y CVE | JSONL, plantillas firmadas/curadas por digest; bloquear code, headless e interacciones externas en perfil inicial. | MIT motor y plantillas oficiales con licencia propia. Revisar reglas de terceros. [Motor](https://github.com/projectdiscovery/nuclei) · [Plantillas](https://github.com/projectdiscovery/nuclei-templates/blob/main/LICENSE.md) |
| testssl.sh para TLS | JSON, TLS al destino/sujeto permitido, sin consultas externas de revocación por defecto. | GPL-2.0 según repositorio. Mantener cumplimiento de redistribución y dependencias. [testssl.sh](https://github.com/testssl/testssl.sh) |
| Trivy para imágenes, SCA y SBOM | Analizar digest o artefacto local, fijar base y edad máxima, sin ejecutar imagen. JSON/CycloneDX. | Apache-2.0 motor; revisar base y fuentes por separado. [Trivy](https://github.com/aquasecurity/trivy/blob/main/LICENSE) |
| Semgrep CE para SAST | JSON/SARIF, reglas propias o curadas. Bloquear red y extensiones no aprobadas. | LGPL-2.1 motor, reglas Semgrep bajo términos separados. [Motor y reglas](https://semgrep.dev/blog/2024/important-updates-to-semgrep-oss) |
| Gitleaks para secretos | JSON redactado, repo de laboratorio y sin hooks. | MIT. Mantener versión y configuración equivalente en CI. [Gitleaks](https://github.com/gitleaks/gitleaks/blob/master/LICENSE) |
| Greenbone/OpenVAS para infraestructura | Integración opcional con servicio dedicado y controles de targets/feed. Consumir resultado normalizado. | Licencias por componente y feed. Costos de sync, CPU, RAM y gestión. [Greenbone](https://greenbone.github.io/docs/latest/index.html) |
| Prowler para cloud | JSON normalizado desde rol de auditoría temporario, cuenta y regiones autorizadas. | Apache-2.0 en repositorio OSS. Uso de APIs cloud y servicios comerciales separados. [Prowler](https://github.com/prowler-cloud/prowler) |
| Checkov para IaC | JSON/SARIF local. Sin descarga de módulos por defecto, fixtures offline. | Apache-2.0 motor; revisar reglas y dependencias. [Checkov](https://github.com/bridgecrewio/checkov/blob/main/LICENSE) |

El manifiesto del adaptador contiene `tool_id, version, image_digest, license, schema_hash, capabilities, risk, requirements, allowed_egress, parser_version`. El registro define argumentos a partir de tipos cerrados y limita tamaño/error de parser. Cada ejecución produce observaciones normalizadas, estadísticas, evidencia y estado. No se instala un scanner de terceros en la imagen base por defecto.
