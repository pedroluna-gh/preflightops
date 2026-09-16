# Etapa 14: políticas y excepciones auditables

## Why

PreflightOps ya dispone de Policy Bundle v2, firmas Ed25519 y Waiver v1.
La etapa 14 debe cerrar las brechas de ejecución y reproducibilidad, no
reemplazar esos contratos ni añadir conectores. La etapa 13 quedó cerrada
en PR #50, comentario issuecomment-5591910696, con post-merge verde para
99eb77dc54acb26119d9924dda0a615b2f2738dc.

## What Changes

- Simulación de políticas activas con claves públicas explícitas e independientes.
- Validación de documentos sin ambigüedades y límites de recursos.
- Evaluación explícita de modos de fallo sin aprobar cambios ni alterar evidencias.
- Reproducción histórica con instante explícito, contexto y digests conservados.
- Revisión de versiones, precedence, conflictos, expiración y rollback.
- Evidencia de pruebas, compatibilidad, empaquetado y CI antes del cierre.

## Capabilities

### New Capabilities

- `policy-governance`: ciclo gobernado de políticas y excepciones.

### Modified Capabilities

Ninguna modificación a los proveedores o sinks existentes.

## Impact

API Python y comandos de gobierno existentes; cambios aditivos cuando sea
posible. No se eliminan outputs legacy ni se modifican decisiones históricas.
Sólo se publican referencias aprobadas, nunca claves privadas o contenido
sensible completo. Rollback: restaurar distribución y bundle previamente
aprobados con su clave pública fijada, manteniendo registros históricos.
