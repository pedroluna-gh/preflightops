# ServiceNow adapter contract v2

## Estado

Contrato implementado por la API Python pública de la etapa 10. Su construcción y
validación de planes es offline; el runtime sólo autoriza llamadas cuando un caller
inyecta explícitamente policy, transporte, credenciales y confirmación. CLI, Action y web
conservan v1 y no activan v2 implícitamente.

## Separación de capas

El adapter v2 tiene cuatro operaciones conceptuales:

```text
validate(request, mapping) -> validated request
preview(validated request, assessment report) -> canonical plan
execute(canonical plan, secret provider, transport) -> adapter result
reconcile(request id, idempotency key, expected digests) -> adapter result
```

`validate` y `preview` son puros y offline. `execute` y `reconcile` viven en una capa de
transporte opt-in, reciben dependencias explícitas y no importan el Trust Kernel. Ningún
secret provider participa antes de que preview, policy y write authorization sean
válidos.

## Request v2

[`servicenow-adapter-request-v2.schema.json`](../schemas/servicenow-adapter-request-v2.schema.json)
es estricto. Campos principales:

| Campo | Semántica |
| --- | --- |
| `request_id` | ID determinístico content-free |
| `operation` | `enrich_existing` o `create_draft` |
| `dry_run` / `write_enabled` | Defaults seguros; write exige gateway |
| `transport_profile` | `evidence_gateway_v1` o sandbox `change_management_v1` |
| `instance` | Alias y origin HTTPS sin credenciales |
| `target` | Exactamente number o sys_id para enrich |
| `creation` | Model sys_id y autorización externa para draft |
| `assessment` | IDs, digest, verdict, risk, confidence, policy, commit y timestamp |
| `delivery` | Mapping/digest, delivery key, payload digest y canal de evidencia |
| `preconditions` | Capability digest y `expected_sys_mod_count` para enrich |

No contiene token, client secret, certificate key, proxy credentials, raw assessment ni
payload remoto. `write_enabled=true` implica `dry_run=false` y Evidence Gateway.

[`servicenow-adapter-plan-v2.schema.json`](../schemas/servicenow-adapter-plan-v2.schema.json)
envuelve request, mapping, campos y evidencia y permite verificar de nuevo todas las
identidades antes de adquirir credenciales. El digest de report es el valor SHA-256 de
integridad definido por Assessment Report v1 y ligado por su `report_id`.

## Mapping v2

[`servicenow-mapping-v2.schema.json`](../schemas/servicenow-mapping-v2.schema.json)
exige las once semánticas operativas y sólo permite destinos de evidencia. El adapter
MUST comprobar además que cada semantic key usa su source esperado; la validación de
choices para `risk`/`impact` es específica de instancia.

El mapping canónico completo se hashea antes de construir el request. No se aceptan
includes, variables de entorno, templates ejecutables, aliases YAML recursivos ni rutas
remotas.

## Result v2

[`servicenow-adapter-result-v2.schema.json`](../schemas/servicenow-adapter-result-v2.schema.json)
distingue:

- `DRY_RUN` y `READ_ONLY`: cero write;
- `UNCHANGED`: replay idéntico verificado;
- `UPDATED` y `CREATED_DRAFT`: write y read-back verificados;
- `CONFLICT`, `FAILED` y `PARTIAL_FAILURE_UNKNOWN`: no éxito.

Sólo `UNCHANGED`, `UPDATED` y `CREATED_DRAFT` requieren `verified=true`. Un result no
incluye response body, token, headers, attachment contents ni texto remoto completo.

## Error taxonomy

| Código | Retryable | Write state esperado | Significado |
| --- | ---: | --- | --- |
| `UNTRUSTED_DESTINATION` | no | NOT_ATTEMPTED | Origin/proxy/evidence URL no permitido |
| `REDIRECT_REJECTED` | no | NOT_ATTEMPTED | Redirect rechazado sin reenviar credenciales |
| `INVALID_MAPPING` | no | NOT_ATTEMPTED | Schema/source/destination/choice inválido |
| `CAPABILITY_MISSING` | no | NOT_ATTEMPTED | Gateway/CAS/unicidad no atestiguados |
| `MODEL_NOT_ALLOWED` | no | NOT_ATTEMPTED | Draft model fuera de allowlist |
| `TARGET_NOT_FOUND` | no | NOT_APPLIED | CHG inexistente |
| `TARGET_AMBIGUOUS` | no | NOT_APPLIED | Lookup no identifica uno solo |
| `AUTHENTICATION_FAILED` | no | NOT_ATTEMPTED | Token/cert inválido o ausente |
| `AUTHORIZATION_DENIED` | no | NOT_APPLIED | Scope, ACL o policy rechaza operación |
| `CONCURRENCY_CONFLICT` | no | NOT_APPLIED | `sys_mod_count` no coincide |
| `REPLAY_MISMATCH` | no | NOT_APPLIED | Delivery key existente con otro digest |
| `RATE_LIMITED` | condicional | NOT_APPLIED | 429; `Retry-After` excede budget o agotó intentos |
| `TIMEOUT` | condicional | NOT_APPLIED/UNKNOWN | Timeout antes o después de posible write |
| `RESPONSE_INVALID` | no | UNKNOWN | Response no cumple contrato |
| `VERIFICATION_MISMATCH` | no | APPLIED/UNKNOWN | Read-back difiere del plan |
| `PARTIAL_FAILURE_UNKNOWN` | no | UNKNOWN | No se puede probar si el write quedó aplicado |

La excepción interna puede conservar causa técnica en memoria, pero el result/log sólo
expone código, retryability, write state y un mensaje redactado de máximo 320 caracteres.

## State machine

```text
RECEIVED -> VALIDATED -> PREVIEWED
PREVIEWED -> DRY_RUN | READ_ONLY
PREVIEWED -> AUTHORIZED -> CAPABILITY_VERIFIED -> TARGET_PINNED
TARGET_PINNED -> UNCHANGED | APPLIED -> VERIFIED
any pre-write state -> FAILED | CONFLICT
APPLIED -> VERIFIED | PARTIAL_FAILURE_UNKNOWN
```

No existe transición desde FAILED/CONFLICT/UNKNOWN hacia éxito sin una nueva request con
nuevo `request_id` y reconciliation explícita.

## Idempotencia y CAS

Las fórmulas normativas están en el golden path. El gateway MUST hacer atómicamente:

1. verificar target/model, delivery key y mapping/capability digest;
2. comparar `expected_sys_mod_count` para enrich;
3. reservar la delivery key única;
4. escribir sólo allowlist;
5. guardar payload/attachment digest y audit metadata;
6. devolver identidad y nuevo `sys_mod_count`.

Ante colisión de key, comparar digest: igual → `UNCHANGED`; distinto →
`REPLAY_MISMATCH`. El adapter siempre realiza read-back con number, sys_id, delivery key,
digests y campos escritos.

## Compatibilidad

V1 permanece sin cambios. No hay conversión implícita v1→v2 ni fallback silencioso de
gateway a Table API. Un caller elige el contrato y recibe error si la capability no está
disponible.

## API pública

- `build_servicenow_plan_v2`: preview determinística, credential-free y offline.
- `validate_servicenow_plan_v2`: recomputa mapping, payload, report, delivery y request.
- `ServiceNowEnterpriseAdapter.execute`: dry-run, read-only o write confirmado.
- `NetworkPolicy` y `UrllibTransport`: policy exacta de URL/DNS y transporte no-redirect.
- `OAuthClientCredentialsProvider`: token corto mediante dependencias inyectadas.
- `compare_servicenow_previews_v1_v2`: dual preview sin fallback ni write.

Consulte el [runbook](SERVICENOW_ENTERPRISE_RUNBOOK.md) y el procedimiento de
[sandbox](SERVICENOW_SANDBOX_VALIDATION.md).
