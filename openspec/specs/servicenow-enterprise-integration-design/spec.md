# servicenow-enterprise-integration-design Specification

## Purpose
Definir el golden path enterprise para entregar evidencia pre-CAB a ServiceNow sin
transferir autoridad de workflow, aprobación o decisión a PreflightOps.

## Requirements

### Requirement: Alcance de diseño sin efectos externos

La etapa SHALL producir contratos, ejemplos, threat model y planes validables. MUST NOT
abrir sockets, adquirir credenciales, desplegar componentes ni escribir en ServiceNow.

#### Scenario: Validación del diseño
- **WHEN** se ejecutan tests y quality gates de la etapa 09
- **THEN** sólo se leen archivos locales y no se invoca ningún endpoint externo

### Requirement: Enriquecimiento como camino normal

El contrato SHALL usar `enrich-existing` por number o sys_id como operación recomendada.
MUST fallar cerrado si el registro no existe, es ambiguo o cambia durante la operación.

#### Scenario: CHG inexistente
- **WHEN** `enrich-existing` no encuentra exactamente un Change
- **THEN** el resultado es `TARGET_NOT_FOUND` y no se crea un reemplazo

#### Scenario: Registro cambiado
- **WHEN** `sys_mod_count` ya no coincide con la precondición
- **THEN** el resultado es `CONCURRENCY_CONFLICT` sin write ni retry

### Requirement: Creación de draft gobernada

`create-draft` SHALL requerir un change model sys_id incluido en allowlist, capability
attestation, write enablement externo e idempotency key única. MUST NOT establecer state,
approval, assignment, schedule o closure.

#### Scenario: Modelo no permitido
- **WHEN** el model sys_id no pertenece al mapping aprobado
- **THEN** la operación falla `MODEL_NOT_ALLOWED` antes de solicitar token o enviar datos

### Requirement: API y mapping acotados

Producción SHALL usar un Evidence Gateway con allowlist y CAS server-side; sandbox MAY
usar Change Management API versionada. Table API MUST permanecer legacy y no crear en v2.
El mapping SHALL cubrir status de assessment, risk, confidence, assessment ID, policy,
blockers, impact, automation details, evidence URL, commit y timestamp sin permitir
campos de workflow.

#### Scenario: Campo privilegiado
- **WHEN** un mapping incluye `state`, `approval`, `assignment_group` o equivalente
- **THEN** schema y validación lo rechazan

### Requirement: Evidencia resumida y completa

El CHG SHALL recibir un resumen compacto y el assessment completo SHALL entregarse como
attachment canónico o URL HTTPS allowlisted. MUST NOT contener secretos, evidencia raw ni
payloads sensibles completos.

#### Scenario: URL con credenciales
- **WHEN** evidence URL contiene userinfo, query, fragment o host no permitido
- **THEN** el plan falla `UNTRUSTED_DESTINATION` sin resolver ni conectar

### Requirement: Identidad, replay e idempotencia

Request ID, delivery key y payload digest SHALL derivarse de campos canónicos no
sensibles. Producción MUST imponer unicidad server-side y distinguir replay idéntico de
una misma key con payload diferente.

#### Scenario: Replay idéntico
- **WHEN** delivery key y payload digest ya fueron aplicados al mismo target
- **THEN** el resultado es `UNCHANGED` sin nueva mutación o attachment

#### Scenario: Replay alterado
- **WHEN** una delivery key existente llega con otro payload digest
- **THEN** el resultado es `REPLAY_MISMATCH` y no se escribe

### Requirement: Autenticación y transporte

El diseño SHALL preferir OAuth client credentials con Application User, auth scope y ACL
mínimos. MUST rechazar redirects, TLS inválido, host no allowlisted y logs con token. MAY
usar mTLS/proxy sólo con capability y policy explícitas.

#### Scenario: Redirect cross-origin
- **WHEN** ServiceNow responde con redirect a otro origin
- **THEN** el adapter falla `REDIRECT_REJECTED` y no reenvía Authorization

### Requirement: Retry y partial failure fail-closed

GET MAY reintentarse bajo budget. POST/PATCH SHALL reintentarse sólo con idempotencia
server-side y reconciliation previa. `Retry-After` MUST respetarse dentro del límite. Un
write no verificable MUST terminar `PARTIAL_FAILURE_UNKNOWN`.

#### Scenario: Rate limit
- **WHEN** el endpoint responde 429 con `Retry-After` fuera del budget
- **THEN** el adapter falla `RATE_LIMITED` sin exceder intentos ni ocultar el bloqueo

### Requirement: Migración y verificación

El diseño SHALL incluir dual-preview, sandbox, contract tests, ATF/E2E, canary, abort
signals y rollback v1 read-only. La etapa 10 MUST requerir aprobación de la política del
gateway y de `create-draft` antes de implementar live writes v2.

#### Scenario: Rollback de adopción
- **WHEN** canary detecta wrong-record, mismatch o partial failure
- **THEN** live v2 se deshabilita y v1 queda sólo dry-run/read-only sin perder evidencia
