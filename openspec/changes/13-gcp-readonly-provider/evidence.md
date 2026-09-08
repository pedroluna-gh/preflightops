# Evidencia de trabajo — etapa 13

Estado: implementación y gates locales aprobados; publicación y CI pendientes.
No lista para cierre.

Prerequisito: etapa 12 cerrada en PR #49, main
610f77cf86322a7ba4c36989a0f7d840d3b3e926. CI 34272904186, CodeQL
34272904270, Scorecard 34272904260 y Fuzzing 34272904345 aprobados.
El comentario final del PR conserva ese registro y sus riesgos/rollback.

## Implementado

gcp_scope.py define configuración inmutable, allowlist, selecciones explícitas
de policies/dashboards/uptime/services/SLOs, métricas y assets. Los nombres deben
pertenecer al proyecto seleccionado, aunque otros estén en el allowlist.
Filtros de métricas incluyen resource.labels.project_id; valores escapados y
labels reservados impiden que la selección amplíe el metrics scope.
Digest estable incluye principal/proyecto referenciados y presupuestos.

gcp_requests.py construye lecturas REST oficiales por recurso seleccionado,
con proyecciones mínimas. No enumera proyectos. Las series solicitan intervalos,
identidad y errores parciales, no valores. Asset Inventory solicita nombre/tipo/
updateTime, sin contenido del recurso, con regex exacta del tipo y readTime explícito.
Los tokens de página se acotan y codifican como datos, no como parámetros extra.
Este módulo prepara requests sin ejecutar red.
La validación previa al transporte reconstruye la lectura permitida y rechaza
URLs, campos y filtros que no coincidan con la selección aprobada.

gcp_auth.py incorpora binding de objetos oficiales google.auth.credentials:
ADC explícitamente inyectadas, rechazo de AnonymousCredentials y scope solicitado
sin inferir identidad IAM. No ejecuta default(), refresh ni introspección de tokens.
Se agregó extra opcional gcp y lock con google-auth 2.57.1, pyasn1 0.6.4 y
pyasn1-modules 0.4.2. Descargas limitadas a dependencias públicas; sin acceso GCP.

gcp_client.py ejecuta lecturas validadas mediante transporte inyectado, con
reintentos limitados, intervalo mínimo y errores estáticos sin payload remoto.
Rechaza JSON ambiguo, duplicados, valores no finitos y respuestas sobredimensionadas.
La paginación mantiene la selección original, acota páginas y tokens, detecta
ciclos y no retorna colecciones parciales ante errores o agotamiento del presupuesto.
Los consumidores todavía deben validar provenance y freshness de cada recurso.

gcp_transport.py implementa HTTPS con requests y before_request de google-auth.
Recursos sólo GET; refresh separado y allowlisted (OAuth/STS/generateAccessToken),
sin redirects/proxies ambientales. Límites de streaming, deadline cooperativo,
cierre de sesión y redacción probados con objetos oficiales sintéticos.

gcp_observations.py valida proyecto y número, enabled/validity de policy,
presencia de dashboard/uptime/service, objetivo/período SLO, snapshot de assets
y freshness de todas las series retornadas, sin afirmar cobertura integral.
Timestamps preservan nanosegundos; expiración redondeada hacia abajo.

gcp_provider.py integra el ciclo open/collect/close y ProviderEvidence v1.
Resuelve un único supplier por ejecución y verifica el proyecto antes de controles.
Identity queda UNKNOWN cuando principal y scopes no tienen atestación independiente.
No se deriva identidad efectiva de aliases o has_scopes. El runbook y ADR explican
este límite, IAM mínimo y rollback.

## Verificación local actual

- 158 pruebas GCP de alcance/requests/ADC/transporte/paginación/mapping/provider aprobadas
  sin red cloud ni credenciales reales.
- Suite general final: 1064 pruebas aprobadas en 37.64 segundos; cobertura de ramas
  combinada 86.80 %, superior al gate 85 %.
- Ruff check y formato aprobados para preflightops y tests (76 archivos).
  scripts/package_smoke.py también validado después de ampliar su smoke test.
- Mypy aprobado en 36 módulos.
- Entorno aislado .venv-gcp creado desde uv.lock para la dependencia opcional.
- El intento inicial de sync encontró una diferencia de Python y permisos en
  .venv; se restauró su ejecutable con venv sin --clear. Validación actual ejecutada
  en .venv-gcp, Python 3.12.13. Posteriormente se restauraron las dependencias de
  .venv desde caché con sync --locked --offline y se verificó pytest 9.1.1.
  No se borraron archivos fuente del producto.
- OpenSpec estricto: 9/9 (8 specs y el cambio de etapa 13).
- Wheel/sdist construidos y Twine aprobados en .tooling/stage13-dist.
- Instalación limpia offline del wheel, CLI --version e import/construcción del
  provider GCP sin extra opcional aprobados. El primer intento encontró caché
  incompleta y el intento con red permisos de lectura del wheel. Se poblaron
  dependencias públicas fijadas en caché y se repitió el smoke offline con éxito.
- OpenSpec estricto revalidado: 9/9, sin fallos.
- Revisión de seguridad: modo non-blocking refresh rechazado sin mutar ADC;
  callback de autenticación revocado al finalizar before_request. Tres pruebas
  adicionales verifican estas restricciones.
- Auditoría del entorno locked con todos los extras: sin vulnerabilidades
  conocidas. Se omitió únicamente preflightops por ser la distribución editable
  bajo prueba. No se enviaron código ni credenciales, sólo metadatos de paquetes.
- Wheel reconstruido después del hardening y smoke de instalación limpia
  repetido correctamente. Ruff completo del repositorio validado, incluido
  formato de ejemplos Markdown; OpenSpec estricto 9/9.

## Pendientes

Publicación/CI/archivo/fusión y verificación posterior del commit integrado.
La configuración y mocks no prueban permisos ni identidad de una cuenta GCP real.
El control identity permanece UNKNOWN, explícitamente, sin atestación independiente.

## Riesgos y rollback

Los nombres de proyecto y filtros permanecen internos; los hashes no anonimizan
valores predecibles. No se ejecutaron consultas cloud: rollback del trabajo local
retira su futura selección sin afectar CLI/Action o outputs legacy.
No se utilizaron credenciales ni recursos productivos.
