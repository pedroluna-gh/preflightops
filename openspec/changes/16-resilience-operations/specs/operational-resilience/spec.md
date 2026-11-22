## ADDED Requirements

### Requirement: Telemetría local sin contenido sensible
El producto SHALL emitir telemetría opt-in `operations-v1` con correlación opaca,
duración, controles, errores, caché, retries, verdicts y degradación. Las etiquetas
SHALL pertenecer a conjuntos fijos; los eventos SHALL estar acotados a 256.

#### Scenario: Diagnóstico positivo
- **WHEN** un assessment válido finaliza con telemetría solicitada
- **THEN** se escribe un documento local nuevo con métricas y correlación sin modificar el reporte

#### Scenario: Payload adversarial
- **WHEN** inputs o excepciones contienen secretos, URLs o nombres privados
- **THEN** no aparecen en eventos ni etiquetas; sólo se expone una taxonomía estática

#### Scenario: Destino ocupado
- **WHEN** el archivo de telemetría ya existe o no se puede escribir
- **THEN** no se sobrescribe y el CLI devuelve código 2

### Requirement: Operación acotada y compatible
El CLI SHALL preservar códigos legacy 0/1/2, limitar bytes antes del parseo y rechazar
estructuras que exceden el presupuesto. ERROR/UNKNOWN MUST NOT convertirse en PASS.

#### Scenario: Entrada excesiva
- **WHEN** un archivo excede su límite o YAML contiene un ciclo/estructura excesiva
- **THEN** la operación falla de forma explícita con código 2 sin aprobar el cambio

#### Scenario: Replay
- **WHEN** se repiten los mismos inputs y contexto con telemetría activada/desactivada
- **THEN** los bytes de evidencia y el resultado de riesgo permanecen iguales

### Requirement: SLO medibles y recuperación realista
La entrega SHALL incluir sonda offline con percentiles, throughput, memoria Python,
invariantes de seguridad y presupuesto de errores, además de runbooks ejecutables.
La documentación MUST distinguir objetivos internos de un SLA o HA de servicio.

#### Scenario: Sonda operacional
- **WHEN** el operador ejecuta la sonda sobre fixtures sintéticas
- **THEN** obtiene mediciones y salida no cero si se incumple un objetivo o invariante

#### Scenario: Recuperación
- **WHEN** se pierde un proceso o un artefacto local
- **THEN** el runbook permite reinstalar una versión verificada y recalcular sólo con inputs/contexto conservados
