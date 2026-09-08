# Diseño Zabbix

## Decision

| Opción | Ventaja | Coste |
| --- | --- | --- |
| Conservadora: inventario exportado | Sin transporte remoto | No demuestra estado actual |
| Balanceada: JSON-RPC aislado y proyección mínima | Control de permisos, versiones y límites | Mantener cliente y mocks |
| Enterprise: gateway de evidencia independiente | Aislamiento central | Infraestructura y operación adicionales |

Se elige la balanceada. Transporte inyectable para tests; transporte HTTPS explícito
para uso autorizado, sin redirects ni proxies implícitos. No SDK en el motor.

## Contracts and semantics

Versión descubierta con apiinfo.version sin token. Familias iniciales 6.0, 7.0 y
7.4; otras fallan cerrado. 6.0 usa auth JSON-RPC; 7.x Authorization Bearer.
Sólo apiinfo.version, host.get, trigger.get, maintenance.get, problem.get,
event.get e item.get. No login, creación, actualización ni borrado.

Hosts seleccionados explícitamente por identificadores; existencia no garantiza
cobertura. Triggers e items deben coincidir con controles esperados. Resultados
vacíos no distinguen falta de permisos de inexistencia: UNKNOWN, nunca PASS.
Maintenance se interpreta con la ventana consultada y estado del host, sin afirmar
que todo intervalo activo es una ocurrencia efectiva de una regla recurrente.
Freshness de muestras usa lastclock comprobado; hora de consulta no sustituye la
hora de medición. Problems/events se acotan por tiempo y paginan por eventid.
Consultas sin cursor admitido usan lotes explícitos de IDs y límite con detección
de truncación; nunca inventar un parámetro offset.

## Security and limits

Token suministrado durante cada llamada, no retenido ni representado. Ningún cuerpo
remoto, nombre de host, URL interna, descripción de trigger, valor de item o error
remoto se copia a evidencia. Referencias opacas aprobadas, resúmenes estáticos y
metadatos de versión constituyen la proyección permitida.
Timeout global cooperativo, backoff acotado y sólo reintentos de lecturas frente
a errores transitorios. Respuestas con IDs incorrectos, claves duplicadas,
JSON inválido, listas excesivas o paginación sin progreso fallan cerrado.

## Sources

- https://www.zabbix.com/documentation/6.0/en/manual/api
- https://www.zabbix.com/documentation/7.4/en/manual/api
- https://www.zabbix.com/documentation/7.0/en/manual/api/reference/host/get
- https://www.zabbix.com/documentation/7.0/en/manual/api/reference/trigger/get
- https://www.zabbix.com/documentation/7.0/en/manual/api/reference/maintenance/get
- https://www.zabbix.com/documentation/7.0/en/manual/api/reference/problem/get
- https://www.zabbix.com/documentation/7.0/en/manual/api/reference/event/get
- https://www.zabbix.com/documentation/7.0/en/manual/api/reference/item/get
- https://docs.python.org/3/library/http.client.html
- https://docs.python.org/3/library/ssl.html

## Residual risks and rollback

Las APIs no prueban por sí solas que los permisos cubran todo el entorno. Se exige
inventario esperado y alcance de rol documentado. Mocks no sustituyen validación
de un sandbox real; ésta no se declarará ejecutada sin acceso autorizado.
Desactivar el provider restaura la operación anterior sin migración destructiva.
