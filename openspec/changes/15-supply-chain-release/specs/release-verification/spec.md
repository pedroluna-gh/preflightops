## ADDED Requirements

### Requirement: Release artifacts are verifiable offline

PreflightOps SHALL producir un bundle con distribuciones, inventario SBOM y
checksums verificables sin credenciales ni acceso de red para comprobar hashes.

#### Scenario: Intact bundle

- **WHEN** los archivos y metadatos corresponden al manifiesto aprobado
- **THEN** la verificación confirma integridad sin afirmar autenticidad por hash

#### Scenario: Tampered or ambiguous bundle

- **WHEN** falta un artefacto, cambia su contenido o un manifiesto usa rutas inseguras
- **THEN** la verificación falla sin aceptar parcialmente el bundle

### Requirement: Packaging is reproducible and installable

PreflightOps SHALL comparar builds independientes con entradas y toolchain
fijadas y SHALL ejecutar clean-install del wheel que se pretende publicar.

#### Scenario: Repeated build

- **WHEN** se repite el build bajo el mismo contexto documentado
- **THEN** se comparan hashes y cualquier divergencia bloquea la promoción

### Requirement: Security exceptions and promotion are explicit

PreflightOps SHALL documentar soporte, EOL, disclosure, SLA y rollback;
excepciones SHALL tener owner, alcance, justificación y expiración.
La promoción SHALL conservar checksums, SBOM y provenance verificable sin
inventar firma ni aprobación cuando la plataforma no las haya producido.

#### Scenario: Expired exception

- **WHEN** una excepción está incompleta o ha expirado
- **THEN** no permite eludir un gate de seguridad

#### Scenario: Rollback

- **WHEN** se restaura una versión anterior aprobada
- **THEN** se verifica su bundle y se preservan tags y evidencia histórica
