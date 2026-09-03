# semantic-evidence-validation Specification

## Purpose

Definir cómo PreflightOps valida offline la suficiencia semántica, provenance y
vigencia de planes de rollback, monitoreo y validación sin inventar evidencia ni
mezclar confidence con risk o decisión humana.

## ADDED Requirements

### Requirement: Contratos estructurados y mínimos semánticos

El sistema SHALL aceptar un contrato versionado para los tres planes y MUST exigir los
campos aplicables de acción, trigger, owner, duración, success criteria, referencias y
pasos observables. MUST NOT considerar suficientes longitud, presencia o texto libre.

#### Scenario: Plan completo
- **WHEN** los tres planes incluyen todos sus campos estructurados y evidencia válida
- **THEN** cada control aplicable obtiene PASS

#### Scenario: Placeholder largo
- **WHEN** un campo contiene `todo`, gibberish allowlisted o repetición sin semántica
- **THEN** el control obtiene FAIL con field y code estables

#### Scenario: Lista vacía
- **WHEN** pasos, dashboards, alerts o success criteria requeridos están vacíos
- **THEN** el control obtiene FAIL y nunca PASS por presencia del contenedor

### Requirement: Estados explícitos y fail-closed

Cada control SHALL concluir `PASS`, `FAIL`, `UNKNOWN`, `ERROR` o
`NOT_APPLICABLE`. ERROR y UNKNOWN MUST NOT convertirse en PASS. NOT_APPLICABLE MUST
requerir exclusión explícita, razón semántica y evidencia vigente.

#### Scenario: Provider ausente
- **WHEN** no existe provider de evidencia para un control
- **THEN** el estado es UNKNOWN aunque el plan parezca completo

#### Scenario: Parser error
- **WHEN** el producer declara error de parsing
- **THEN** el estado es ERROR con confidence acotado

#### Scenario: No aplicabilidad sin razón
- **WHEN** applicable es false y falta una razón válida
- **THEN** el estado es FAIL, no NOT_APPLICABLE

### Requirement: Confidence independiente y explicable

El sistema SHALL calcular confidence sólo desde determinability, freshness y
provenance. SHALL publicar componentes, fórmula, cap y nivel. MUST NOT derivarlo de
risk, recomendación o decisión humana.

#### Scenario: Falla demostrada con alta confianza
- **WHEN** un defecto semántico se observa en evidencia fresca y digest-pinned
- **THEN** el control puede ser FAIL con confidence HIGH

#### Scenario: Incertidumbre
- **WHEN** el estado es UNKNOWN
- **THEN** el cap impide confidence HIGH aunque otros componentes sumen más

### Requirement: Freshness y expiración determinísticas

El sistema SHALL usar únicamente timestamps explícitos y el TTL máximo versionado.
MUST usar la expiración más temprana y MUST clasificar timestamps futuros o intervalos
invertidos como ERROR.

#### Scenario: Evidencia expirada
- **WHEN** evaluated_at supera la expiración efectiva de evidencia PASS
- **THEN** freshness es STALE y el estado final es UNKNOWN

#### Scenario: Mismo input y contexto
- **WHEN** se repite la evaluación con bytes semánticos y timestamps iguales
- **THEN** output, ID e integrity hash son byte-a-byte idénticos

### Requirement: Referencias offline y contradicciones declaradas

El sistema SHALL validar forma y estado declarado de dashboard/alert references sin
acceso de red. Una referencia BROKEN o URL inválida MUST fallar; una referencia UNKNOWN
MUST impedir PASS. Contradicciones declaradas MUST producir FAIL.

#### Scenario: URL declarada rota
- **WHEN** un dashboard tiene state BROKEN
- **THEN** monitoring obtiene FAIL sin intentar resolver la URL

#### Scenario: Información contradictoria
- **WHEN** contradictions contiene al menos un elemento
- **THEN** el control obtiene FAIL y el contenido de la contradicción no se copia

### Requirement: Privacidad, integridad y compatibilidad

El output MUST contener sólo metadatos allowlisted, issues y digests; MUST NOT copiar
planes o contenido sensible. Los validadores y outputs legacy SHALL preservarse. El
adaptador legacy MUST NOT inventar campos ni elevar evidencia ambigua a PASS.

#### Scenario: Marcador sensible
- **WHEN** un plan contiene un valor arbitrario o marcador secreto
- **THEN** el valor no aparece en el output serializado ni en errores

#### Scenario: Change Request v1
- **WHEN** se usa el adaptador legacy
- **THEN** el source contract queda identificado y las APIs legacy siguen disponibles

#### Scenario: Tamper
- **WHEN** se modifica status, score, issue o metadata después de generar el output
- **THEN** la validación estricta rechaza el integrity hash

#### Scenario: ERROR o UNKNOWN reseñado
- **WHEN** un producer reporta ERROR o UNKNOWN y el contrato se vuelve a sellar
- **THEN** las invariantes cruzadas impiden elevarlo a PASS
