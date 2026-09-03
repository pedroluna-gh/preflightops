# auditable-assessment-reporting Specification

## Purpose

Definir cómo PreflightOps transforma Assessment Contract v1 en outputs offline,
determinísticos, auditables y escaneables sin alterar contratos legacy ni límites de
autoridad humana.

## Requirements

### Requirement: JSON canónico, completo y versionado

El sistema SHALL producir un `assessment-report-v1` estricto con audit metadata,
decisión, scores, todos los controles clasificados, provenance permitida, next actions,
configuración e integrity. MUST derivar ID y hash de bytes canónicos estables.

#### Scenario: Mismo assessment y configuración
- **WHEN** se renderiza dos veces el mismo Assessment Contract y configuración
- **THEN** JSON, report ID e integrity son byte-a-byte idénticos

#### Scenario: Tamper
- **WHEN** se modifica decisión, score, control, provenance o configuración
- **THEN** la validación rechaza el integrity hash o una invariante cruzada

### Requirement: Revisión humana escaneable

El informe Markdown SHALL presentar primero recomendación técnica, risk, confidence,
verdict y decisión humana, seguido de top blockers, passed controls, UNKNOWN/ERROR,
freshness, provenance y next actions. MUST indicar que la recomendación no concede
aprobación.

#### Scenario: Assessment mixto
- **WHEN** existen controles PASS, FAIL, UNKNOWN y ERROR
- **THEN** cada categoría se muestra explícitamente y ERROR/UNKNOWN nunca aparece PASS

#### Scenario: Decisión humana no registrada
- **WHEN** `human_decision.status` es `NOT_RECORDED`
- **THEN** el informe indica autoridad externa y no afirma aprobación

### Requirement: Resúmenes PR y ticket acotados

El sistema SHALL generar un resumen PR compacto y un resumen ticket con budgets
configurables. El resumen PR MUST enlazar el reporte completo sólo cuando el caller
provee una URL HTTPS segura y MUST conservar decisión, blockers y next actions dentro
del budget.

#### Scenario: Output extenso
- **WHEN** el contenido excede el límite configurado
- **THEN** se trunca en un límite determinístico, se declara la omisión y no se corta un secreto parcialmente redactado

#### Scenario: URL insegura
- **WHEN** el artifact link contiene credenciales, query, fragment o esquema no HTTPS
- **THEN** el link no se renderiza

### Requirement: Automation Details configurable

El sistema SHALL derivar un bloque breve sólo desde run, pipeline, repository, PR y
commit allowlisted. El caller SHALL poder omitirlo sin cambiar los estados de decisión.

#### Scenario: Bloque omitido
- **WHEN** `include_automation_details` es false
- **THEN** JSON registra `included: false` y los outputs humanos omiten la sección

### Requirement: Privacidad y seguridad de Markdown

Todos los textos libres SHALL aplicar redacción y límites versionados. Los outputs
MUST NOT contener evidencia raw, Bearer/JWT, valores asignados a secretos, credenciales
en URLs, HTML ejecutable ni caracteres de control.

#### Scenario: Texto adversarial
- **WHEN** summary/message contiene token, password, pipe, salto de línea o script
- **THEN** el valor sensible se redacta y Markdown conserva su estructura

### Requirement: Compatibilidad y operación offline

Las APIs y archivos legacy SHALL permanecer sin cambios. El subcomando nuevo MUST
requerir rutas explícitas, MUST rechazar colisiones salvo overwrite explícito y MUST
completar sin sockets o APIs externas.

#### Scenario: Archivo existente
- **WHEN** un destino ya existe y no se suministra `--overwrite`
- **THEN** el comando falla cerrado sin modificar el archivo

#### Scenario: Red bloqueada
- **WHEN** sockets producen error durante build y rendering
- **THEN** todos los outputs solicitados se generan de forma idéntica
