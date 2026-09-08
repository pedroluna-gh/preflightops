# evidence-provider-contract Specification

## Purpose

Normalizar evidencia operacional read-only sin dependencia del proveedor en el motor.

## ADDED Requirements

### Requirement: Contrato estricto y reproducible
El contrato SHALL incluir provider/version, control_id, status, summary, source/reference,
collected_at, valid_until, confidence, error taxonomy, raw_evidence_reference y redacción.
La serialización SHALL ser canónica y rechazar campos desconocidos y valores inválidos.

#### Scenario: Orden de resultados
- **WHEN** los mismos resultados llegan en distinto orden
- **THEN** el agregado y su digest son idénticos

### Requirement: Fallos explícitos
El runtime MUST preservar ERROR/UNKNOWN y MUST NOT convertirlos en PASS.
NOT_APPLICABLE SHALL requerir justificación. Ausencias SHALL producir UNKNOWN.

#### Scenario: Fallo parcial
- **WHEN** un proveedor falla y otro entrega evidencia válida
- **THEN** se conserva la evidencia válida y el fallo queda explícito en el agregado

### Requirement: Freshness y caché
El runtime SHALL validar timestamps contra un instante explícito y SHALL rechazar
reutilización de evidencia vencida o de otro contexto en una caché acotada.

#### Scenario: Expiración
- **WHEN** el instante de evaluación alcanza valid_until
- **THEN** un PASS previo no produce un control aprobado

### Requirement: Lifecycle controlado
Providers SHALL declarar capabilities read-only, recibir credenciales inyectadas y
respetar cancelación cooperativa y deadlines; respuestas tardías MUST fallar cerrado.

#### Scenario: Cancelación previa
- **WHEN** una solicitud está cancelada antes de iniciar
- **THEN** no se consultan credenciales ni se invoca la recolección

### Requirement: Privacidad y desacoplamiento
El motor SHALL consumir el contrato común sin importar SDKs de proveedores.
Credenciales y contenido remoto completo MUST NOT aparecer en resultados o caché.

#### Scenario: Excepción sensible
- **WHEN** el adapter lanza una excepción con un secreto
- **THEN** sólo se expone una categoría de error y un mensaje estático
