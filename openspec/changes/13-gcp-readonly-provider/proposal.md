# Provider GCP read-only

## Why

PreflightOps necesita evidencia GCP con identidad, proyecto y alcance explícitos,
sin convertir ausencia de permisos o métricas en una evaluación favorable.
La etapa 12 está cerrada en main 610f77cf86322a7ba4c36989a0f7d840d3b3e926;
PR #49 registra CI, seguridad, Scorecard y fuzzing posteriores aprobados.

## What Changes

- Provider Contract v1 aplicado a Monitoring y Asset Inventory acotado.
- Clientes/APIs oficiales con Application Default Credentials inyectadas.
- Allowlist de proyectos y selecciones de recursos/métricas verificables.
- IAM mínimo, límites de consultas, cuotas, timeouts y paginación explícitos.
- Mocks, contrato reusable, privacidad, runbook, migración y rollback.

## Scope

Sólo etapa 13: identidad/scope, policies, dashboards, uptime checks, services/SLOs,
freshness de series relevantes y Asset Inventory para controles definidos.
No recursos productivos, enumeración fuera del allowlist ni escrituras cloud.
No implementar etapas 14–18 dentro de este cambio.

## Compatibility

Adopción aditiva y explícita. El motor offline, CLI/Action y outputs legacy se
conservan. Se retira la selección del provider para rollback, preservando evidencia.
