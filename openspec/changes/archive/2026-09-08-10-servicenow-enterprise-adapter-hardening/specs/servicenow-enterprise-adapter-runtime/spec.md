# servicenow-enterprise-adapter-runtime Specification

## Purpose

Implementar el adapter ServiceNow v2 aprobado de forma explícita, idempotente,
testeable, redactada y fail-closed, sin transferir autoridad CAB a PreflightOps.

## ADDED Requirements

### Requirement: Preview pura y determinística

El runtime SHALL validar report, mapping, origin y evidence offline y SHALL derivar
mapping digest, payload digest, delivery key y request ID mediante canonical JSON.

#### Scenario: Preview repetida
- **WHEN** se usa el mismo report, mapping y contexto explícito
- **THEN** el plan y todos sus IDs son byte-for-byte idénticos sin token ni red

### Requirement: Default sin escritura

Dry-run SHALL ser default y MUST realizar cero llamadas a resolver, credential provider
o transport. Read-only MAY consultar Change API pero MUST NOT mutar.

#### Scenario: Confirmación ausente
- **WHEN** un plan live write se ejecuta sin confirmación explícita
- **THEN** retorna fallo de autorización antes de adquirir token o enviar datos

### Requirement: Target, CAS e idempotencia

Enrich SHALL resolver exactamente un CHG, fijar number/sys_id y comparar
`sys_mod_count`. Gateway MUST atestiguar CAS y delivery única. Replay idéntico SHALL ser
`UNCHANGED`; replay alterado SHALL fallar sin write.

#### Scenario: Carrera
- **WHEN** lookup devuelve un `sys_mod_count` distinto del esperado
- **THEN** retorna `CONCURRENCY_CONFLICT` y el gateway no recibe POST

### Requirement: Draft desactivado por defecto

Create draft SHALL requerir mapping habilitado, feature flag runtime, model allowlisted,
autorización externa, gateway capability y confirmación. MUST NOT enviar campos de
workflow, approval, assignment, schedule o closure.

#### Scenario: Feature flag apagada
- **WHEN** se solicita create draft con el default de runtime
- **THEN** falla antes de token, resolver o transport

### Requirement: Transporte y auth endurecidos

El adapter SHALL exigir HTTPS/host/IP policy, rechazar redirects, limitar body/timeouts y
usar OAuth client credentials. Basic MUST permanecer fuera del runtime v2.

#### Scenario: Redirect
- **WHEN** cualquier request protegida recibe 301/302/303/307/308
- **THEN** retorna `REDIRECT_REJECTED` sin seguir ni reenviar Authorization

### Requirement: Retry y recuperación fail-closed

Retries SHALL estar acotados y respetar `Retry-After`. Un write timeout/5xx MUST
reconciliar antes de retry; sin estado verificable SHALL ser `PARTIAL_FAILURE_UNKNOWN`.

#### Scenario: Timeout después de commit
- **WHEN** POST expira pero reconcile encuentra delivery aplicada y válida
- **THEN** se retorna el resultado verificado sin duplicar el write

### Requirement: Privacidad y compatibilidad

Plans/results/logs MUST NOT contener secrets, headers, body remoto completo ni target
completo en eventos. V1 SHALL permanecer compatible y sin fallback implícito.

#### Scenario: Error remoto sensible
- **WHEN** response/error incluye token, password o payload remoto
- **THEN** sólo se expone código, retryability, write state y mensaje estático redactado
