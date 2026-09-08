# Contrato común de Evidence Providers

## Why

El motor necesita consumir evidencia normalizada sin depender de SDKs, credenciales
ni detalles de Zabbix o GCP. La ausencia o caducidad de evidencia debe permanecer visible.

## What Changes

- Contrato v1 estricto con identidad, control, estado, referencias, tiempos,
  confidence, taxonomía de errores y metadatos de redacción.
- Lifecycle read-only con capacidades, configuración validada, cancelación y deadlines.
- Caché acotada, aislada por contexto y sin reutilizar evidencia vencida.
- Agregación reproducible con fallos parciales explícitos y adaptador al Trust Kernel.
- Fake provider y suite contractual reutilizable.

## Scope

Sólo la etapa 11. No implementar providers Zabbix/GCP ni contactar sistemas externos.
Credenciales se inyectan durante la ejecución y no forman parte de contratos o caché.

## Compatibility and rollback

API aditiva; inputs y outputs legacy permanecen. Desactivar el consumo del contrato
restaura el camino anterior sin migración destructiva ni eliminación de evidencia.
