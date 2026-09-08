# Zabbix Evidence Provider v1 — operación y límites

Estado: implementación de etapa 12 validada en CI del PR #49; fusión pendiente.
API Python aditiva; no activa consultas desde CLI, Action ni importaciones.
Contrato de salida: ProviderEvidence v1, adapter `zabbix` versión `1.0.0`.

## Configuración y uso explícito

Construir `ZabbixEndpoint` con URL HTTPS terminada en `api_jsonrpc.php`, IP
numérica aprobada y opcional CA corporativa. La conexión usa la IP fijada y
verifica el certificado contra el hostname de la URL. No hay DNS, proxies,
redirects ni opción TLS insegura. Una IP privada requiere `allow_private=True`;
loopback, link-local y destinos de metadata siguen prohibidos.

`ZabbixConfig` exige un alias opaco aprobado `source_reference`, un `host_id` y
tuplas ordenadas numéricamente, únicas, de `trigger_ids` e `item_ids` esperados.
Una selección vacía no equivale a cobertura: produce UNKNOWN en su control.
Los IDs y el endpoint son configuración interna; no publicar su contenido.

Crear `ProviderRequest` con `configuration_digest=config.digest`, un
`context_digest` aprobado y timestamp UTC explícito. Seleccionar controles desde
`provider.capabilities.controls`. Invocar `ProviderRunner.run` con el provider,
request y un `credentials` callable que lea el token de un almacén protegido.
No pasar tokens por argumentos CLI ni registrar el valor retornado. No guardar
tokens en `ZabbixConfig`. La construcción de objetos no consulta Zabbix.

La identidad del contexto debe incluir una referencia no sensible a la versión
de permisos del principal. Al cambiar permisos o principal, renovar contexto y
runner/caché; no reutilizar evidencia de un ámbito de acceso anterior.
El digest de configuración identifica destino, selección y presupuestos, pero
no demuestra que el operador haya aprobado su contenido. Conservarlo como
metadato interno; un hash no anonimiza entradas de baja entropía.

## Controles independientes

| Sufijo del alias | Evidencia limitada que representa |
| --- | --- |
| host | El host esperado es visible y está habilitado; no prueba cobertura |
| triggers | Triggers esperados visibles, habilitados y con estado conocido |
| maintenance | Estado efectivo del host y definiciones visibles relevantes |
| problems | Problemas no resueltos creados dentro del intervalo configurado |
| events | Eventos de problema de triggers dentro del intervalo configurado |
| freshness | lastclock de todos los items esperados, nunca su valor |

Un resultado PASS no aprueba despliegues ni modifica el score. Los errores de
consulta son ERROR con confianza cero; objetos esperados ausentes son UNKNOWN.
Un host deshabilitado impide evidencia favorable de triggers, eventos y muestras.
Triggers deshabilitados o de estado desconocido impiden interpretar una lista
vacía de eventos como favorable. Un problema anterior al intervalo puede seguir
activo: el control problems no afirma ausencia histórica/global de problemas.

Un intervalo `active_since`/`active_till` que se superpone no prueba una ocurrencia
de mantenimiento recurrente: se informa UNKNOWN si el host no confirma estado
efectivo. El inventario visible no demuestra permisos completos sobre el entorno.
Se consultan por separado asignaciones directas al host y asignaciones a sus
grupos (hasta 100 grupos). El filtro groupids también puede devolver mantenimiento
de otros hosts: sólo se incorpora cuando la asignación al grupo está confirmada.
Respuestas contradictorias entre ambas lecturas fallan cerrado. La ausencia de
grupos o una lista malformada impide PASS. En 6.0 se usa selectGroups; en 7.x,
selectHostGroups. Los IDs de grupos no se copian a evidencia.

`collected_at` representa el instante de evaluación explícito del request, no
una hora de medición inventada. La vigencia general dura como máximo el TTL;
freshness vence además al alcanzar `min(lastclock) + max_sample_age`.
Muestras futuras, ausentes o vencidas nunca se convierten en PASS por consultar
la API de nuevo. Mismos fixtures, contexto y configuración producen bytes iguales;
una API viva puede cambiar entre consultas y no es un snapshot transaccional.

## Presupuestos

| Parámetro | Default | Rango |
| --- | --- | --- |
| ttl_seconds | 60 | 1–3600 |
| max_sample_age | 300 | 1–86400 |
| lookback_seconds | 3600 | 1–604800 |
| page_size | 100 | 1–1000 |
| max_pages | 5 | 1–20 por consulta paginada |
| max_response_bytes | 1048576 | 256–4194304 |
| retries | 2 | 0–3 |
| min_interval_ms | 100 | 1–10000 |

Timeout global del request: máximo 120 segundos. El intervalo se aplica a cada
intento por instancia de cliente, incluso retries; no es un rate limiter global.
Serializar ejecuciones y ajustar concurrencia en el consumidor. Con todos los
controles se realizan como máximo `13 + 2 * max_pages` llamadas lógicas, cada
una con hasta `1 + retries` intentos. El deadline puede interrumpir antes.
429/502/503/504 permiten backoff acotado; no hay reintento ilimitado.

Problems/events usan cursor `eventid_from` inclusivo, avanzando al último ID + 1.
Repetición, desorden, datos fuera de ámbito/tiempo o agotamiento de páginas
producen ERROR. No se inventa offset. Hosts/items/triggers usan IDs explícitos y
un elemento adicional como detector de truncación. Nunca se pide output extend.
La cancelación es cooperativa; una lectura bloqueada queda limitada por deadline,
no por terminación forzada del proceso.

## Mínimo privilegio

1. Un operador crea un principal exclusivo de lectura y un token con expiración.
2. Restringir grupos de hosts al inventario aprobado, sin permisos de escritura.
3. En el rol API permitir únicamente `host.get`, `trigger.get`, `maintenance.get`,
   `problem.get`, `event.get`, `item.get`; discovery usa `apiinfo.version` sin token.
4. Denegar métodos de mutación, login programático y privilegios administrativos
   innecesarios. No ampliar permisos automáticamente para resolver un error.
5. Verificar con el administrador que la selección esperada queda visible y
   documentar el alcance del rol. Una respuesta vacía no demuestra autorización.
6. Restringir egress al destino aprobado y almacenar el token fuera de artefactos.

Familias admitidas: 6.0 (auth JSON-RPC), 7.0 y 7.4 (Authorization Bearer).
Otras versiones fallan antes de enviar credenciales. La documentación 7.0 permite
`maintenance.get` a cualquier tipo de usuario, sujeto a restricciones del rol;
no requiere asumir un usuario Super admin.
[Referencia oficial](https://www.zabbix.com/documentation/7.0/en/manual/api/reference/maintenance/get).

## Privacidad y sandbox separado

Sólo resúmenes estáticos, versión de API, alias aprobado, estado y tiempos salen
como evidencia. No se copian URLs, tokens, descripciones, nombres de hosts,
valores de items ni mensajes remotos. No habilitar wire logging, tracing de cuerpos
ni dumps de variables locales en el consumidor; contienen material transitorio.

Los tests usan transporte y sockets simulados. No se ejecutó un sandbox real.
Para validarlo por separado, obtener autorización de una instancia no productiva,
usar principal mínimo, ejecutar sólo las lecturas listadas y verificar en auditoría
que no hubo mutaciones. Probar roles incompletos, token revocado, mantenimiento,
item vencido y host deshabilitado. Registrar sólo evidencia redactada. Revocar
el token de prueba al terminar; no convertir este procedimiento en CI productiva.

## Migración y rollback

No modifica contratos legacy, sinks ni decisiones humanas. Adoptar primero en
modo informativo sin blocking, con inventario y umbrales revisados por su dueño.
Rollback: dejar de seleccionar el provider y volver al flujo anterior; conservar
evidencia para auditoría. Un operador puede revocar el token y la regla egress.
Cambiar el pin ante rotación de IP exige revisar configuración y renovar digest.
No hay objetos remotos creados por este provider que deban borrarse.
