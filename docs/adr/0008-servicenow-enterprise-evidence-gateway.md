# ADR 0008: ServiceNow Enterprise Evidence Gateway

- Estado: aceptado para diseño; implementación condicionada a aprobación de política
- Fecha: 2026-09-03
- Alcance: etapa 09, sin llamadas de red

## Contexto

PreflightOps debe enriquecer ServiceNow como proveedor de evidencia pre-CAB sin asumir
autoridad sobre el Change. El conector v1 usa Table API con guards cliente. Ese camino es
válido para demo/piloto, pero no ofrece compare-and-set atómico ni restringe server-side
el API a los campos de evidencia.

ServiceNow documenta Change Management API como la interfaz orientada al proceso y
soporta creación desde un change model explícito. También indica que los endpoints de
update pueden modificar campos del Change, por lo que roles, ACL y auth scope siguen
siendo controles necesarios. Referencias:

- [Change Management API](https://www.servicenow.com/docs/r/api-reference/rest-apis/change-management-api.html)
- [REST API Auth Scope](https://www.servicenow.com/docs/r/platform-security/authentication/rest-api-auth-scope.html)
- [OAuth client credentials](https://www.servicenow.com/docs/r/platform-security/authentication/client-credential-grant.html)
- [Inbound REST API rate limiting](https://www.servicenow.com/docs/r/api-reference/rest-api-explorer/inbound-REST-API-rate-limiting.html)
- [Certificate-based inbound authentication](https://www.servicenow.com/docs/r/platform-security/authentication/certificate-api-auth.html)

## Alternativas

| Alternativa | Ventaja | Costo/riesgo | Decisión |
| --- | --- | --- | --- |
| Conservadora: Table API v1 enrich-only | Sin componente nuevo | Sin modelos, scope amplio y carrera cliente | Sólo rollback |
| Balanceada: Change Management API directa | Estándar versionado, model-aware | Update amplio y CAS no atómico | Sandbox/piloto |
| Enterprise: scoped Evidence Gateway | Allowlist, CAS e idempotencia server-side | Requiere despliegue y ownership en la instancia | Elegida para producción |

## Decisión

El golden path productivo usa un scoped Evidence Gateway instalado y gobernado por el
equipo ServiceNow. Sólo expone preview/capabilities, enrich-existing y create-draft.
Aplica allowlist, índice único de delivery, compare-and-set contra `sys_mod_count`,
auditoría y read-back antes de responder éxito. Usa la semántica del Change Management
API y deja Attachment API como canal acotado para el assessment completo.

Change Management API directa es un perfil de sandbox/piloto, siempre versionado y sin
live write si la instancia no atestigua CAS/idempotencia. Table API v1 permanece durante
migración como dry-run/read-only y no es ruta de creación v2.

## Invariantes

- `enrich_existing` es el default y requiere exactamente number o sys_id.
- `create_draft` requiere model sys_id allowlisted y autorización externa explícita.
- El cliente nunca escribe state, approval, assignment, schedule, closure, work notes,
  tasks ni ejecuta transiciones.
- Assessment status se almacena en un campo `u_preflightops_*`; no es el estado del CHG.
- Write, attachment y respuesta se correlacionan con una delivery key determinística.
- Un resultado no verificable es fallo parcial desconocido, nunca éxito.

## Consecuencias

La seguridad se refuerza incluso si el cliente es comprometido, y concurrencia/replay se
resuelven donde reside el dato. A cambio, cada cliente debe aprobar y operar el gateway,
un campo único `u_preflightops_delivery_id`, ACL, scope OAuth y change models permitidos.

## Gate de política

Antes de la etapa 10 se requiere decisión humana sobre dos puntos:

1. hacer gateway + delivery field único obligatorios para cualquier live write de
   producción; y
2. implementar `create_draft` como capability desactivada por defecto o excluirla del
   primer release v2.

## Rollback

Deshabilitar live v2, conservar sus resultados auditables y volver a v1 sólo en
dry-run/read-only. No se elimina ningún CHG ni attachment como rollback automático.
