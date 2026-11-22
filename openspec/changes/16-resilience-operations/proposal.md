## Why

La etapa 15 y el mantenimiento de seguridad están fusionados con CI verde (#52,
#53 y #54). Falta demostrar operación reproducible, diagnóstico sin datos sensibles
y degradación segura bajo fallos y concurrencia. Esta propuesta cubre sólo la etapa 16.

## What Changes

- Telemetría local opt-in con contrato versionado, identificador opaco de correlación,
  métricas de cardinalidad fija y eventos acotados. No modifica hashes de evidencia.
- Presupuesto de espera del runner, instrumentación de caché y fallos, sin retries nuevos.
- Lectura acotada de entradas CLI y descubrimiento local, con errores sanitizados.
- Pruebas de fallos/carga y una sonda offline ejecutable con SLI/SLO medidos.
- Runbook de operación, retención, recuperación y rollback acorde a CLI/biblioteca.

## Capabilities

### New Capabilities
- `operational-resilience`: diagnóstico local, límites, SLO y recuperación verificables.

### Modified Capabilities
- `evidence-provider-contract`: el deadline incluye la espera por el runner ocupado.

## Impact

Se preservan outputs legacy, códigos 0/1/2 y contratos de assessment. Inputs que
exceden límites explícitos se rechazan. La telemetría requiere un destino local nuevo;
no habilita red ni sinks. No se agrega un servicio, HA, aprobación humana ni etapa 17.
Rollback: retirar opt-in y revertir la implementación en un PR verificado, conservando
artefactos previos y las dependencias de seguridad. Comparación de diseños en design.md.
