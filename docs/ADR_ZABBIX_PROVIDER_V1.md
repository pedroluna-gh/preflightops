# ADR — Evidence Provider Zabbix v1

Estado: implementada y validada en CI del PR #49; archivo y fusión en curso.
Alcance: etapa 12; no proveedor GCP ni cambios en decisiones humanas.

## Opciones

| Diseño | Ventaja | Coste |
| --- | --- | --- |
| Conservador: exportación offline | Sin transporte remoto | No consulta estado actual |
| Balanceado: cliente JSON-RPC aislado | Lectura verificable y límites explícitos | Mantener protocolo y fixtures |
| Enterprise: gateway independiente | Aislamiento y cuotas centralizados | Infraestructura adicional |

## Decisión

Adoptar el diseño balanceado: transporte HTTPS fijado a una IP aprobada,
autenticación token-only por familia de versión y siete métodos permitidos.
Un provider por host proyecta seis controles al contrato común de evidencia.
El motor de riesgo no importa el cliente; no hay consultas implícitas en CLI/Action.

La composición conserva outputs legacy. Se permiten referencias opacas y resúmenes
estáticos; no cuerpos remotos ni secretos. El inventario esperado hace explícitas
las ausencias. ERROR y UNKNOWN nunca se convierten en PASS por falta de resultados.

Freshness de muestras usa lastclock y limita la vigencia por la muestra más antigua.
Los mantenimientos directos y por grupo se consultan separadamente; la revisión
del filtro hostids demostró que no incluye por sí solo asignaciones a grupos.
Una definición recurrente superpuesta no se interpreta como ocurrencia efectiva.

## Trade-offs

- Un alias de procedencia no prueba permisos completos; los valida el operador.
- La API no ofrece snapshot atómico entre estas consultas. Cambios contradictorios
  se rechazan cuando son detectables, sin prometer consistencia transaccional.
- IP pinning evita resolución implícita y destinos inesperados, pero exige rotación.
- Rate limiting es por cliente; cuotas globales corresponden al consumidor.
- Selecciones, páginas y bytes acotados pueden generar UNKNOWN/ERROR en entornos
  extensos. Se debe ajustar el alcance, no ocultar truncación.
- El sandbox es separado; mocks y CI no prueban una instalación Zabbix real.

## Evidencia, migración y rollback

Suite reusable del Provider Contract v1 y fixtures 6.0/7.0/7.4 en
tests/test_zabbix_provider.py. Protocolo y transporte tienen suites separadas.
Resultados de gates en openspec/changes/archive/2026-09-08-12-zabbix-readonly-provider/evidence.md;
el PR #49 registra la verificación del head final y de la fusión.
Runbook, límites, permisos y procedimiento sandbox en ZABBIX_PROVIDER_V1.md.
Retirar la selección del provider restaura el flujo anterior sin borrar artefactos;
un operador revoca token/egress cuando corresponda. No se crean objetos remotos.

## Referencias primarias

- [Maintenance API 7.0](https://www.zabbix.com/documentation/7.0/en/manual/api/reference/maintenance/get)
- [Implementación de filtros 7.0](https://github.com/zabbix/zabbix/blob/release/7.0/ui/include/classes/api/services/CMaintenance.php)
- [API 6.0](https://www.zabbix.com/documentation/6.0/en/manual/api)
- [API 7.4](https://www.zabbix.com/documentation/7.4/en/manual/api)
