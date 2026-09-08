# Diseño GCP

## Decision

| Opción | Ventaja | Coste |
| --- | --- | --- |
| Conservadora: exportaciones offline | Sin credenciales remotas | No demuestra alcance efectivo |
| Balanceada: APIs oficiales aisladas | Límites y redacción verificables | Mantener mapping y pruebas |
| Enterprise: gateway central | Cuotas y credenciales centralizadas | Infraestructura adicional |

Se elige balanceada. Las credenciales ADC se suministran explícitamente, no se
descubren al importar módulos ni construir configuración. Los tests no usan ADC
del equipo. El transporte/controlador sólo expone lecturas aprobadas, no un SDK
genérico al motor de riesgo. Una consulta exitosa no prueba todos los permisos.

## Scope and semantics

Un provider evalúa un proyecto elegido dentro de un allowlist inmutable. Todos
los nombres de recursos deben pertenecer a ese proyecto. Las métricas usan
filtros construidos con resource.labels.project_id además de metric.type y
resource.type: el metrics scope puede incluir otros proyectos. No se aceptan
expresiones arbitrarias que amplíen el alcance.

Policies habilitadas y objetos existentes son hechos separados de cobertura.
La selección esperada es explícita; vacío, denied, parcial o agotamiento de cuota
no significa PASS. Freshness usa timestamps demostrados, no la hora de consulta.
Asset Inventory se restringe a nombres/tipos esperados y proyecto, nunca a
organizaciones o carpetas. Identidad y scopes no demostrables quedan UNKNOWN.

## Privacy and determinism

Referencias públicas opacas aprobadas vinculan proyecto y principal sin publicar
IDs sensibles. Los digests identifican configuración, no anonimizan entradas
predecibles. No copiar métricas, labels, dashboards, filtros o errores remotos a
evidencia. Mismo fixture y contexto producen bytes iguales; la API viva no es
un snapshot transaccional. Timestamps y contexto son explícitos.

## References

- https://docs.cloud.google.com/monitoring/api/ref_v3/rest/v3/projects.timeSeries/list
- https://cloud.google.com/monitoring/settings/multiple-projects
- https://docs.cloud.google.com/monitoring/api/ref_v3/rest/v3/projects.alertPolicies/get
- https://google-auth.readthedocs.io/en/latest/reference/google.auth.credentials.html

## Residual risks

Mocks no demuestran permisos de una cuenta real. Sandbox no productivo requiere
autorización separada. Rotación de principal/permisos invalida el contexto/caché.
No afirmar identidad efectiva basándose sólo en metadatos suministrados por usuario.
