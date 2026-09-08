# Evidence Providers v1

La API pública es aditiva: `ProviderEvidence`, `parse_provider_evidence`,
`ProviderCapabilities`, `ProviderRequest`, `ProviderContext`, `EvidenceProvider`,
`ProviderRunner`, `ProviderExecutionError`, `FakeProvider`, `ProviderAggregate`,
`aggregate_provider_evidence`, `assess_risk_with_provider_evidence` y
`ProviderContractError`.

## Contrato y validación

`schemas/provider-evidence-v1.schema.json` define la estructura estricta. El decoder
Python exige todos los campos, incluidos null explícitos, UTC canónico sin fracciones,
intervalo temporal positivo y resúmenes acotados. Validar sólo JSON Schema no sustituye
la validación semántica. Estados: PASS, FAIL, UNKNOWN, ERROR y NOT_APPLICABLE.
ERROR/UNKNOWN tienen confianza cero y categoría de error obligatoria. N/A requiere
justificación y no constituye evidencia positiva. No se admiten extensiones sin versionar.

La serialización JSON canónica y SHA-256 se calculan únicamente sobre la proyección
aprobada. Un digest demuestra identidad de contenido, no autenticidad de un proveedor.
No se firman ni verifican credenciales a través de este contrato.

## Uso del runtime

1. Registrar explícitamente un adapter y sus capabilities read-only.
2. Construir ProviderRequest con controles, evaluated_at, timeout y digests aprobados
   de contexto/configuración. El contexto debe identificar tenant y alcance de acceso.
3. Ejecutar ProviderRunner.run con supplier de credenciales y Event de cancelación.
4. El adapter implementa open/collect/close y usa context.remaining() antes de cada
   operación bloqueante y como timeout del transporte.
5. Agregar contra una lista explícita de identidades esperadas. Controles ausentes
   quedan UNKNOWN; duplicados e identidades extra se rechazan.
6. Consumir mediante assess_risk_with_provider_evidence. El resultado contiene legacy
   intacto y Assessment v1 con controles adicionales y límite de confianza.

La caché tiene capacidad 0–1024, está serializada por runner y sólo conserva resultados
completos concluyentes. La clave liga proveedor/versión, configuración, contexto y
controles. Cambiar credenciales con distinto alcance exige cambiar context_digest.
No compartir un runner entre dominios de autorización sin esa separación.

## Fallos y límites

TIMEOUT, CANCELLED, AUTH, RATE_LIMIT, UNAVAILABLE, INVALID_RESPONSE e INTERNAL son
fallos de ejecución. MISSING, STALE y FUTURE explican ausencia o degradación temporal.
Las excepciones remotas nunca se copian al contrato. Un fallo parcial conserva controles
ya obtenidos; timeout/cancelación invalida la respuesta completa. La limpieza de recursos
se ejecuta incluso tras errores de apertura o recolección. Si el proveedor falla después
de emitir todos los controles, se invalida el lote completo: el fallo terminal no puede
desaparecer porque no queden controles pendientes.

Cancelación es cooperativa. El proceso no puede matar código arbitrario ni garantizar
que un adapter incumplidor termine: usar procesos aislados y límites de red cuando el
adapter no sea confiable. La serialización del runner no es un scheduler distribuido;
el deadline empieza al adquirir el runner, no incluye espera en su bloqueo. Los
consumidores que necesiten un límite global deben limitar también su cola de trabajo.

El Trust Kernel v1 no representa N/A: su proyección usa UNKNOWN conservadoramente.
El agregado retiene N/A y su justificación. El riesgo se calcula por reglas existentes;
confidence no modifica puntos ni autoriza una decisión humana.

## Privacidad, pruebas y rollback

Nunca guardar tokens, headers, cuerpos remotos ni URLs firmadas. Resúmenes y referencias
opacas son responsabilidad del adapter; el filtro inline es defensa adicional limitada.
El FakeProvider no consulta red ni credenciales. La suite reutilizable inicial está en
tests/test_provider_runtime.py (`assert_provider_contract`); cada adapter real debe
añadir pruebas propias de autorización, paginación, límites y redacción.

Rollback: retirar la llamada aditiva y continuar con assess_risk. Conservar artefactos
previos para auditoría. CLI/Action no se conectan automáticamente a providers y no hay
dependencias Zabbix/GCP en el núcleo. Véase ADR 0010 para alternativas y riesgos.
