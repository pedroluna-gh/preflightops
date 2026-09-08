# ADR 0010 — Evidence Providers v1

## Estado

Implementado localmente; cierre de etapa 11 pendiente de gates completos y CI.

## Opciones

| Diseño | Ventaja | Coste |
| --- | --- | --- |
| Conservador: diccionarios por SDK | Poca infraestructura | Motor acoplado y fallos inconsistentes |
| Balanceado: protocolo y contratos explícitos | Offline, testeable, serialización estable | Cada adapter cumple lifecycle y contrato |
| Enterprise: plugins dinámicos y workers | Aislamiento y distribución | Dependencias y operación adicionales |

Se adopta el balanceado. No hay descubrimiento automático, ejecución de plugins
descargados ni dependencia de Zabbix/GCP. El registro de adapters es explícito.

## Invariantes

El runner es read-only. Los proveedores reciben un contexto de ejecución con deadline,
cancelación y un supplier de credenciales excluido de representación/serialización.
El supplier no se consulta en una cancelación previa ni en un cache hit vigente.
Cada transporte futuro debe usar el tiempo restante como timeout y cerrar recursos.
El runner no puede interrumpir forzosamente Python arbitrario; rechaza respuestas tardías.

El agregado ordena por provider/version/control, exige identidades esperadas y rechaza
duplicados. Ausencias, evidencia futura y vencida no aprueban controles. N/A permanece
distinto en el contrato; el Trust Kernel v1 lo recibe conservadoramente como UNKNOWN
porque su contrato no representa N/A. El límite de confianza no cambia puntos de riesgo.

## Privacidad

Resúmenes deben ser proyecciones aprobadas, nunca cuerpos remotos. La detección de
secretos inline es defensa adicional, no un clasificador de información sensible.
Referencias opacas excluyen URLs firmadas y query strings. Digests de configuración y
contexto deben incluir el alcance de autorización no sensible, nunca secretos.

## Compatibilidad y rollback

La función de evaluación con providers devuelve legacy y assessment por separado.
El adaptador legacy conserva su límite máximo de confianza 80 y comportamiento por
defecto. Deshabilitar la nueva llamada permite continuar con assess_risk; conservar
artefactos ya emitidos. No existe migración de datos ni rollback de sistemas externos.

## Riesgos residuales

Los adapters ejecutan código confiable en proceso y requieren revisión y controles de
egress. La caché vive sólo en memoria y es acotada; no es un repositorio de auditoría.
Cambios de autorización deben cambiar el context_digest para impedir reutilización entre
principales. Las integraciones reales y sus pruebas quedan en sus etapas específicas.
