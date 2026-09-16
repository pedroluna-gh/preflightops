## ADDED Requirements

### Requirement: Simulation authenticates active policies without activating drafts

PreflightOps SHALL aceptar claves públicas independientes para las políticas
base y candidata de una simulación offline y SHALL conservar separada la
decisión humana.

#### Scenario: Active base and draft candidate

- **WHEN** una base activa tiene firma válida bajo la clave confiable explícita
  y la candidata es un borrador válido
- **THEN** la simulación produce digests y diferencias sin activar la candidata
  y con automatic_approval false

#### Scenario: Invalid signature

- **WHEN** una política activa fue alterada o no corresponde a la clave fijada
- **THEN** la simulación falla sin escribir un resultado exitoso

### Requirement: Explicit failure handling preserves evidence truth

PreflightOps SHALL distinguir fallo de gobierno de evidencia no disponible.
Fallos de firma, política o contexto SHALL cerrar la evaluación; fail-open
SHALL significar sólo continuación informativa y nunca aprobación.

#### Scenario: Unavailable evidence

- **WHEN** una política permite fail-open para evidencia no disponible
- **THEN** el registro conserva la incertidumbre y la decisión humana externa

### Requirement: Historical governance is reproducible and reversible

PreflightOps SHALL conservar versión, digest, contexto e instante de evaluación
para reproducir políticas y expiración de waivers sin modificar historia.

#### Scenario: Expired waiver

- **WHEN** el instante explícito coincide o supera la expiración del waiver
- **THEN** el waiver no es válido aunque exista una firma correcta

#### Scenario: Rollback

- **WHEN** se vuelve al bundle previamente aprobado y su contexto original
- **THEN** se reproduce el resultado original sin alterar la evaluación candidata

### Requirement: Governance inputs are unambiguous

PreflightOps SHALL rechazar entradas ambiguas, estructuras inválidas y firmas
incorrectas sin revelar claves o contenido sensible en los errores.

#### Scenario: Duplicate document keys

- **WHEN** un documento contiene claves duplicadas con valores distintos
- **THEN** la carga falla antes de su utilización como política o waiver
