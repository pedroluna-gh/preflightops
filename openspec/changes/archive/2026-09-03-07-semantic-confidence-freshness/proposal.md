# Cambio 07: validación semántica, confidence y freshness

## Why

Los validadores v1 históricos comprueban presencia, longitud o cantidad de campos,
pero una cadena larga, `todo`, una lista vacía semánticamente o una referencia
declarada rota todavía pueden parecer completas. El Assessment Contract v1 separa
risk y confidence, pero necesita observaciones semánticas reproducibles que distingan
fallo, ausencia de evidencia, error técnico, expiración y no aplicabilidad.

## What Changes

- Se añade un contrato estructurado y estricto para planes de rollback, monitoreo y
  validación, con acción, trigger, owner, duración, éxito, referencias y pasos
  observables según corresponda.
- Se implementa un evaluador puro y offline con estados `PASS`, `FAIL`, `UNKNOWN`,
  `ERROR` y `NOT_APPLICABLE`.
- Se calcula confidence de forma explicable a partir de determinabilidad, freshness y
  provenance, con caps no lineales que impiden certeza falsa.
- Se exige tiempo de evaluación explícito y se aplican expiración declarada y TTL
  máximo de policy; la evidencia futura o inválida produce `ERROR`.
- Se generan IDs, hashes y JSON canónico determinísticos sin incluir el contenido de
  los planes.
- Se conserva la API legacy y se añade un adaptador explícito que no inventa campos ni
  transforma evidencia ambigua en `PASS`.

## Scope

Incluye exclusivamente validación semántica local de planes suministrados y metadatos
de evidencia. No consulta dashboards, alertas, proveedores, URLs, ServiceNow, Jira,
clusters ni modelos remotos; no cambia scores de riesgo, recomendaciones técnicas o
decisiones humanas.

## Compatibility

Los validadores v1 y los outputs existentes permanecen sin cambios. El contrato nuevo
es aditivo y versionado. El adaptador de Change Request v1 etiqueta su origen y aplica
el mismo fallo cerrado; los consumidores pueden migrar control por control.

## Privacy

El resultado conserva únicamente identificadores acotados, timestamps, digests
SHA-256 aprobados y códigos de issue. Nunca serializa acciones, triggers, criterios,
pasos, nombres libres, payloads de proveedores ni contenido sensible completo.

## Rollback

Dejar de invocar la API semántica y fijar la versión anterior restaura el flujo previo.
No existe estado persistente ni llamada externa que revertir. Los resultados ya
emitidos se conservan como evidencia histórica y no se reinterpretan.

## Outcome

Implementado y verificado en el PR #44 con 15/15 checks exitosos antes de archivar.
