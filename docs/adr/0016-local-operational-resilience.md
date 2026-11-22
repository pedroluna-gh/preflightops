# ADR 0016 — Observabilidad local y resiliencia acotada

Estado: aceptado para la etapa 16, sujeto a validación y CI del cambio.

## Decisión

| Opción | Ventaja | Limitación |
| --- | --- | --- |
| Conservadora: runbooks y tests | Mínima superficie | Diagnóstico sin contrato consistente |
| Balanceada: recorder local y límites del proceso | Offline, sin dependencias nuevas, privacidad verificable | El operador conserva y elimina los artefactos |
| Enterprise: servicio y colector remoto | Operación centralizada | Infraestructura, permisos y exposición fuera de alcance |

Se adopta la opción balanceada. `operations-v1` acepta únicamente enums, números e
identificadores opacos aprobados. La redacción es por exclusión: no existe un campo
para payload, mensaje remoto, URL, servicio, usuario o etiqueta libre. La correlación
no se convierte en etiqueta de métricas. Los relojes y el UUID operacional no entran
en hashes, IDs ni serialización del Assessment Contract.

El runner sigue serializado y cooperativo. El timeout ahora incluye la espera por
el lock; el request que expira no toca el lifecycle de la ejecución activa. Se mide
el retry read-only existente de Zabbix sin ampliar su política. GCP y el runner no
introducen retries. No hay servicio nuevo ni afirmación de HA o SLA contractual.

## Compatibilidad, privacidad y rollback

El CLI mantiene outputs y códigos legacy; la telemetría sólo aparece mediante
`--telemetry-output` y usa creación exclusiva. Un fallo al persistir lo solicitado
devuelve 2. Inputs excesivos se rechazan antes de construir objetos. Los límites y
su migración están en [el runbook](../OPERATIONS_RUNBOOK.md).

Los registros operacionales son metadatos internos aunque no contengan payloads.
No se exportan automáticamente. Para rollback se retira el flag y se revierte sólo
este cambio por PR verificado, conservando evidencia e inputs privados y manteniendo
las correcciones de dependencias de #53 y workflows de #54.

Riesgos: cancelación cooperativa no interrumpe código arbitrario; no hay recuperación
de inputs que el operador no guardó; la medición sintética no valida proveedores
reales. Los SLO se aplican al workload documentado, no al rendimiento de sistemas externos.
