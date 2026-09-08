# Provider Zabbix read-only

## Why

PreflightOps necesita evidencia operacional verificable de Zabbix sin acoplar el
motor al protocolo remoto ni transformar ausencia de acceso en evidencia favorable.
La etapa 11 quedó fusionada en 3987aabef8fcf58a4adf3990217f51c83f068d3d y sus
controles posteriores a la fusión terminaron correctamente.

## What Changes

- Cliente JSON-RPC aislado y allowlist de métodos de lectura, autenticación con token.
- Configuración acotada, transporte HTTPS explícito y tratamiento por versión.
- Provider Contract v1 para hosts, triggers, maintenance, problems/events y freshness.
- Reintentos seguros, presupuestos de tiempo/respuesta/paginación y redacción.
- Mocks, suite contractual, pruebas adversariales y runbook de mínimo privilegio.

## Scope

Sólo etapa 12. No escrituras Zabbix, instancia productiva, proveedor GCP ni cambios
en decisiones humanas. El sandbox queda como procedimiento separado y autorizado.

## Compatibility and rollback

API aditiva y deshabilitada por defecto. Mantener CLI/Action y outputs legacy.
Rollback retira la selección del provider, conserva artefactos y revoca su token
desde el sistema de credenciales por un operador autorizado.
