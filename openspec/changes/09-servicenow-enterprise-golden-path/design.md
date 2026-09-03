# Diseño: ServiceNow enterprise golden path

## Context

ServiceNow sigue siendo system of record y autoridad de workflow/CAB. PreflightOps sólo
produce evidencia técnica pre-CAB. El diseño debe impedir que mapping, credenciales,
retries o carreras amplíen esa autoridad.

## Opciones evaluadas

| Diseño | Beneficio | Desventaja | Uso |
| --- | --- | --- | --- |
| Conservador: Table API v1 enrich-only | Migración mínima | Sin semántica de modelos y CAS no atómico | Rollback temporal |
| Balanceado: Change Management API directa | API versionada y model-aware | El endpoint permite campos amplios; los guards cliente conservan TOCTOU | Sandbox/piloto |
| Enterprise: Evidence Gateway acotado | Allowlist y CAS server-side, idempotencia única y auditoría | Requiere componente/configuración en la instancia | Producción elegida |

## Decisión

Elegir el diseño enterprise. El gateway expone sólo `preview`, `enrich-existing` y
`create-draft`; internamente preserva la semántica del Change Management API. Un perfil
directo versionado queda disponible sólo para sandbox/piloto. Table API no será default
v2 y jamás podrá crear en modo legacy.

## Límites de autoridad

- PreflightOps MAY escribir exclusivamente campos de evidencia allowlisted y un
  attachment JSON versionado.
- PreflightOps MUST NOT escribir state, approval, assignment, schedule, close fields,
  work notes, approvals, tasks ni ejecutar transiciones/risk evaluation.
- `create-draft` MUST requerir model sys_id allowlisted, capability attestation,
  confirmación externa y un idempotency key único. El estado deriva del modelo; el
  cliente no lo establece.
- `enrich-existing` MUST requerir exactamente number o sys_id y fallar si no existe,
  es ambiguo o cambia durante la operación.

## Contrato y determinismo

Request, mapping y result son JSON v2 estrictos. La preview canónica no contiene
credenciales. `request_id`, `idempotency_key` y `payload_sha256` se derivan de operación,
alias de instancia, destino/modelo, assessment/report IDs, mapping digest y payload
canónico. Timestamps vienen del caller y no participan en la identidad semántica.

## Concurrencia e idempotencia

Producción exige un índice único sobre delivery/idempotency key y compare-and-set
server-side con `expected_sys_mod_count`. Conflicto produce `CONCURRENCY_CONFLICT` sin
retry ni escritura. Un replay idéntico devuelve `UNCHANGED`; misma key con digest
distinto devuelve `REPLAY_MISMATCH`. Locks cliente sólo reducen carga, no son control de
integridad.

## Transporte y autenticación

- Default `dry_run=true` y `write_enabled=false`.
- OAuth client credentials con Application User, REST API Auth Scope dedicado y ACL de
  campos; evitar `useraccount` y cuentas personales/admin.
- mTLS inbound es opcional cuando la edición de ServiceNow lo soporta; proxy sólo con
  hostname allowlisted, CONNECT al destino esperado y sin terminación que exponga token.
- TLS verification y redirect refusal obligatorios. Tokens sólo en headers y memoria,
  nunca en request/plan/result/log.

## Retries y fallos parciales

GET MAY reintentarse con backoff acotado y jitter inyectado por policy. POST/PATCH sólo
MAY reintentarse tras 429/502/503/504 cuando existe idempotency key server-side y el
resultado previo se consulta antes. `Retry-After` prevalece dentro del budget. Un write
sin read-back verificable termina `PARTIAL_FAILURE_UNKNOWN`; nunca se afirma éxito.

## Evidencia y privacidad

El CHG recibe resumen compacto, status de assessment, risk, confidence, assessment ID,
policy, blockers, impact, automation details, evidence URL, commit y timestamp. El
assessment completo se entrega como attachment canónico o enlace HTTPS allowlisted. No
se copian evidencia raw, secretos ni payloads de provider.

## Migración

1. Inventariar campos/choices/ACL/modelos y desplegar v2 en dry-run.
2. Comparar preview v1/v2 y registrar mapping digest.
3. Habilitar enrich-existing en sandbox mediante gateway; crear draft sigue desactivado.
4. Ejecutar contract/ATF/E2E y prueba de concurrencia/replay.
5. Canary productivo enrich-only; después evaluar create-draft por policy separada.
6. Mantener v1 como rollback read-only durante una ventana definida y retirar su live
   write sólo tras evidencia aprobada.

## Riesgos residuales

- El gateway y los ACL son configuración del cliente y requieren auditoría independiente.
- Business Rules pueden transformar campos después del write; read-back y ATF siguen
  siendo obligatorios.
- mTLS y OAuth dependen de capacidades/licencia/release de la instancia.
- La creación de drafts aumenta volumen y ownership operativo aun sin aprobar cambios.

## Política pendiente antes de etapa 10

Se requiere aprobación humana para hacer obligatorio el Evidence Gateway y el campo
único de delivery en producción, y para decidir si `create-draft` se implementa habilitado
por configuración o se mantiene compilado pero denegado por defecto.
