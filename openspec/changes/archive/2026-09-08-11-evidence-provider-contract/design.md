# Diseño del contrato común

## Decisión

| Alternativa | Beneficio | Coste |
| --- | --- | --- |
| Conservadora: diccionarios específicos | Poca implementación | Acoplamiento y validación inconsistente |
| Balanceada: protocolo explícito y contratos inmutables | Testeable, offline, sin descubrimiento implícito | Adaptador por proveedor |
| Enterprise: plugins dinámicos y workers distribuidos | Aislamiento operacional | Dependencias y operación adicionales |

Se elige la alternativa balanceada. Los adaptadores son código confiable registrado
explícitamente, no plugins descargados o ejecutados automáticamente.

## Límites

El contrato contiene resúmenes aprobados y referencias opacas; nunca payloads completos,
credenciales, headers o errores remotos. Los tiempos son UTC explícitos. La confianza
es una medida de evidencia independiente del riesgo y de la decisión humana.

## Ejecución

Configuración y capabilities declaran controles disponibles y operación read-only.
Cada solicitud lleva contexto, controles, instante de evaluación y deadline.
Cancelación cooperativa y timeouts del transporte son obligatorios para adaptadores.
El runner rechaza respuestas tardías, incompletas, duplicadas o de identidad incorrecta.
No se promete interrumpir forzosamente código Python arbitrario dentro del proceso.

## Determinismo y degradación

Identidades y hashes usan JSON canónico; orden de llegada no cambia agregados.
Freshness se calcula contra el instante explícito. Evidencia vencida/futura no puede
aprobar controles. ERROR y UNKNOWN se conservan y reducen completitud/confianza.
NOT_APPLICABLE requiere justificación y no equivale a evidencia PASS.

## Caché

Clave ligada a proveedor/versión/configuración/contexto/controles, sin secretos.
Lectura devuelve copias inmutables y exige vigencia al instante solicitado. Fallos,
cancelaciones y respuestas parciales no se almacenan como éxito. Capacidad acotada.

## Riesgos y rollback

Un adapter malicioso no queda aislado por un protocolo Python. El despliegue debe
revisar adapters y limitar egress; aislamiento en procesos queda fuera de esta fase.
Rollback deshabilita la API aditiva y conserva contratos emitidos para auditoría.
