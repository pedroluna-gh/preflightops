## ADDED Requirements

### Requirement: Carga YAML multi-documento segura y acotada
El sistema SHALL cargar YAML Kubernetes multi-documento con un loader seguro y límites
configurables de bytes, documentos, aliases, profundidad, nodos, strings, objetos y
containers. MUST rechazar tags no seguros, claves duplicadas, grafos recursivos y
límites excedidos antes de emitir findings parciales.

#### Scenario: Manifest válido multi-documento
- **WHEN** se entrega un conjunto de objetos dentro de todos los límites
- **THEN** cada objeto se carga una vez sin llamadas de red

#### Scenario: Alias cíclico o excesivo
- **WHEN** el YAML contiene un grafo recursivo o supera el límite de aliases
- **THEN** el parser falla con código y ruta sanitizados sin evaluar reglas

#### Scenario: YAML inválido
- **WHEN** el input no puede parsearse de forma inequívoca
- **THEN** se propaga un error tipado y nunca se devuelve una evaluación PASS o LOW

### Requirement: Identidad individual obligatoria
Cada objeto evaluado SHALL identificarse por `apiVersion`, `kind`, `namespace` y
`metadata.name`. Documentos vacíos MUST ignorarse y objetos incompletos o items inválidos
de un `List` MUST fallar de forma cerrada.

#### Scenario: Objetos homónimos en namespaces distintos
- **WHEN** dos workloads comparten name pero tienen namespaces diferentes
- **THEN** sus findings contienen object_ref distintos y verificables

#### Scenario: Documento vacío entre objetos
- **WHEN** un separador YAML produce un documento vacío
- **THEN** se ignora sin crear un objeto o finding fantasma

### Requirement: Evaluación independiente por workload y container
El sistema SHALL evaluar Deployment, StatefulSet, DaemonSet, Job y CronJob por objeto.
Para workloads de larga duración, SHALL evaluar readinessProbe, livenessProbe y
resources por container sin usar campos de otro objeto o container.

#### Scenario: Probe presente sólo en un workload
- **WHEN** un Deployment completo precede a otro sin probes
- **THEN** los findings de probes faltantes referencian únicamente al segundo objeto y
  sus containers afectados

#### Scenario: Container mixto
- **WHEN** un PodSpec tiene un container completo y otro sin límites
- **THEN** el finding de límites identifica sólo el segundo container y el campo exacto

### Requirement: Reglas demostrables por objeto y campo
El sistema SHALL evaluar Service, Ingress, NetworkPolicy, Secret,
PodDisruptionBudget y configuración de workload mediante rutas estructurales. MUST NOT
afirmar drift, reducción, exposición efectiva o impacto que requiera estado live.

#### Scenario: Service LoadBalancer
- **WHEN** `spec.type` es `LoadBalancer`
- **THEN** se emite evidencia en `spec.type` para ese Service

#### Scenario: Texto riesgoso en comentario
- **WHEN** un comentario menciona Secret, LoadBalancer o replicas cero
- **THEN** no se emite ningún finding por ese texto

#### Scenario: PDB sin protección declarada
- **WHEN** un PodDisruptionBudget declara `maxUnavailable: 100%` o `minAvailable: 0`
- **THEN** se emite un finding con el campo y predicado exactos sin inferir cobertura live

### Requirement: Privacidad estricta de Secret
El sistema MUST reducir objetos Secret a identidad antes de ejecutar reglas. MUST NOT
incluir `data`, `stringData`, valores decodificados, fragmentos YAML ni payloads completos
en modelos públicos, findings, excepciones o logs.

#### Scenario: Secret adversarial
- **WHEN** un Secret contiene marcadores únicos en data y stringData
- **THEN** sólo se emite presencia/tipo del objeto y ningún marcador aparece en outputs

#### Scenario: Secret dentro de List inválida
- **WHEN** un Secret válido acompaña un item posterior inválido
- **THEN** el parser falla sin devolver el Secret ni su contenido como finding parcial

### Requirement: Evidencia determinística y compatible
Cada finding estructural MUST incluir identidad del objeto, campo y predicado. Los ids,
scores y severidades existentes MUST conservarse, y el orden MUST ser estable para el
mismo conjunto semántico de objetos.

#### Scenario: Documentos reordenados
- **WHEN** dos inputs contienen los mismos objetos en orden diferente
- **THEN** la serialización de findings es byte-a-byte equivalente

#### Scenario: Finding heredado
- **WHEN** un Deployment válido activa una regla existente
- **THEN** conserva su id, score y severidad y añade evidencia estructurada

### Requirement: Scanner legacy explícito sin fallback
El sistema SHALL conservar el scanner textual histórico mediante una API explícita.
Un error de la ruta estructural MUST NOT activar esa API automáticamente.

#### Scenario: Consumidor legacy explícito
- **WHEN** un consumidor invoca `scan_kubernetes_legacy`
- **THEN** recibe las coincidencias textuales históricas durante la ventana de migración

#### Scenario: Error estructural
- **WHEN** `scan_kubernetes` recibe YAML inválido o un objeto incompleto
- **THEN** el error se propaga y no se ejecutan coincidencias por keywords

