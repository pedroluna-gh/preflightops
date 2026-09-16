# ADR: cierre incremental de gobierno de políticas

## Context

La implementación existente ofrece ownership, fechas, hashes, overlays,
firmas y excepciones. La inspección identifica simulación sin claves para
políticas activas, carga YAML permisiva y modos de fallo sin evaluación
explícita. Estas brechas impiden declarar cerrada la etapa.

## Goals / Non-Goals

Cerrar exclusivamente etapa 14. No añadir conectores, autoridad CAB,
requisitos regulatorios inventados ni activar políticas productivas.

## Decisions

| Diseño | Beneficio | Coste o límite |
| --- | --- | --- |
| Conservador: documentación y pruebas existentes | Cambio mínimo | No corrige brechas de ejecución |
| Balanceado: endurecer v2/v1 y añadir evaluación explícita | Conserva consumidores y corrige brechas verificables | Requiere pruebas de compatibilidad y límites claros |
| Enterprise: motor externo y servicio de aprobación | Gobierno distribuido | Nueva infraestructura y autoridad fuera de alcance |

Se elige balanceado. OpenSpec estructura el trabajo de PreflightOps; no se
modifica el proyecto OpenSpec. Las firmas prueban posesión de una clave
confiable, no identidad humana ni autorización corporativa por sí solas.

## Risks / Trade-offs

- La custodia de claves y aprobación independiente pertenecen al operador.
- Fail-open permite continuar de forma informativa, nunca transforma
  ERROR/UNKNOWN en PASS ni autoriza cambios.
- El motor no puede impedir ediciones externas de un archivo histórico;
  digests y registros inmutables deben detectar divergencias.
- La simulación no ejecuta proveedores ni verifica condiciones productivas.

## Migration Plan

Preservar Policy Bundle v2 y Waiver v1; documentar cualquier entrada inválida
antes aceptada accidentalmente. Las nuevas opciones CLI serán opcionales.
Validar ejemplos y wheel sin dependencias adicionales. Revertir a la
distribución anterior y bundle aprobado si falla la adopción; no reescribir
evidencia anterior ni convertir un waiver expirado en vigente.
