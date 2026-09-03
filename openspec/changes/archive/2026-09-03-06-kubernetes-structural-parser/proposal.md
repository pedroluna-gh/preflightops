# Cambio 06: parser estructural de Kubernetes

## Why

El scanner actual intenta parsear YAML, pero ante un error o un documento sin `kind`
vuelve silenciosamente a coincidencias globales por texto. Ese comportamiento puede
mezclar objetos, tomar comentarios como evidencia y convertir un input inválido en un
resultado aparentemente evaluado. La etapa 06 necesita evidencia independiente por
objeto y campo, con fallo cerrado y límites defensivos.

## What Changes

- Se incorpora un parser dedicado para YAML Kubernetes multi-documento con límites de
  bytes, documentos, aliases, nodos, profundidad, objetos y containers.
- Se identifican objetos por `apiVersion`, `kind`, `namespace` y `name`, incluyendo
  listas Kubernetes sin perder identidad individual.
- Se evalúan workloads, Services, Ingress, NetworkPolicy, Secrets y
  PodDisruptionBudget mediante rutas estructurales, nunca por keywords globales.
- Se generan findings determinísticos con referencia de objeto, campo y predicado,
  sin copiar contenido de Secret ni payloads completos.
- El scanner legacy se conserva como API explícita y documentada, pero deja de ser un
  fallback automático de la ruta estructural.
- Se añaden fixtures y pruebas positivas, negativas, adversariales, de límites y de
  compatibilidad.

## Scope

Incluye exclusivamente parsing y reglas demostrables desde manifests suministrados.
No consulta el cluster, no renderiza Helm/Kustomize, no compara estado live y no cambia
scores, umbrales globales ni contratos legacy de reportes.

## Compatibility

`scan_kubernetes` pasa a ser estrictamente estructural y propaga errores tipados.
`scan_kubernetes_legacy` conserva el comportamiento histórico para consumidores que lo
seleccionen de forma explícita durante la migración. Los ids y scores existentes se
mantienen; nuevos findings usan ids aditivos y campos de evidencia adicionales.

## Privacy

Los objetos Secret se reducen a identidad y presencia del recurso antes de evaluar
reglas. `data`, `stringData`, valores arbitrarios, documentos completos y fragmentos de
YAML no aparecen en findings, excepciones ni logs.

## Rollback

Revertir el cambio restaura el scanner anterior. Durante una degradación controlada,
los consumidores pueden invocar explícitamente `scan_kubernetes_legacy`; no existe
estado persistente ni datos externos que reparar.

