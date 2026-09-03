# Evidencia de cierre — etapa 05

Fecha local: 2026-09-03. Alcance: parser estructural de Terraform Plan JSON;
no se modificaron umbrales globales ni el scanner Kubernetes.

## Resultados verificables

- Línea base previa: 52 tests Terraform/structured existentes, todos exitosos.
- Pruebas focalizadas finales: 194 tests de parser, legacy, CLI, changed-files,
  risk engine y contratos, todos exitosos.
- Suite completa: 500 tests exitosos en Python 3.12.13 sobre Windows.
- Cobertura branch-aware: 86,60%, superior al gate de 85%; módulo
  `terraform_plan.py`: 93%.
- Ruff check: exitoso. Ruff format check: 96 archivos formateados.
- mypy: 19 módulos sin hallazgos.
- Corpus sanitizado `precision-matrix-v1.json`: 100% precision y 100% recall
  sobre ocho casos conocidos positivos/negativos multi-cloud.
- Build sin aislamiento con el toolchain fijado: wheel y sdist 0.4.2 exitosos;
  el wheel contiene `preflightops/terraform_plan.py`.
- Twine check: wheel y sdist exitosos.
- Instalación `--no-index --no-deps` e import desde target limpio: exitosos.
- OpenSpec `validate --strict`: exitoso antes de implementación; se repite al cierre.
- Publicación aislada: PR #42 desde `stage-05-terraform-plan-json` hacia `main`,
  head `1efef866ba586d722905a5bdf79f8e4a9839125c`, 26 archivos y 10 commits.
- CI remoto: 15 de 15 checks exitosos, incluidos tests Windows/macOS/Ubuntu,
  Python 3.11-3.13, quality gates, auditorías de dependencias, CodeQL,
  contrato de la Action y ClusterFuzzLite.
- Revisión remota: cero comentarios, cero reviews, cero hilos pendientes y estado
  mergeable `clean` antes de integrar.

El primer build aislado no pudo descargar `setuptools==83.0.0` porque el sandbox
bloqueó PyPI. No fue un fallo de build: la repetición sin aislamiento usó la misma
versión fijada ya instalada y produjo ambos artefactos. El CI remoto independiente
confirmó posteriormente todos los gates sobre el PR #42.

## Invariantes demostrados

- JSON inválido, versión mayor desconocida, plan `errored`, acción desconocida o
  límite excedido termina en error y no en LOW.
- Delete y ambos órdenes de replace provienen de `change.actions` reales.
- Valores sensitive/unknown se eliminan antes de reglas y no aparecen en findings
  ni errores.
- El mismo conjunto de cambios produce findings iguales aunque cambie su orden.
- El scanner textual legacy permanece disponible y nunca es fallback de JSON.

## Riesgos residuales

- El catálogo de resource types es intencionalmente conservador y no cubre todos los
  providers; cada ampliación requiere fixtures y cambio compatible.
- Mappings Python legacy sin `format_version` conservan una excepción temporal;
  archivos y strings nuevos lo requieren.
- Un atributo sensitive o unknown no puede sustentar una detección positiva. La etapa
  07 debe reflejar ese gap en confidence/freshness sin promoverlo a PASS.
- No se resuelven schemas de providers, HCL ni grafos de dependencias.

## Rollback

Deshabilitar la entrada `--terraform-json` o restaurar el delegador anterior de
`scan_terraform_json`. `scan_terraform`, outputs legacy, scores y umbrales globales
permanecen intactos. Conservar fixtures y evidencia de evaluaciones emitidas para
auditoría; no hay escrituras externas ni reparación de datos.
