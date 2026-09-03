# Plan de pruebas ServiceNow v2

## Objetivo

Demostrar antes de producción que el adapter entrega evidencia al Change correcto de
forma idempotente, acotada, privada y fail-closed. Las pruebas automatizadas de etapa 10
usan transporte/resolver/clock inyectados y no contactan una instancia. La validación de
sandbox es un gate posterior, separado y autorizado; nunca se prueba en producción.

## Pirámide

| Nivel | Entorno | Cobertura mínima | Gate |
| --- | --- | --- | --- |
| Unit/schema | Offline | Canonicalización, IDs, mapping, redacción, taxonomy | Cada commit |
| Transport mocks | Offline | HTTP, redirects, timeout, 429/5xx, malformed response | Cada commit |
| Contract | Mock server | Request/result/gateway capability y Change API fixtures | PR |
| ServiceNow ATF | Sandbox | ACL, role, denylist, CAS, uniqueness, model allowlist | Pre-canary |
| E2E | Sandbox Change dedicado | Preview, enrich, replay, attachment, draft opt-in | Pre-canary |
| Resilience | Sandbox | Race, timeout-after-write, 429, proxy/mTLS rotation | Release |

## Casos obligatorios

### Positivos

- Preview idéntica produce los mismos bytes, request ID, delivery key y payload digest.
- Enrich por number y sys_id fija ambos identificadores y verifica read-back.
- Replay idéntico devuelve `UNCHANGED` sin nueva mutación/attachment.
- Draft usa exactamente un model sys_id allowlisted y queda en estado del modelo.
- 429 respeta `Retry-After` dentro del budget.
- OAuth client credentials y mTLS capability opcional funcionan sin registrar secretos.

### Negativos

- Not-found/ambiguous/wrong number/sys_id; mapping desconocido o digest distinto.
- Model no permitido, create deshabilitado o autorización externa ausente.
- Scope/ACL insuficiente, token expirado, cert inválido, proxy no permitido.
- Response sin sys_id/number/delivery digest o con schema inesperado.
- Attachment demasiado grande, duplicado ambiguo o read-back distinto.

### Adversariales

- HTTP, userinfo, puerto, path/query/fragment y host lookalike; DNS rebinding/IP privada.
- 301/302/303/307/308 same-origin y cross-origin con canary Authorization.
- Tokens, passwords, JWT, PEM, cookies y raw evidence en errores/responses/logs.
- `state`, `approval`, `assignment_group`, `assigned_to`, fechas, close fields, work notes,
  tasks y transition endpoints en mapping/payload.
- Dos writers con mismo/diferente delivery key y `sys_mod_count`.
- Timeout después de commit, caída entre record y attachment, retry tras 502/503/504.
- Replay del mismo assessment contra otro Change/model/instance/mapping.

## Mocks y fixtures

- Transporte inyectado; no monkeypatch global de red.
- Fixtures content-free con host `.example.test`, CHG/sys_id ficticios y hashes repetidos.
- Mock stateful modela `sys_mod_count`, índice único, attachment digest y Business Rules.
- Socket-block test garantiza que validate/preview no intentan red o secret provider.
- Golden request/plan/result usa LF y canonical JSON.

## Contract y sandbox

El mock contract debe fijar endpoints/versiones y payloads sin snapshot de headers
secretos. ATF valida el rol custom con matriz allow/deny por campo y que ningún endpoint
de approvals/tasks/transitions/delete es accesible. La sandbox debe:

1. ser no productiva y contener Changes descartables;
2. tener plugin/release/capabilities inventariados;
3. usar Application User y auth scope dedicados;
4. registrar auditoría y sys_mod_count;
5. ejecutar cleanup manual aprobado, nunca desde el adapter.

## Evidencia de salida de implementación y gates externos

- Tests positivos, negativos, adversariales y compatibilidad v1 verdes.
- Cobertura branch-aware ≥85%, Ruff, mypy, packaging y CI multiplataforma verdes.
- Antes del canary: ATF/E2E autorizados con IDs de ejecución,
  mapping/capability digests y Change sandbox según
  [`SERVICENOW_SANDBOX_VALIDATION.md`](SERVICENOW_SANDBOX_VALIDATION.md).
- Cero secretos/canaries en logs/artifacts.
- Race/replay/partial failure demostrados fail-closed.
- Rollback drill documentado y aprobado por ServiceNow owner + Change owner.
