# Evidencia incremental de etapa 14

## Estado

En implementación local; no publicada, no fusionada y no cerrada. Ningún
resultado de la etapa 13 se utiliza como sustituto de las verificaciones de 14.

## 2026-09-08: simulación con claves independientes

- Corrección aditiva: `policy simulate` admite `--base-public-key`,
  `--candidate-public-key` y `--at` opcional.
- Las firmas de documentos activos se verifican independientemente; los
  borradores no se activan y la decisión humana permanece no registrada.
- `--at` registra el instante normalizado: una simulación no acredita vigencia
  operacional ni sustituye la validación de una evaluación activa.
- 37 pruebas focalizadas pasaron: 30 existentes y 7 nuevas, incluyendo claves
  incorrectas, ausencia de confianza, alteración de firma y repetibilidad.
- Ruff check y format de ambos archivos cambiados: correctos.
- mypy: 36 módulos sin errores.
- OpenSpec estricto: 10 elementos correctos, incluyendo este cambio.

## Pendiente obligatorio

Publicación, CI, archivo y post-merge. No se declara
madurez 5/5 ni finalización de etapa 14. La checklist se cerrará sólo al obtener
evidencia final para cada bloque.

## 2026-09-08: gobierno y reproducción histórica

- Carga común acotada de YAML/JSON: rechaza duplicados, alias, ciclos, fechas
  implícitas, valores no finitos y estructuras excesivas; errores sin payload.
- Campos cerrados de Policy Bundle v2 y Waiver v1; reglas vacías o duplicadas
  de waiver rechazadas. Diff/simulación exige nueva versión si cambia contenido.
- `governance-failure-v1` separa detener de continuar informativamente. V2 con
  inventario requerido ausente respeta el modo configurado sin cambiar score,
  findings, confidence ni autoridad. Waivers no eliminan el stop.
- `--governance-at` permite reproducir política y waivers con un único instante;
  prohíbe integraciones reales en replay histórico.
- Pruebas focalizadas de replay: 13 aprobadas; bloque previo de gobierno:
  71 aprobadas. Incluyen los tres tipos de cambio, firma, expiración exacta,
  rollback, versión, entradas adversariales y reportes CLI reproducibles.
- La suite integral intermedia detectó tres fallos de registro de schemas por
  ausencia de `$id` en el nuevo schema; corregido. Se repite la suite completa.
- Ruff: 375 archivos formateados, lint correcto. mypy: 38 módulos correctos.
  OpenSpec estricto: 10 elementos correctos.
- Build, Twine y wheel limpio pasaron antes del último endurecimiento de firma;
  deben repetirse para el contenido final. No cambiaron dependencias ni lockfile.
- Un primer build encontró un error transitorio de reemplazo de metadata en
  Windows; repetir el build sin otra verificación simultánea tuvo éxito.

## Verificación integral del contenido actual

- Suite completa: **1118 pruebas aprobadas**, 81.44 s.
- Cobertura combinada con ramas: **87.14%**, superior al gate 85%.
- Los tres fallos de registro de schema quedaron resueltos en la repetición.
- Build de wheel y sdist, Twine y smoke de wheel limpio repetidos correctamente
  después del último cambio de código. Instalación offline con dependencias
  fijadas; no se añadieron dependencias de runtime.
- Ruff check/format: correctos (375 archivos). mypy: 38 módulos sin errores.
- OpenSpec estricto: 10 elementos correctos. No se ha publicado una rama de 14.

## Revisión final previa a publicación

- Alineación schema/runtime: 14 pruebas adicionales aprobadas. Se rechazan
  listas duplicadas, expiración nula, digests mal formados y timestamps que no
  cumplen RFC 3339. Los límites se aplican antes de copiar entradas de API.
- Los formatos de JSON Schema son anotaciones y algunas instalaciones no
  incluyen su validador opcional de date-time; runtime aplica RFC 3339 de forma
  independiente. No se agregó dependencia para suplir esa anotación.
- Suite final: **1132 aprobadas**, 86.15 s; cobertura **87.19%**.
- Ruff: 376 archivos correctos; mypy: 38 módulos; OpenSpec: 10 elementos.
- Build, Twine y wheel limpio repetidos con éxito después del último cambio.
- Base remota verificada idéntica a 99eb77dc54acb26119d9924dda0a615b2f2738dc.

## Riesgos y rollback

La confianza en las claves la aporta el operador; la firma no acredita por sí
sola el rol corporativo. No se usaron claves productivas ni se hicieron llamadas
de proveedores. Volver a la distribución aprobada anterior conserva contratos
legacy; las nuevas opciones de simulación simplemente no estarán disponibles.
