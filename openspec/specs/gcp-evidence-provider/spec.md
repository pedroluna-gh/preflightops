# gcp-evidence-provider Specification

## Purpose

Obtener evidencia GCP de sólo lectura con alcance y degradación verificables.

## Requirements

### Requirement: Alcance explícito
El provider SHALL limitarse a proyectos permitidos y MUST NOT enumerar proyectos
externos, carpetas u organizaciones. Recursos y series SHALL verificar proyecto.

#### Scenario: Recurso fuera del allowlist
- **WHEN** una selección o respuesta apunta a otro proyecto
- **THEN** se rechaza sin ampliar la consulta ni producir evidencia favorable

#### Scenario: Metrics scope multiproyecto
- **WHEN** Monitoring permite consultar métricas de proyectos asociados
- **THEN** el filtro y la validación de respuesta restringen el proyecto esperado

### Requirement: Credenciales oficiales inyectadas
Las APIs oficiales SHALL usar ADC inyectadas y MUST NOT descubrir credenciales
ambientales por importación. Identidad no demostrable SHALL ser UNKNOWN.

#### Scenario: Permiso denegado
- **WHEN** una lectura falla por IAM o scope
- **THEN** se obtiene UNKNOWN/ERROR con confianza cero, sin copiar secretos

### Requirement: Semántica de controles
Existencia, enabled state, cobertura y freshness SHALL permanecer separados.
Policies, dashboards, uptime, services/SLOs y assets SHALL tener selección explícita.

#### Scenario: Policy deshabilitada
- **WHEN** una policy existe pero está deshabilitada
- **THEN** no se declara monitoreo operativo por su sola existencia

#### Scenario: Métrica vencida
- **WHEN** los puntos son ausentes, futuros o demasiado antiguos
- **THEN** una nueva consulta no renueva artificialmente la evidencia

### Requirement: Presupuestos de lectura
Timeouts, páginas, respuesta, cuotas y retries SHALL estar acotados; escrituras
cloud MUST NOT estar disponibles en la interfaz del provider.

#### Scenario: Paginación incompleta
- **WHEN** se repite un token o se agota el presupuesto de páginas
- **THEN** no se emite PASS para una lista cuya completitud no se demostró

### Requirement: Validación y operación
El provider SHALL pasar la suite común y pruebas adversariales sin recursos
productivos. IAM mínimo por capability y rollback SHALL estar documentados.

#### Scenario: Ejecución de tests
- **WHEN** se ejecuta la suite con mocks
- **THEN** no se accede a ADC ambientales ni se modifica ningún recurso cloud
