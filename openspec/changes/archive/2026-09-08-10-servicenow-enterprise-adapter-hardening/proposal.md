# Cambio 10: adapter ServiceNow enterprise endurecido

## Why

La etapa 09 definió contratos y límites de autoridad, pero PreflightOps aún no dispone de
un runtime v2 que demuestre idempotencia, optimistic concurrency, URL hardening, OAuth,
retries seguros y recuperación fail-closed. El conector v1 debe permanecer compatible
mientras se añade el camino enterprise.

## What Changes

- Se implementa un adapter v2 aditivo con preview determinística y offline.
- Se añade un cliente Change Management API read-only y un cliente Evidence Gateway
  con transporte y credenciales inyectados.
- Todo live write productivo exige gateway, delivery key única, capability attestation,
  confirmación explícita y CAS por `sys_mod_count`.
- `create_draft` se implementa detrás de dos gates y permanece desactivado por defecto.
- Se implementan OAuth client credentials, URL/DNS policy, redirect refusal, timeouts,
  retries/reconciliation y auditoría redactada.
- Se publican contrato de plan, tests unitarios/integration-mock/contract y runbooks
  separados de sandbox y rollback.

## Scope

No se contacta ninguna instancia ServiceNow. Las pruebas usan transportes, resolvers,
relojes y sleeps falsos. No se despliega el gateway ni se ejecuta ATF/E2E real.

## Compatibility

El módulo, CLI y outputs ServiceNow v1 no se eliminan ni cambian de semántica. V2 usa
otro módulo, otros contratos e IDs; no existe fallback silencioso de gateway a Table API.

## Approved policy

El owner aprobó que todo live write productivo requiera Evidence Gateway y
`u_preflightops_delivery_id` único. También aprobó implementar `create_draft` compilado
pero desactivado por defecto.

## Rollback

Deshabilitar `write_enabled`, revocar la credencial del Application User y retirar el
módulo/contratos v2. V1 queda disponible sólo en dry-run/read-only durante investigación.
