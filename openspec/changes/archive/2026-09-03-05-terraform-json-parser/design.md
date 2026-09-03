## Context

`scan_terraform_json()` ya existe como extensión aditiva, pero opera directamente sobre
diccionarios sin contrato de versión, límites o modelo intermedio. Sus reglas se basan
en substrings del tipo y serializan `after` para detectar exposición, lo que dificulta
probar privacidad, precisión y fallo cerrado. Terraform define un formato JSON 1.x con
acciones ordenadas y mapas paralelos `before_sensitive`/`after_sensitive`.

## Goals / Non-Goals

**Goals:**

- Separar parseo/validación, normalización segura y evaluación de reglas.
- Conservar la API y scores existentes mientras se endurece su semántica.
- Producir evidencia mínima, determinística y explicable por recurso.
- Acotar CPU y memoria mediante límites verificables antes de evaluar findings.

**Non-Goals:**

- Descargar schemas de providers o consultar Terraform Cloud/proveedores.
- Interpretar HCL, resolver valores unknown o inferir dependencias completas.
- Cambiar el risk engine, umbrales globales o Kubernetes.

## Decisions

### Modelo intermedio inmutable

Se incorporan modelos congelados para límites, plan y cambio de recurso. La entrada se
recorre iterativamente para medir profundidad, nodos y bytes escalares; luego se valida
y normaliza. `before` y `after` se proyectan aplicando primero sus máscaras sensitive.
Un subárbol sensitive se reemplaza en memoria por un sentinel y nunca llega a reglas o
evidencia.

Alternativa descartada: aplicar reglas directamente al diccionario. Es más corta, pero
mezcla validación, privacidad y detección, y permite resultados parciales ambiguos.

### Compatibilidad de formato Terraform

Se acepta `format_version` 1.x y se ignoran campos top-level desconocidos para permitir
minor versions compatibles. Una major distinta, `errored: true`, ausencia o forma
inválida de `resource_changes`, recursos mal formados y acciones desconocidas producen
`TerraformPlanError`, subclase de `ValueError` para compatibilidad con consumidores.
La ausencia de `format_version` sigue aceptándose temporalmente para mappings ya
decodificados que usaban la API pública, y se documenta como compatibilidad legacy; los
archivos/strings nuevos deben declararlo.

### Acciones canónicas

Las únicas combinaciones admitidas son `no-op`, `create`, `read`, `update`, `delete`,
`delete/create` y `create/delete`. Ambas combinaciones dobles se representan como
`replace`, conservando el orden original en evidencia. Delete emite el rule ID actual;
replace conserva el ID y score actual para no cambiar umbrales.

### Reglas declarativas por tipo y atributos

Los dominios IAM, red, DNS, KMS y bases de datos usan prefijos/nombres de resource type
concretos por provider, no búsqueda libre sobre todo el payload. Exposición pública usa
un conjunto acotado de nombres de atributo y valores seguros, después de redacción.
Cada evidencia contiene solamente `attribute_path` y `predicate`; nunca el valor.

Los findings se ordenan por address, acción, ID y evidencia canónica. Esto elimina la
dependencia del orden de `resource_changes` sin tocar scores globales.

### Presupuestos defensivos

Defaults: 16 MiB de input textual, profundidad 64, 500.000 nodos, 20.000 cambios y
1 MiB por string. Los límites son inmutables y configurables para tests/consumidores.
El parser no devuelve findings parciales cuando un presupuesto o invariante falla.

### Selección de scanner

`--terraform-json` y la detección no ambigua existente seleccionan la ruta estructural.
`--terraform` sigue seleccionando el scanner legacy. No se captura una excepción JSON
para reintentar como texto. La documentación marca legacy/deprecated, pero no elimina
la API ni sus outputs.

## Risks / Trade-offs

- [Schemas de provider evolucionan] → catálogo conservador, evidencia por regla y
  fixtures versionados; ampliar mediante cambios compatibles posteriores.
- [Atributo público unknown o sensitive no se puede evaluar] → no inventar un PASS;
  documentar la limitación para la futura etapa de confidence/freshness.
- [Planes válidos extremadamente grandes superan defaults] → permitir límites
  explícitos con máximos documentados y error estable.
- [Aceptar mappings sin `format_version` mantiene ambigüedad temporal] → restringir la
  excepción de compatibilidad a objetos ya decodificados y recomendar formato 1.x.

## Migration Plan

1. Mantener `scan_terraform` y todos sus tests sin cambios de firma.
2. Migrar CI/Action a `terraform show -json` mediante la entrada explícita existente.
3. Observar errores tipados y precisión del corpus antes de deprecar formalmente texto.
4. Rollback: retirar el parser/modelo nuevo y restaurar la implementación previa de
   `scan_terraform_json`; el scanner textual y los outputs legacy continúan disponibles.

