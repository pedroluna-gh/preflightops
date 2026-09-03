# Diseño: reportes de Assessment Contract v1

## Context

La superficie humana debe ser rápida de revisar y la superficie de máquina debe ser
estricta, estable y auditable. Un renderer no puede elevar ERROR/UNKNOWN, confundir una
recomendación con aprobación ni romper consumidores legacy.

## Design Options

| Opción | Beneficio | Desventaja |
| --- | --- | --- |
| Conservadora: adaptar en sitio los reportes legacy | Menos archivos y flags | Mezcla dos contratos, arriesga compatibilidad y pierde invariantes estrictos |
| Balanceada: contrato de reporte aditivo y renderizadores puros | Determinismo, rollback simple, migración gradual y privacidad verificable | Requiere que el caller entregue un Assessment Contract v1 válido |
| Enterprise: templates remotos, publicación automática y enriquecimiento live | Mayor personalización e integración inmediata | Introduce red, credenciales, mutabilidad, exposición y lifecycle fuera de alcance |

## Decision

Se elige la opción balanceada. `assessment-report-v1` es una proyección completa para
decisión pre-CAB: incluye todos los controles clasificados y toda provenance permitida,
pero nunca el payload raw. Su ID e integrity hash cubren la proyección semántica y la
configuración de rendering.

## Contract

El contrato contiene:

- `audit`: assessment ID/timestamp, schema/producer/policy, repository, PR, commit,
  pipeline/run, hashes de inputs y hash canónico del assessment;
- `decision`: verdict, recomendación técnica con `grants_approval: false` y decisión
  humana externa como conceptos independientes;
- `scores`: risk y confidence sin recalibración;
- `controls`: counts, top blockers, passed, failed, unknown y errors;
- `evidence`: counts de freshness y provenance metadata content-free;
- `next_actions`: acciones determinísticas basadas en estados/códigos;
- `automation_details`: bloque breve incluido u omitido de forma explícita;
- `rendering` e `integrity`: límites, perfiles y hash canónico.

## Determinism and Status Invariants

No se usa reloj, filesystem, entorno, red o aleatoriedad. Se preserva el timestamp del
assessment, se ordenan items por claves estables y se usa JSON canónico LF. Si existe
ERROR o UNKNOWN, el reporte conserva `INDETERMINATE` y `DO_NOT_PROCEED`; ningún
renderer puede convertir esos estados en PASS o aprobación.

## Redaction and Limits

Todo texto libre pasa por un perfil versionado que elimina asignaciones de
password/token/secret/API key, Bearer/JWT, access keys conocidas y caracteres de
control. Cada texto se trunca determinísticamente con marcador. Los resúmenes PR y
ticket aplican budgets configurables y conservan siempre la cabecera de decisión,
boundary humana y referencia al reporte completo cuando se suministra una URL HTTPS
sin credenciales, query o fragment.

## Markdown

Los valores dinámicos se escapan para tablas y listas. El informe completo muestra en
orden: 30-second review, blockers, UNKNOWN/ERROR, passed controls, freshness,
provenance, next actions, Automation Details opcional y audit metadata. Los resúmenes
compactos no incluyen evidencia raw.

## CLI and File Safety

`preflightops report render` requiere `--assessment` y al menos una ruta de output
explícita. Cada destino se crea de forma exclusiva; si ya existe, falla cerrado salvo
`--overwrite`, que es una autorización local explícita. El comando no contiene ninguna
ruta de publicación o integración externa.

## Migration

Consumidores pueden generar outputs nuevos en paralelo, comparar golden/snapshots y
mover readers al schema nuevo. Los reportes legacy permanecen durante toda la
migración. Cambios incompatibles requieren un schema nuevo.

## Residual Risks

- La redacción por patrones no clasifica semánticamente todos los secretos posibles;
  producers siguen obligados a no incluir contenido sensible.
- Hashes e identificadores aprobados pueden actuar como correladores y requieren una
  política de retención adecuada.
- La meta de revisión menor a un minuto se valida por estructura y budgets, pero la
  latencia humana real depende de cantidad de findings y experiencia del reviewer.

