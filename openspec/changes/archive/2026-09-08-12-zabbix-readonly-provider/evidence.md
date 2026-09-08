# Evidencia de trabajo — etapa 12

Estado: implementación y CI del PR validados; especificación archivada.
Pendientes CI del archivo, fusión y verificación posterior.

La etapa 11 quedó fusionada mediante PR #48, commit main
3987aabef8fcf58a4adf3990217f51c83f068d3d. CI 34268509996, CodeQL
34268510064, Scorecard 34268509998 y Fuzzing 34268510053 finalizaron
correctamente. El comentario final del PR registra la verificación posterior.

## Implementado hasta ahora

- Cliente JSON-RPC aislado con siete métodos de lectura permitidos.
- Discovery sin credenciales; soporte explícito de autenticación para familias
  6.0, 7.0 y 7.4. No login ni métodos de escritura.
- Identidad de respuesta, claves duplicadas, JSON, tamaño y errores estáticos.
- Reintentos HTTP transitorios acotados y cancelación mediante contexto común.
- Mocks offline; no instancia Zabbix, credenciales reales o llamadas productivas.
- Transporte HTTPS con IP fijada por operador, verificación TLS/hostname, sin DNS,
  proxies ni redirects. Direcciones locales/metadatos prohibidas; privadas requieren
  opt-in explícito. Límites de bytes y deadline por lectura, incluyendo headers.

## Verificación local 2026-09-08

Provider añadido con seis controles independientes, configuración inmutable y
digest vinculado al request. Paginación por eventid, intervalo entre intentos y
freshness limitada por la caducidad de la muestra más antigua. Hosts deshabilitados
y triggers desconocidos no generan evidencia favorable de eventos vacíos.
Runbook: docs/ZABBIX_PROVIDER_V1.md. Decisión comparativa: design.md.

- 150 tests focalizados de cliente/transporte/provider/runtime aprobados.
- Suite general final: 906 tests aprobados; cobertura de líneas y ramas 86.22%
  (mínimo exigido 85%). Incluye regresiones de mantenimiento asignado a grupos.
- Ruff sin hallazgos; mypy sin errores en 29 módulos.
- OpenSpec validate --all --strict: 8/8 aprobado.
- Build sin aislamiento: sdist y wheel generados en dist-stage12.
- Twine check aprobado en ambos artefactos.
- Wheel actualizado instalado sin dependencias ni red en .stage12-wheel-final; importación
  aislada del provider comprobada desde esa instalación, no desde el source tree.

Pruebas cubren replay independiente, contrato reusable, expiración exacta de
muestras, ausencia de objetos, estados desconocidos/deshabilitados, recurrencia,
autenticación, redacción, límites, paginación parcial y respuestas malformadas.

## Pendientes

Revisión de filtros contrastada con implementación oficial de Zabbix 7.0:
hostids no incluye asignaciones a grupos. Se añadió consulta separada con
selectGroups (6.0) / selectHostGroups (7.x), filtrado de asignaciones ajenas y
regresiones en las tres familias. ADR público: docs/ADR_ZABBIX_PROVIDER_V1.md.

PR #49: https://github.com/pedroluna-gh/preflightops/pull/49
Head validado: 4a2b36da2a3a3b28763010bae294c8154a26e0ba.
Los 15 archivos publicados coinciden con el contenido local tras normalización LF,
comparados contra hashes de objetos remotos. Todos los jobs terminaron con éxito:

- CI, 11 jobs incluidos Required, matriz y auditorías: 34271306483.
- Seguridad, CodeQL y dependency review: 34271306438.
- Fuzzing: 34271306507.

Especificación promovida a openspec/specs/zabbix-evidence-provider/spec.md;
cinco artefactos preservados en este archivo histórico. Pendientes: CI del head
final tras archivar, fusión y verificación posterior. No declarar cierre antes de
registrar esos resultados en el PR. No se declara madurez 5/5.

## Riesgos y rollback provisional

El transporte HTTPS se probó con sockets simulados, no con un sandbox real. Una IP
fijada exige actualización operativa ante cambios del servicio. No adoptar como
integración validada en vivo: faltan sandbox separado y gates remotos. Desactivar
la selección del provider revierte la adopción sin afectar las APIs existentes.
El límite de tasa es por instancia; el consumidor debe controlar concurrencia.
Permisos parciales y cambios de estado entre llamadas requieren evaluación humana.
