# terraform-plan-analysis Specification

## Purpose
Define el comportamiento observable para analizar planes JSON de Terraform de forma
estructural, determinística, acotada, compatible y segura para evidencia pre-CAB.

## Requirements

### Requirement: Contrato de entrada explícito y versionado
El sistema SHALL aceptar únicamente un objeto JSON de plan con `resource_changes` y
SHALL validar cualquier `format_version` presente. El sistema MUST aceptar versiones
1.x compatibles y MUST rechazar versiones mayores no soportadas, planes de estado sin
cambios, planes marcados como erróneos y formas JSON inválidas.

#### Scenario: Plan Terraform compatible
- **WHEN** se entrega un plan con `format_version` 1.x y `resource_changes` válido
- **THEN** el sistema analiza los cambios sin usar texto libre ni llamadas de red

#### Scenario: Versión mayor desconocida
- **WHEN** se entrega un plan con `format_version` 2.x
- **THEN** el sistema termina con un error tipado y no produce una evaluación LOW

#### Scenario: JSON malformado
- **WHEN** el input textual no es JSON válido
- **THEN** el sistema termina con un error sanitizado que no incluye el contenido

### Requirement: Semántica real de acciones y recursos
El sistema SHALL modelar address, type, provider, before, after y actions de cada
`resource_change`. MUST distinguir create, read, update, delete y las variantes
ordenadas delete/create y create/delete de replace. MUST rechazar acciones o
combinaciones desconocidas.

#### Scenario: Reemplazo destroy-before-create
- **WHEN** un recurso declara `actions: [delete, create]`
- **THEN** se emite un finding de replace y no uno de delete irreversible

#### Scenario: Reemplazo create-before-destroy
- **WHEN** un recurso declara `actions: [create, delete]`
- **THEN** se conserva el orden en la acción normalizada y se emite un finding de replace

#### Scenario: Acción desconocida
- **WHEN** un recurso declara una acción no soportada o una combinación inválida
- **THEN** el parser falla de forma cerrada indicando la ruta estructural afectada

### Requirement: Findings estructurados y determinísticos
El sistema SHALL detectar riesgos iniciales de IAM, red, exposición pública, DNS, KMS,
bases de datos y operaciones destructivas, incluyendo recursos GCP. Cada finding MUST
incluir address, provider, resource type, acción normalizada y evidencia estructurada
sin payloads completos. Para el mismo input y configuración, el orden y contenido de
los findings MUST ser idéntico.

#### Scenario: Recurso GCP expuesto públicamente
- **WHEN** un firewall GCP cambia y un atributo no sensible permite `0.0.0.0/0`
- **THEN** se emiten findings de red y exposición con ruta y predicado verificables

#### Scenario: Texto riesgoso en un valor irrelevante
- **WHEN** una descripción contiene palabras como `destroy`, `kms` o `public_ip` pero el tipo, la acción y los atributos relevantes no representan riesgo
- **THEN** no se emiten findings por coincidencia textual

#### Scenario: Orden de recursos diferente
- **WHEN** dos planes contienen los mismos cambios en orden distinto
- **THEN** ambos producen findings byte-a-byte equivalentes al serializarse canónicamente

### Requirement: Protección de valores sensibles
El sistema MUST aplicar `before_sensitive` y `after_sensitive` antes de evaluar reglas.
MUST ignorar cualquier subárbol marcado como sensible y MUST NOT copiar valores before,
after, variables, outputs ni payloads completos a findings, excepciones o logs.

#### Scenario: CIDR público marcado sensible
- **WHEN** `after` contiene un valor público pero `after_sensitive` marca esa ruta
- **THEN** el sistema no inspecciona ni expone el valor y no deriva evidencia desde él

#### Scenario: Secreto adversarial en plan inválido
- **WHEN** un valor secreto acompaña una estructura inválida
- **THEN** el error identifica solamente el código y la ruta, nunca el valor rechazado

### Requirement: Límites defensivos y fallo cerrado
El sistema SHALL imponer límites configurables con defaults seguros para bytes de input,
profundidad, nodos JSON, cantidad de cambios y longitud de strings. Exceder un límite
MUST producir un error tipado antes de emitir findings parciales.

#### Scenario: Plan grande permitido
- **WHEN** un plan permanece dentro de todos los límites configurados
- **THEN** se procesa completamente con consumo acotado y resultado determinístico

#### Scenario: Plan excesivamente profundo
- **WHEN** la profundidad JSON excede el límite
- **THEN** el parser falla con código de límite y sin recursión no controlada

#### Scenario: Demasiados recursos
- **WHEN** `resource_changes` excede el máximo permitido
- **THEN** el parser falla antes de evaluar reglas y no devuelve findings parciales

### Requirement: Compatibilidad legacy explícita
El sistema SHALL conservar `scan_terraform` para texto legacy con deprecación
documentada. La ruta JSON MUST seleccionarse explícitamente y un error JSON MUST NOT
activar el scanner textual como fallback silencioso. Los scores y umbrales globales
MUST permanecer sin cambios.

#### Scenario: Consumidor legacy
- **WHEN** un consumidor continúa invocando el scanner textual
- **THEN** recibe el comportamiento legacy existente durante la ventana de migración

#### Scenario: Error en entrada JSON explícita
- **WHEN** el consumidor selecciona Terraform JSON y el parser falla
- **THEN** el error se propaga y el scanner textual no se ejecuta

### Requirement: Precisión medida y reproducible
El proyecto SHALL mantener una matriz sanitizada de casos con resultados esperados para
positivos, negativos, negaciones, acciones destructivas y recursos GCP. La matriz MUST
reportar precisión y recall de 100% sobre el corpus conocido antes de cerrar el cambio.

#### Scenario: Corpus conocido
- **WHEN** se ejecuta la prueba de precisión sobre todos los fixtures catalogados
- **THEN** cada finding esperado aparece y ningún finding no esperado es emitido
