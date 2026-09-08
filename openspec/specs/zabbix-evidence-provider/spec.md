# zabbix-evidence-provider Specification

## Purpose

Obtener evidencia Zabbix de sólo lectura con límites, provenance y degradación explícita.

## Requirements

### Requirement: Métodos y autenticación acotados
El cliente SHALL permitir sólo métodos de lectura aprobados y MUST NOT crear,
actualizar o borrar objetos. Tokens MUST NOT aparecer en errores o evidencia.

#### Scenario: Método de escritura
- **WHEN** se solicita host.create o cualquier método no permitido
- **THEN** se rechaza antes de consultar credenciales o transporte

#### Scenario: Versión incompatible
- **WHEN** apiinfo.version devuelve una familia no soportada
- **THEN** no se envían credenciales ni se supone compatibilidad

### Requirement: Semántica conservadora
El provider SHALL separar existencia, estado y cobertura esperada. Datos ausentes,
permisos insuficientes o respuestas parciales MUST NOT producir PASS.

#### Scenario: Host visible sin triggers esperados
- **WHEN** existe el host pero faltan los triggers configurados
- **THEN** existencia no se interpreta como monitoreo adecuado

#### Scenario: Mantenimiento asignado a un grupo
- **WHEN** el host pertenece a un grupo con una definición de mantenimiento superpuesta
- **THEN** se consulta la asignación al grupo aunque el filtro directo por host esté vacío
- **AND** no se confunde una definición recurrente con una ocurrencia efectiva

#### Scenario: Mantenimiento de otro host del mismo grupo
- **WHEN** el filtro por grupo devuelve una asignación directa a otro host
- **THEN** no se aplica al host evaluado sin una asignación al grupo confirmada

### Requirement: Freshness y provenance
Evidencia SHALL cumplir Provider Contract v1 con tiempos explícitos y referencias
opacas; freshness de muestras SHALL basarse en timestamps demostrables.

#### Scenario: Muestra vencida
- **WHEN** lastclock excede la antigüedad configurada
- **THEN** una consulta reciente no convierte esa muestra en evidencia vigente

### Requirement: Presupuesto de ejecución
Timeouts, retries, tasa, páginas y tamaño de respuesta SHALL estar acotados.

#### Scenario: Paginación sin progreso
- **WHEN** la API repite IDs o agota el máximo de páginas sin demostrar completitud
- **THEN** no se declara completa ni favorable la consulta

### Requirement: Validación aislada
La suite SHALL probar fallos de autenticación, timeout, respuestas malformadas,
diferencias de versión y datos parciales sin usar una instancia productiva.

#### Scenario: Error con contenido sensible
- **WHEN** una excepción remota contiene un token o una URL interna
- **THEN** el resultado sólo expone una categoría estática y confianza cero
