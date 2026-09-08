# Diseño: runtime ServiceNow enterprise v2

## Opciones evaluadas

| Diseño | Beneficio | Desventaja | Decisión |
| --- | --- | --- | --- |
| Conservador: endurecer Table API v1 | Cambio mínimo | Conserva creación implícita y CAS cliente | Sólo rollback |
| Balanceado: Change API directa | Menos componentes | Superficie de escritura amplia y TOCTOU | Read-only/sandbox |
| Enterprise: adapter aditivo + gateway | Allowlist/CAS/unicidad server-side | Requiere gateway por instancia | Elegido |

## Arquitectura

`build_servicenow_plan_v2` valida el Assessment Report v1, mapping, origen, evidencia y
policy antes de producir IDs/digests canónicos. No recibe ni consulta secretos.

`ServiceNowEnterpriseAdapter` recibe explícitamente transporte, credential provider,
network policy, clock, monotonic clock, sleep y event sink. Dry-run no utiliza ninguna de
esas dependencias externas. Read-only usa Change Management API únicamente para lookup.
Live write fija el target, valida capability y delega la transacción al gateway.

## Identidad

Mapping y payload se serializan con canonical JSON. Delivery key liga versión,
operación, alias, target/model, assessment/report, mapping y payload. Request ID liga
delivery key, dry-run y versión esperada. Timestamps vienen del report o reloj inyectado,
nunca de datos ambientales durante preview.

## Seguridad

- Origins y evidence links son HTTPS exactos, sin userinfo, query, fragment ni puertos
  no estándar; hosts e IPs se validan contra policy explícita.
- Resolución se valida antes de adquirir token y antes de cada request protegida.
- Redirects 301/302/303/307/308 se rechazan como resultado terminal.
- OAuth client credentials es el único auth v2 concreto. Basic permanece legacy v1.
- Errores y eventos contienen IDs/digests, nunca headers, body remoto, token o target
  completo.

## Write path

1. Revalidar integridad del plan y confirmación.
2. Resolver CHG exacto por Change API y fijar number/sys_id/sys_mod_count.
3. Fallar cerrado ante identidad o CAS distinto.
4. Verificar capability digest, mapping digest, unicidad y operación allowlisted.
5. POST al gateway con idempotency header y payload acotado.
6. Reconciliar/read-back siempre y verificar target, digests y mapped fields.

`create_draft` requiere mapping habilitado, feature flag runtime, model allowlisted,
autorización externa y capability remota. No envía workflow fields.

## Retries y partial failure

GET puede reintentarse dentro de intentos/tiempo. 429 respeta `Retry-After`. Después de
timeout/502/503/504 de un write, el adapter reconcilia primero. Sólo reintenta cuando el
gateway prueba que la delivery key no fue aplicada; de otro modo devuelve
`PARTIAL_FAILURE_UNKNOWN` o el resultado reconciliado.

## Compatibilidad y rollback

V1 no importa ni invoca v2. Un helper de dual preview compara identidades y campos sin
red. Rollback desactiva live v2; no borra evidencia ni intenta revertir Changes.
