## Why

El scanner estructural actual reconoce algunas acciones y tipos, pero acepta planes sin
contrato de formato, ignora acciones desconocidas, no limita tamaño/profundidad y puede
inspeccionar valores marcados como sensibles. Esto impide demostrar comportamiento
fail-closed, precisión conocida y evidencia segura para `terraform show -json`.

## What Changes

- Introducir un parser explícito para Terraform Plan JSON v1.x con límites de bytes,
  nodos, profundidad y cantidad de cambios.
- Validar `format_version`, `resource_changes`, identidad de recurso, provider y
  combinaciones de acciones; un error o acción desconocida detendrá la evaluación.
- Modelar create, read, update, delete y las dos variantes ordenadas de replace.
- Emitir findings determinísticos con address, provider, tipo, acción normalizada y
  evidencia estructurada basada exclusivamente en rutas y predicados no sensibles.
- Añadir reglas iniciales para IAM, red, exposición pública, DNS, KMS, bases de datos y
  operaciones destructivas en AWS, Azure y GCP.
- Mantener `scan_terraform()` como API legacy/deprecated y exigir selección explícita;
  nunca usarla como fallback silencioso de un error JSON.
- Incorporar fixtures sanitizados, matriz de precisión y pruebas positivas, negativas,
  adversariales, de compatibilidad y escala.
- Documentar migración, limitaciones, privacidad y rollback sin cambiar umbrales globales.

No objetivos: resolver schemas de providers, evaluar HCL, consultar APIs cloud, construir
un grafo completo de dependencias o modificar los scanners de Kubernetes.

## Capabilities

### New Capabilities

- `terraform-plan-analysis`: Contrato y evaluación estructural, determinística,
  acotada y fail-closed de planes JSON de Terraform.

### Modified Capabilities

Ninguna; no existían specs OpenSpec archivadas antes de este cambio.

## Impact

Afecta `preflightops.scanners.scan_terraform_json`, su API pública, documentación,
fixtures y tests. El contrato legacy de `scan_terraform` permanece disponible y los
scores/umbrales globales no cambian. No se añaden llamadas de red ni dependencias runtime.

| Diseño | Beneficio | Costo/riesgo |
| --- | --- | --- |
| Conservador | Endurecer validaciones sobre el scanner actual | Mantiene reglas por substring y evidencia débil |
| Balanceado | Parser acotado, acciones tipadas, reglas declarativas y evidencia sanitizada | Más código de contrato y fixtures |
| Enterprise | Schema de providers y grafo semántico completo | Acoplamiento y complejidad fuera de esta etapa |

Decisión: diseño balanceado. Entrega precisión y auditabilidad sin introducir providers,
red ni un motor de políticas prematuro.

