# ServiceNow enterprise golden path

## Resultado y límites

Este diseño mantiene ServiceNow como system of record y a CAB/Change Management como
única autoridad de aprobación y workflow. PreflightOps prepara y entrega evidencia
técnica pre-CAB; no decide, aprueba, asigna, agenda, implementa ni cierra cambios.

La etapa 09 es diseño puro. Los schemas v2 y ejemplos describen el target de la etapa 10,
pero el runtime actual sigue siendo v1 y no se añade ninguna llamada de red.

El [diagrama del flujo](diagrams/servicenow-enterprise-golden-path.mmd) muestra los tres
trust boundaries y el punto exacto donde un write se habilita externamente.

## Golden path

1. Validar Assessment Contract/Report, mapping y request v2 offline.
2. Generar preview canónica sin credenciales y mostrar destino, operación, campos,
   digests, precondiciones y efectos esperados.
3. Default `enrich_existing`: resolver exactamente un Change por number o sys_id.
4. Verificar capability attestation, mapping digest y `expected_sys_mod_count`.
5. Sólo con autorización externa, obtener un token corto y ejecutar contra el Evidence
   Gateway; no se siguen redirects.
6. El gateway valida field allowlist, delivery key única y compare-and-set atómico.
7. Aplicar summary y, opcionalmente, attachment o enlace allowlisted.
8. Read-back y reconcile. Responder éxito sólo si identidad, digest y campos coinciden.

`create_draft` es una capability separada. Exige un change model sys_id permitido,
autorización explícita y delivery key única. El modelo decide el estado inicial; el
cliente no envía `state`.

## API: Change Management frente a Table API

| Perfil | API | Permitido | Restricción |
| --- | --- | --- | --- |
| Producción | Evidence Gateway v1 | preview, enrich-existing, create-draft autorizado | Allowlist + CAS + unicidad server-side |
| Sandbox/piloto | Change Management API v1 | lookup/model, preview y pruebas controladas | Live sólo con capability guard atestiguado |
| Legacy | Table API v1 | compatibilidad v1 y rollback read-only | No creación ni live write v2 |

Change Management API es preferible a Table API porque modela Change y sus change
models en una superficie versionada. Sin embargo, su endpoint de update admite campos
del Change; el gateway reduce esa superficie a evidencia. Attachment API se usa sólo
para el JSON canónico acotado y deduplicado.

## Mapping semántico

El mapping v2 nombra semántica estable y destinos específicos por instancia. El ejemplo
[`servicenow-enterprise-mapping-v2.yaml`](../examples/servicenow-enterprise-mapping-v2.yaml)
usa sólo campos `u_preflightops_*`:

| Semántica | Fuente report v1 | Regla |
| --- | --- | --- |
| Assessment status | `decision.verdict` | No equivale a `change_request.state` |
| Risk | `scores.risk` | Preferir custom; standard `risk` requiere choice mapping aprobado |
| Confidence | `scores.confidence` | Independiente de risk |
| Assessment ID | `audit.assessment_id` | URN completa o digest según límite |
| Policy | `audit.policy` | Nombre, versión y hash allowlisted |
| Blockers | `controls.top_blockers` | Compacto, acotado, conserva UNKNOWN/ERROR |
| Risk impact | technical recommendation summary | No concede aprobación |
| Automation details | `automation_details` | Sólo metadata allowlisted |
| Evidence URL | `delivery.evidence_url` | HTTPS, host allowlisted, sin query/fragment |
| Commit | `audit.commit` | SHA validado |
| Timestamp | `audit.assessment_timestamp` | Explícito del contrato |

Mappings que incluyan workflow, approval, assignment, schedule, closure, journal/task o
campos no allowlisted se rechazan antes de adquirir credenciales.

## Summary y assessment completo

El registro guarda un resumen compacto suficiente para revisión: verdict técnico, risk,
confidence, top blockers, policy, IDs, commit y timestamp. El Assessment Report completo
se publica como attachment JSON canónico o enlace HTTPS allowlisted. No se inserta el
payload completo en `description`; no se publican raw evidence, provider payloads,
secretos, cabeceras o URLs firmadas con query sensible.

## Identidad, idempotencia y concurrencia

La canonicalización es JSON con claves ordenadas, UTF-8, sin whitespace y enteros
normales. Se calculan:

- `payload_sha256 = sha256(canonical(mapped_evidence_fields))`;
- `idempotency_key = "snv2-" + sha256(version || operation || instance_alias ||
  target_or_model || assessment_id || report_sha256 || mapping_sha256 ||
  payload_sha256)`;
- `request_id = "snreq-" + first_32_hex(sha256(idempotency_key || dry_run ||
  expected_sys_mod_count))`.

El gateway impone índice único por delivery key. Repetición con mismo digest devuelve
`UNCHANGED`; misma key con digest distinto devuelve `REPLAY_MISMATCH`. Para
`enrich_existing`, `expected_sys_mod_count` es obligatorio y el gateway ejecuta CAS en
una transacción. Locks/concurrency groups del caller son optimización, no garantía.

## Autenticación y red

- Preferir OAuth 2.0 client credentials para machine-to-machine, Application User
  dedicado, REST API Auth Scope específico, rol custom y ACL por campo.
- No usar `useraccount`, admin, cuentas personales ni password grant. Basic Auth queda
  restringido a compatibilidad de sandbox y no forma parte del golden path.
- Mantener client secret/token en secret manager; adquirirlo después del preview y
  borrarlo de memoria al finalizar. Nunca aparece en CLI, archivos o logs.
- Validar origin HTTPS exacto, puerto 443, DNS/IP policy y certificado. Deshabilitar
  redirects automáticos y no reenviar Authorization a otro origin.
- mTLS inbound es opcional por capability. Si existe proxy corporativo, sólo se permite
  CONNECT al origin esperado; no se confía en variables proxy no aprobadas.

## Retries y rate limits

| Caso | Retry | Acción |
| --- | --- | --- |
| Validación, auth 400/401/403, 404, 409/CAS | No | Falla cerrada y evidencia del código |
| GET timeout/502/503/504 | Sí, acotado | Backoff con budget total |
| 429 | Sí si cabe | Respetar `Retry-After`; fuera del budget retorna `RATE_LIMITED` |
| POST/PATCH timeout o 5xx | Sólo con unicidad server-side | Reconcile por delivery key antes de reintentar |
| Write sin read-back | No afirmar éxito | `PARTIAL_FAILURE_UNKNOWN` y revisión humana |

## Threat model específico

| Amenaza | Control de diseño | Verificación prevista |
| --- | --- | --- |
| SSRF/DNS rebinding | Origin allowlist, DNS/IP policy antes de token y por conexión | Casos URL/IP adversariales |
| Redirect credential leakage | Redirects deshabilitados; Authorization nunca se reenvía | Mock 301/302/307/308 cross-origin |
| Log leakage | Mensajes por código, redacción, sin headers/body raw | Captura de logs con canaries |
| Wrong-record update | Exactamente number/sys_id, pin de ambos tras lookup, CAS y read-back | Ambiguo/not-found/mismatch |
| Privilege escalation | Gateway, auth scope, rol custom, ACL/denylist server-side | ATF con campos prohibidos |
| Replay | Delivery key única y binding a target/model, assessment, mapping y payload | Replay igual y alterado |
| Partial failure | Reconcile antes de retry; UNKNOWN fail-closed | Timeout después de commit/attachment |

## Errores y observabilidad

La taxonomía pública está en
[`SERVICENOW_ADAPTER_CONTRACT_V2.md`](SERVICENOW_ADAPTER_CONTRACT_V2.md). Logs y métricas
usan request ID, operation, target hash, outcome, error code, attempts y duración; nunca
number/sys_id completos si la política los clasifica como sensibles. La ausencia del
provider no convierte UNKNOWN/ERROR en éxito.

## Adopción y rollback

Seguir el [plan de migración v2](SERVICENOW_MIGRATION_V2.md) y el
[plan de pruebas](SERVICENOW_TEST_PLAN_V2.md). En un abort, deshabilitar write v2,
conservar evidencia y volver a v1 exclusivamente dry-run/read-only. No borrar ni mutar
automáticamente el Change para “deshacer” una evidencia ya auditada.

## Referencias oficiales

- [Change Management API](https://www.servicenow.com/docs/r/api-reference/rest-apis/change-management-api.html)
- [REST API Auth Scope](https://www.servicenow.com/docs/r/platform-security/authentication/rest-api-auth-scope.html)
- [Client credentials grant](https://www.servicenow.com/docs/r/platform-security/authentication/client-credential-grant.html)
- [Inbound REST rate limiting](https://www.servicenow.com/docs/r/api-reference/rest-api-explorer/inbound-REST-API-rate-limiting.html)
- [Certificate-based authentication](https://www.servicenow.com/docs/r/platform-security/authentication/certificate-api-auth.html)
