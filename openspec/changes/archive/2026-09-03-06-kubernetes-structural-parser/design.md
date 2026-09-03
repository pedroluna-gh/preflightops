# Diseño: análisis estructural Kubernetes

## Context

La implementación actual comparte parsing, fallback textual y reglas en
`scanners.py`. Usa `safe_load_all`, pero no limita tamaño, documentos, aliases o
profundidad; un error activa análisis por texto y algunas compatibilidades históricas
aceptan probes fuera del PodSpec. La etapa requiere que cada conclusión provenga del
objeto y campo correctos.

## Design Options

### Conservador

Mantener toda la lógica en `scanners.py`, añadir unos límites previos y retirar sólo el
fallback en errores. Minimiza archivos modificados, pero mantiene acoplados parsing,
normalización, privacidad y reglas; dificulta demostrar que Secret y aliases quedan
acotados antes de producir evidencia.

### Balanceado — elegido

Crear `kubernetes_manifest.py` con límites inmutables, error tipado, loader seguro con
claves duplicadas rechazadas, modelo de identidad por objeto y reglas puras. Exponer
un scanner estructural determinístico y un adaptador legacy separado. Ofrece una
frontera auditable y testeable sin introducir un motor externo ni acceso al cluster.

### Enterprise

Validar schemas OpenAPI por versión, ejecutar políticas Rego/CEL, resolver Helm y
comparar contra inventario live. Aporta mayor cobertura semántica, pero requiere
artefactos externos, lifecycle de schemas y potencialmente red/credenciales; excede el
alcance offline de esta etapa.

## Decision

Se adopta el diseño balanceado. El módulo nuevo será la única ruta estructural; el
scanner histórico queda explícito y nunca se invoca automáticamente tras un error.

## Input Boundary

`KubernetesManifestLimits` define defaults seguros para:

- bytes UTF-8 de entrada;
- documentos YAML;
- tokens alias;
- profundidad y nodos únicos;
- longitud de strings y claves;
- objetos expandidos desde `List`;
- containers e initContainers.

Se tokeniza primero para contar documentos y aliases sin construir el grafo. Después,
un `SafeLoader` estricto rechaza tags peligrosos, claves no string y claves duplicadas.
El grafo resultante se recorre iterativamente, detectando ciclos y límites antes de
normalizar objetos o emitir findings.

## Object Model

Cada `KubernetesObject` conserva `api_version`, `kind`, `namespace`, `name`, índice de
documento y cuerpo sanitizado. Para Secret, el cuerpo se reduce a apiVersion, kind y
metadata mínima: los datos nunca alcanzan las reglas ni el modelo público.

`kind: List` se expande en objetos individuales con límites. Documentos vacíos se
ignoran. Un documento no mapping, objeto sin apiVersion/kind/metadata.name o lista con
items inválidos produce `KubernetesManifestError` con código y ruta estables.

## Rule Evaluation

Los findings conservan `id`, `description`, `severity`, `score` y `source`, y añaden:

- `resource`: compatibilidad compacta `kind/name`;
- `object_ref`: apiVersion, kind, namespace y name;
- `evidence`: `field` y predicado estable; `container` cuando corresponde.

Reglas cubiertas:

- cambios de Deployment, StatefulSet, DaemonSet, Job/CronJob, Ingress,
  NetworkPolicy y Secret;
- replicas cero en controladores con replicas;
- probes y requests/limits por container de workloads de larga duración;
- Service LoadBalancer/NodePort;
- hostNetwork, hostPID, hostIPC, privileged y allowPrivilegeEscalation;
- estrategias declaradas de disponibilidad degradada que puedan probarse desde el
  manifest;
- PodDisruptionBudget con `maxUnavailable: 100%` o `minAvailable: 0`.

No se afirma drift, eliminación, reducción respecto de live, cobertura real de un PDB,
alcance externo efectivo de una IP ni impacto de rollout que requiera estado previo.

## Determinism

Los objetos y findings se ordenan por identidad, regla, campo y container. Los mensajes
no incluyen representación Python ni contenido rechazado. El mismo YAML semántico y
límites produce la misma lista serializable.

## Migration

Consumidores con manifests Kubernetes válidos continúan usando `scan_kubernetes`.
Entradas históricas incompletas o análisis deliberadamente textual deben migrar a
`scan_kubernetes_legacy` y corregirse antes de volver a la ruta estructural. CLI, Action
y motor de riesgo permanecen fail-closed por defecto.

## Residual Risks

- No se validan schemas OpenAPI específicos de CRDs o versiones Kubernetes.
- No se conoce estado live, selectores efectivos, endpoints, admission policies ni
  NetworkPolicies combinadas.
- La política inicial cubre campos demostrables y debe evolucionar con fixtures para
  nuevos kinds, apiVersions y semánticas.

