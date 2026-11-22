## Context

PreflightOps es un CLI/biblioteca offline con UI Streamlit opcional y providers
read-only explícitos. El runner serializa ejecuciones y dispone de caché LRU acotada,
pero su espera de lock no consume el deadline. El core determinístico no debe medir
relojes ni emitir telemetría. Las protecciones de release existentes se preservan.

## Goals / Non-Goals

Diagnosticar fallos sin payloads, medir límites reales y permitir operación por otra
persona. No crear backend, recolector remoto, HA ficticia, SLA contractual ni activar
integraciones. No afirmar revisión independiente en un proyecto de un mantenedor.

## Decisions

| Diseño | Beneficio | Coste/riesgo |
| --- | --- | --- |
| Conservador: sólo documentación y tests | Cambio mínimo | Sin diagnóstico operacional consistente |
| Balanceado: recorder local acotado, runner y CLI instrumentados | Sin red ni dependencias; privacidad comprobable | Persistencia/retención a cargo del operador |
| Enterprise: colector distribuido, tracing y servicio | Operación centralizada | Infraestructura y exposición fuera del modelo actual |

Se elige el balanceado. El contrato `operations-v1` contiene sólo enums, contadores,
duraciones y un ID opaco UUID de correlación. Un assessment ID es opcional y validado;
no se deriva un hash de entradas sensibles. Nunca se aceptan etiquetas arbitrarias,
mensajes de excepción, nombres de servicios, URLs o credenciales. Los eventos son una
ventana acotada; las métricas agregadas registran descartes. Tiempo/IDs operacionales
quedan fuera de la serialización de evidencia.

La espera del lock consume el presupuesto del request y expira sin abrir el provider.
Cancelación/deadline siguen siendo cooperativos: no se puede matar Python bloqueado,
DNS o SDKs arbitrarios. El proceso host debe imponer su límite duro externo.
No hay retries automáticos nuevos; se miden los intentos adicionales del cliente
Zabbix existente. El runner no introduce una política de reintentos propia.

Lecturas acotadas antes del parseo y límites de estructura YAML evitan crecimiento
ilimitado. La sonda usa fixtures sintéticas, mide percentiles y memoria Python y
verifica determinismo y fallo cerrado; no se confunde memoria Python con RSS.

## Risks / Trade-offs

Los SLO son objetivos internos para workloads documentados, no disponibilidad de un
servicio. La sonda no certifica proveedores reales ni permisos remotos. IDs opacos
proporcionados por el operador deben estar aprobados como no sensibles. Se cuantifica
la ventana de eventos, caché, inputs, timeout y presupuesto de errores en el runbook.

## Migration Plan

Activación explícita de telemetría; sin flag, mismos reportes. Archivos operacionales
nuevos mediante creación exclusiva, sin sobrescribir evidencia. Fallo de persistencia
solicitada produce código 2. Evolución aditiva compatible o nueva versión del contrato.
Rollback por PR, sin restaurar dependencias vulnerables ni eliminar evidencia histórica.

## Validation

Pruebas positivas, negativas/adversariales, privacidad, compatibilidad, fallos de
provider, cola concurrente, replay y límites. Sonda medida, pytest con cobertura >=85%,
Ruff, mypy, packaging reproducible, Twine y CI completo antes del cierre.
