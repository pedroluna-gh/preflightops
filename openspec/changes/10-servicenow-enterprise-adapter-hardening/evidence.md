# Evidencia de implementación — etapa 10

Fecha local: 2026-09-03. Alcance: adapter ServiceNow v2 implementado y probado sin
contactar sandbox ni producción.

## Política aprobada

- Todo live write productivo requiere Evidence Gateway y delivery key única.
- `create_draft` queda compilado pero desactivado por defecto.

## Evidencia local

- Suite completa: 714 passed en Python 3.12.13.
- Cobertura statement/branch: 85,51%, por encima del gate 85%.
- Ruff format/check: verde; mypy sobre 23 módulos: verde.
- Suite focal ServiceNow v2/v1/contratos: 162 passed antes de la ampliación de casos;
  suite v2 final: 92 passed.
- Golden preview SHA-256:
  `d61d8ec46fe7227c1343e642a24ccb20e40e84e1447d9ae6ae9a63c5bca2ddbc`.
- OpenSpec strict: change válido.
- Wheel y sdist 0.4.2 construidos; Twine: ambos PASSED; import de wheel instalado en
  entorno limpio validó versión y API v2. El smoke oficial con dependencias se delega a
  CI porque el cache local offline no contenía la versión bloqueada de `cffi`.
- Cero llamadas ServiceNow/sandbox/producción; resolver, transporte, clock y credenciales
  fueron dobles inyectados.

## Evidencia remota pendiente

- CI inicial del PR, archivo/promoción OpenSpec, CI definitivo y comprobación de `main`.

## Riesgos residuales

- Gateway/ACL/índice único y ATF/E2E requieren una instancia sandbox preparada y
  autorización independiente.
- Validar DNS antes del envío reduce SSRF/rebinding, pero un despliegue real debe usar un
  resolver/proxy corporativo que fije la conexión al resultado validado.

## Rollback

Deshabilitar writes v2 y credenciales, conservar evidencia/reconciliation y volver a v1
exclusivamente dry-run/read-only. No borrar ni revertir automáticamente un Change.
