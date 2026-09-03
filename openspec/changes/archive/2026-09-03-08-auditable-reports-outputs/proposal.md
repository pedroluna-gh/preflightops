# Cambio 08: reportes auditables y outputs

## Why

Assessment Contract v1 ya separa risk, confidence, recomendación técnica y decisión
humana, pero los reportes históricos consumen `risk-report-v1`. Un reviewer necesita
una proyección segura y escaneable del contrato nuevo sin reinterpretar estados, copiar
evidencia sensible ni depender de servicios externos.

## What Changes

- Se añade `assessment-report-v1`, un contrato JSON estricto, canónico e íntegro que
  referencia la identidad y hashes del Assessment Contract sin copiar evidencia raw.
- Se añaden renderizadores determinísticos para informe Markdown, resumen PR y resumen
  ticket, todos con límites y redacción defensiva.
- Se presenta primero recomendación técnica, risk, confidence, decisión humana,
  blockers, UNKNOWN/ERROR, freshness, provenance y next actions.
- Se añade un bloque Automation Details breve y configurable, derivado exclusivamente
  del contexto ya aprobado del Assessment Contract.
- Se añade un subcomando offline opt-in con rutas de output explícitas; no realiza
  llamadas de red ni sobrescribe los reportes legacy.

## Scope

Incluye exclusivamente transformación y renderizado local de Assessment Contract v1.
No crea assessments, no publica comentarios, no carga artifacts, no escribe tickets y
no llama GitHub, ServiceNow, Jira, providers ni otras APIs.

## Compatibility

Los generadores Markdown/JSON/HTML/GitHub/ticket históricos permanecen disponibles y
sin cambios. La API y el subcomando nuevos son aditivos. Ningún archivo se escribe sin
una ruta explícita del caller.

## Privacy

El output sólo contiene metadatos allowlisted, hashes aprobados, códigos, estados y
texto acotado después de redacción. No copia payloads, valores de evidencia, secretos,
credenciales en URLs ni contenido sensible completo.

## Rollback

Dejar de llamar la API nueva o el subcomando `report render` restaura el flujo previo.
No existe estado persistente o remoto que reparar; los outputs versionados ya emitidos
se conservan como evidencia histórica.
