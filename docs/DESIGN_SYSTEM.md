# Sistema de diseño de KronShield

## Arquitectura y superficies

| Capa | Responsabilidad |
|---|---|
| [Tokens](../frontend/src/tokens.css) | Identidad cromática, temas, contraste, tipografías locales, escala y duración. |
| [Estilos](../frontend/src/styles.css) | Shell, entrada pública, paneles, tablas, estados y formularios. Superficies opacas para datos y formularios. Translucidez moderada en la barra superior. |
| [Marca y tema](../frontend/src/brand.tsx) | Isotipo, nombre y selector nativo de tema. Guarda solamente la elección visual en `kronshield.theme`. |
| [Primitivas](../frontend/src/ui.tsx) y [registros](../frontend/src/records.tsx) | Botones Radix, superficies, tablas semánticas, estados por texto y filtros sobre registros cargados. |
| [Entrada](../frontend/src/main.tsx), [shell](../frontend/src/workspace.tsx) y [flujos](../frontend/src/features/) | La portada y la sesión cargan primero. El espacio de trabajo se descarga tras autenticar. Incluye contexto organización/proyecto, control de alcance, administración, selección de equipo y consulta histórica. |

La auditoría del frontend en `a79d61a` encontró una navegación por hash, permisos efectivos desde `/me`, permisos y mutaciones con CSRF, y vistas separadas para autorizaciones, inventario y evaluaciones. El aspecto anterior estaba concentrado en una hoja clara y en la marca corporativa. La nueva capa visual reutiliza React, React Query, Lucide, formularios y tipos OpenAPI. La caché permanece delimitada por usuario, organización y proyecto. El historial usa los endpoints de detalle de importación, plan, eventos e informe. Como el piloto no ofrece una lista general de importaciones o planes históricos, se consulta por el UUID del registro. El filtro indica expresamente que trabaja sobre los datos cargados.

La portada combina información pública y acceso. El dashboard muestra las tres métricas disponibles, un gráfico de vigencia calculado sobre los mandatos cargados, evaluaciones recientes y la especialidad del proyecto. Una consulta de historial conserva la procedencia de los hallazgos importados y su confianza sin verificar. La navegación por teclado conserva la sección al saltar al contenido. Los enlaces antiguos a planes mantienen su formato.

## Tokens

| Familia | Valores y aplicación |
|---|---|
| Marca | Shield Emerald `#20D3A6`, Defense Teal `#0D9488`, Intelligence Blue `#38BDF8`. Aplica Emerald con texto oscuro en acciones principales. En superficies claras usa `#08786C` para texto de acción de menor tamaño. |
| Neutros | `#090F19`, `#111C2B`, `#263445`, `#F1F5F9`. Las superficies y el texto se asignan con `light-dark()` y `color-scheme`. |
| Semántica | Critical `#DC2626`, High `#F97316`, Medium `#EAB308`, Low `#38BDF8`, Info `#94A3B8`, Success `#22C55E`, AI `#A78BFA`. Los textos de error, advertencia y éxito tienen tonos específicos por tema. Combina color con etiqueta, recuento o icono. |
| Tipografía | Sora Variable para titulares, Inter Variable para interfaz y JetBrains Mono Variable para hashes e identificadores. Las fuentes se sirven en WOFF2 desde la compilación propia y usan `font-display: swap`. Las tres licencias OFL se distribuyen en `/licenses/`. |
| Ritmo | Unidad de 4 px. Radios de 8/12/16/24 px. Controles de 40–44 px en uso común. Transiciones de 160–200 ms sobre propiedades visuales. |
| Temas | Oscuro inicial, Claro explícito o Sistema. Los temas se aplican a controles nativos, avisos, gráficos y navegación. El ajuste de movimiento reducido desactiva las transiciones. |

El esquema oscuro usa una base de profundidad controlada, con glass solo en la navegación superior. El móvil presenta la navegación en dos filas y apila los paneles y formularios. Coincidencias, área seleccionada, límites y motivos de bloqueo son visibles sin depender del color. El estado de foco usa un contorno de 3 px. Los paneles con tablas pueden desplazarse internamente con teclado sin expandir el ancho de página.

## Proveniencia de la revisión de la skill externa

**REVIEW · UI UX Pro Max, revisión `8db36338810d0942567b97ce439affd1619fcf31`.** Se inspeccionaron el inventario, el adaptador Codex, la plantilla de instrucciones, las referencias rápidas y las rutas de búsqueda, persistencia, vista previa e instalación. La distribución para Codex genera una skill desde una plantilla y escribe en `.agents` mediante su instalador. La vía heredada obtiene el ZIP de la última release y la exportación de vistas previas puede incluir peticiones a Google Fonts. El proyecto incorporó de la referencia los criterios verificables de foco visible, controles nativos, avisos anunciados, movimiento reducido, color acompañado de texto y degradados limitados a superficies editoriales. La instalación del paquete completo queda pendiente de una revisión de la distribución generada y sus dependencias. [Plantilla Codex](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/8db36338810d0942567b97ce439affd1619fcf31/src/ui-ux-pro-max/templates/platforms/codex.json) · [Instalador](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/8db36338810d0942567b97ce439affd1619fcf31/cli/src/commands/init.ts) · [Guía rápida](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/8db36338810d0942567b97ce439affd1619fcf31/src/ui-ux-pro-max/templates/base/quick-reference.md)

## Validación reproducible

- Web y tipos: `npm --prefix frontend run build`.
- Pruebas de comportamiento y axe en Chromium: `npm --prefix frontend test -- shell.spec.ts`. Incluye 320/360/768/1440 px, navegación por teclado, tema, movimiento reducido, filtrado, selección por proyecto e historial.
- Regresión de capturas en Windows: `$env:KRONSHIELD_VISUAL='1'; npm --prefix frontend test -- shell.spec.ts --grep 'regresión visual'`. Las referencias se guardan en `frontend/tests/shell.spec.ts-snapshots`. Actualízalas de forma deliberada con `--update-snapshots`; la rasterización se compara en la plataforma de referencia.
- Lighthouse: compila el frontend, crea `frontend/playwright-report` si todavía no existe e inicia `node frontend/tests/audit-server.mjs`. En otra consola ejecuta `npx --yes --package=lighthouse@13.6.0 lighthouse http://127.0.0.1:4179/ --chrome-flags=--headless --output=json --output-path=./frontend/playwright-report/landing-lighthouse.json`. El servidor de auditoría solo sirve el build en loopback con sesiones sintéticas.
- La cobertura manual comprueba foco visible, salto al contenido, tabulación, límites de anchura, escala móvil y legibilidad en ambos temas. Las verificaciones automáticas aportan evidencia parcial de conformidad. [WCAG 2.2](https://www.w3.org/TR/WCAG22/) · [Playwright y axe](https://playwright.dev/docs/accessibility-testing) · [Lighthouse](https://developer.chrome.com/docs/lighthouse/)

### Evidencia local

- Capturas de Chromium con datos sintéticos. [Dashboard oscuro](../frontend/tests/shell.spec.ts-snapshots/dashboard-dark-win32.png) · [Dashboard claro](../frontend/tests/shell.spec.ts-snapshots/dashboard-light-win32.png) · [Landing móvil](../frontend/tests/shell.spec.ts-snapshots/landing-mobile-win32.png).
- La ejecución final pasó 15 pruebas de Chromium, incluidas dos pruebas de comparación de imágenes contra tres referencias. La suite Python pasó 379 pruebas y omitió una por permisos de enlaces simbólicos en Windows. También pasaron el build web y la comprobación de OpenAPI.
- Lighthouse 13.6.0 en móvil simulado, build comprimido y referencia local. Rendimiento 65/100, accesibilidad 100/100, buenas prácticas 96/100 y SEO 100/100. FCP 1,8 s, LCP 2,7 s, CLS 0,045 y TBT 2.500 ms. El reporte mostró una tarea larga de 2.342 ms sin URL atribuida y la respuesta 401 prevista al consultar una sesión inexistente. Esta medición corresponde a la landing pública y depende del equipo de prueba.
- Perfil de escritorio de la misma landing con `--preset=desktop`. Rendimiento 78/100, accesibilidad 100/100, buenas prácticas 96/100 y SEO 100/100. FCP 0,4 s, LCP 0,6 s, CLS 0,009 y TBT 510 ms.
- La comparación local contra `a79d61a` verifica que el contrato OpenAPI, el backend, las migraciones, la CLI y el render de informes históricos conservan su código. El piloto completo de esa revisión pasó en CI. El rediseño se probó localmente con el navegador y respuestas de API sintéticas. Docker Compose validó la configuración, con el daemon local detenido para el ensayo integral. [CI de la base](https://github.com/Blandskron/KronShield/actions/runs/45621213686)
