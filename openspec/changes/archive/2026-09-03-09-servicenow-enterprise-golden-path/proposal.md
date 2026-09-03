# Cambio 09: diseño enterprise de ServiceNow

## Why

El conector ServiceNow v1 demuestra publicación opt-in y enriquecimiento seguro en una
instancia de prueba, pero su Table API permite creación implícita, la concurrencia se
comprueba sólo desde el cliente y la identidad técnica puede recibir permisos más
amplios que el perfil de evidencia pre-CAB. Se necesita un golden path enterprise antes
de endurecer la implementación.

## What Changes

- Se define un contrato v2 independiente del transporte para preview, enriquecimiento
  de un CHG existente y creación opcional de un draft desde un change model permitido.
- Se selecciona un Evidence Gateway acotado en ServiceNow para producción, con
  allowlist server-side, idempotencia única y compare-and-set atómico.
- Se selecciona Change Management API versionada para sandbox/piloto y para semántica
  de modelos; Table API queda sólo como compatibilidad legacy durante migración.
- Se especifican mapping semántico, autenticación, proxy/mTLS, retries, rate limits,
  attachments, error taxonomy, threat model, test plan, migración y rollback.
- Se añaden schemas y ejemplos de diseño validables, sin implementar transporte ni
  realizar llamadas de red.

## Scope

Incluye exclusivamente contratos y documentación de arquitectura. No cambia el runtime,
no adquiere tokens, no abre sockets, no instala componentes en ServiceNow y no escribe en
una instancia real.

## Compatibility

El conector, CLI, Action, mapping v1, evidence v1 y outputs actuales permanecen intactos.
Los contratos v2 se marcan como target de diseño para la etapa 10 y no habilitan live
writes por sí mismos.

## Privacy

Los ejemplos sólo usan identificadores ficticios, hashes y metadatos allowlisted. El
contrato prohíbe secretos, tokens, payloads raw, evidencia sensible completa y URLs con
credenciales.

## Rollback

Retirar los artefactos v2 de diseño devuelve la documentación al baseline v1 sin cambiar
ninguna ejecución. Durante una futura migración, desactivar el perfil v2 y conservar v1
en dry-run/read-only restaura el camino previo.
