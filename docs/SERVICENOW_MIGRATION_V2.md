# Migración ServiceNow v1 a v2

## Principios

La migración es aditiva, dry-run-first y enrich-only-first. No existe fallback silencioso,
reescritura de evidencia histórica ni creación automática de Changes. V1 permanece
disponible durante la ventana acordada, pero sus live writes se deshabilitan antes de
habilitar producción v2.

## Fase 0 — inventario y decisión

- Identificar release/plugins, Change models, dominios, Business Rules, ACL, rate limits,
  proxy/mTLS y retención.
- Inventariar cada mapping v1 y clasificar destinos/choices.
- Aprobar owner de gateway, Application User, auth scope, field ACL, índice único y
  soporte 24x7.
- Decidir política `create_draft`: capability off por defecto o fuera del primer release.

Gate: ADR/política aprobados; ningún cambio runtime.

## Fase 1 — preparar instancia sandbox

- Instalar Evidence Gateway v1 y campo `u_preflightops_delivery_id` con unicidad.
- Configurar rol custom, ACL, OAuth scope, rate limit y audit history.
- Allowlist de model sys_ids vacía inicialmente.
- Publicar capability attestation digest y mapping v2 firmado/aprobado.

Gate: ATF denylist y CAS/uniqueness verdes.

## Fase 2 — dual preview offline

- Para fixtures aprobadas, generar payload v1 y plan v2 sin token/red.
- Comparar semántica, truncación, risk/confidence, UNKNOWN/ERROR, IDs y attachments.
- Aceptar diferencias deliberadas: v2 no crea implícitamente, no escribe standard risk
  sin choice mapping y no usa timestamp/volatile data en idempotencia.

Gate: 100% de campos v2 explicados y cero campo privilegiado.

## Fase 3 — sandbox enrich-existing

- Ejecutar Changes dedicados por number y sys_id.
- Probar unchanged, concurrency conflict, replay mismatch, rate limit, timeout-after-write
  y partial attachment failure.
- Verificar read-back, audit history y ausencia de transición/workflow side effects.

Gate: contract + ATF + E2E y resilience verdes.

## Fase 4 — canary productivo

- Sólo enrich-existing, un servicio no crítico, Change previamente aprobado para recibir
  evidencia, mapping/capability digests fijados y rollback owner disponible.
- `create_draft=false`; una ejecución a la vez; budgets conservadores.
- Métricas: outcome, error code, conflict/replay, latency, 429 y verification mismatch.

Abort inmediato ante wrong-record, campo no allowlisted, digest mismatch, secret canary,
partial failure unknown, error rate >1% o latencia p95 fuera del SLO acordado.

## Fase 5 — expansión y draft opcional

Expandir por cohortes sólo después de ventana estable y revisión CAB/ServiceNow. Draft
requiere decisión de política independiente, model sys_ids explícitos, quota, ownership y
pruebas de duplicación. Nunca se habilita por mera presencia de credenciales.

## Compatibilidad y datos

- Mapping/evidence v1 no se cambia ni se convierte in-place.
- Delivery v2 usa nuevo namespace/key; referencias v1 se conservan para auditoría.
- Assessment/report se versionan y sus hashes no se recalculan con reglas v2.
- Dashboards distinguen v1, v2 dry-run, v2 enrich y v2 create-draft.

## Rollback

1. Poner `write_enabled=false` y revocar token/cert del Application User.
2. Deshabilitar gateway write manteniendo capability/read audit.
3. Detener retries y reconciliar delivery keys con write state UNKNOWN.
4. Conservar CHG/attachments y registrar corrección humana si corresponde; no borrar.
5. Volver a v1 sólo para dry-run/read-only mientras se resuelve la causa.
6. Reabrir canary únicamente con nuevo mapping/capability digest y aprobación.

El último estado conocido bueno es el conector v1 en dry-run/enrich-only de sandbox. La
autoridad del Change nunca sale de ServiceNow durante migración o rollback.
