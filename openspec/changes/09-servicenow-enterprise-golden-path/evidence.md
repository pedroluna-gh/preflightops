# Evidencia de implementación — etapa 09

Fecha local: 2026-09-03. Alcance exclusivo: diseño y threat model del golden path
ServiceNow enterprise. Esta etapa no implementa transporte ni realiza llamadas de red.

## Resultado local

- `pytest tests/test_servicenow_design_v2.py tests/test_contracts.py
  tests/test_servicenow_workflow.py tests/test_integrations.py -q`: 93 passed.
- `pytest --cov=preflightops --cov-branch --cov-report=term-missing -q`: 620 passed;
  86,57 % de cobertura branch-aware, sobre el mínimo de 85 %.
- `ruff check .`: verde; `ruff format --check .`: 242 archivos conformes.
- `mypy preflightops`: verde sobre 22 módulos.
- `openspec validate --all --strict`: 5/5 cambios y especificaciones válidos;
  `openspec doctor`: root y referencias correctos.
- `python -m build --no-isolation`: sdist y wheel `0.4.2` generados.
- `twine check`: sdist y wheel válidos.
- Instalación aislada del wheel, import con `python -I` y `preflightops --help`:
  verdes; el módulo se cargó desde `site-packages`, no desde el checkout.

## Evidencia de diseño

- El ADR compara explícitamente los diseños conservador, balanceado y enterprise, y
  selecciona el Evidence Gateway scoped para producción.
- Los tres schemas v2 son estrictos, versionados y se validan con ejemplos positivos y
  casos negativos/adversariales.
- Un live write v2 sólo puede dirigirse al gateway; el modo preview no necesita secretos
  ni red. Enriquecer exige target exacto y `sys_mod_count` esperado.
- El mapping cubre status, risk, confidence, assessment ID, policy, blockers, impact,
  automation details, evidence URL, commit y timestamp sin permitir campos de workflow.
- Idempotencia, CAS atómico, retries acotados, `Retry-After`, rate limits, reconciliación
  y estados de fallo parcial quedan especificados en el contrato del adapter.
- El threat model cubre SSRF, fuga por redirect/log, wrong-record, privilege escalation,
  replay y partial failure.
- CLI, Action, mapping, evidence y runtime v1 permanecen intactos; no hubo sockets,
  tokens ni escrituras ServiceNow en esta etapa.

## Evidencia remota pendiente

- CI completo de la rama/PR.
- Archivo/promoción OpenSpec posterior al primer CI verde.
- CI definitivo del PR y comprobación post-merge de `main`.

## Riesgos residuales

- El Evidence Gateway, ACL, índice único y modelos permitidos dependen de configuración
  específica de cada instancia.
- La producción debe decidir si el gateway y el índice único
  `u_preflightops_delivery_id` son obligatorios para todo live write.
- La política debe decidir si `create_draft` se compila desactivado por defecto o se
  excluye de la primera entrega v2. Ambas decisiones requieren aprobación humana antes
  de la etapa 10.
- Los contract tests no sustituyen ATF ni validación en una instancia sandbox compatible;
  esas pruebas pertenecen a la implementación futura.

## Rollback

Retirar schemas, ejemplos y documentación v2 devuelve el repositorio al baseline de la
etapa 08. El runtime v1 no cambia y permanece disponible; durante una futura migración,
el perfil v2 puede deshabilitarse y v1 conservarse en dry-run/read-only.
