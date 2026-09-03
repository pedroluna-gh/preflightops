# Evidencia de implementación — etapa 06

Fecha local: 2026-09-03. Alcance exclusivo: parser estructural de manifiestos
Kubernetes. No se modificaron el parser Terraform, umbrales globales, contratos
de aprobación humana ni integraciones remotas.

## Resultados locales verificables

- Pruebas focalizadas finales: 159 casos de parser, compatibilidad, CLI,
  changed-files y risk engine exitosos; 60 casos directos Kubernetes/CLI en la
  repetición final focalizada.
- Suite completa: 540 pruebas exitosas en Python 3.12.13 sobre Windows.
- Cobertura branch-aware: 87,57%, superior al gate de 85%; módulo
  `kubernetes_manifest.py`: 95%.
- Ruff check y format check: exitosos sobre 146 archivos.
- mypy: 20 módulos sin hallazgos.
- Build sin aislamiento: wheel y sdist 0.4.2 exitosos.
- Twine check: wheel y sdist exitosos.
- Instalación `--no-index --no-deps` e import desde target limpio: exitosos;
  smoke test de Secret estructural sin exposición de su valor exitoso.
- OpenSpec `validate --strict` y `doctor`: exitosos antes de publicación.
- Rama exclusiva: `stage-06-kubernetes-structural-parser`; PR
  [#43](https://github.com/pedroluna-gh/preflightops/pull/43).
- Head validado: `a1078c3d4cff71461c88ddf3888665c44786639e`.
- CI remoto del head: `CI` #124, `Security` #65 y `Fuzzing` #22 concluyeron
  exitosamente. Esto incluye `Required`, cinco matrices OS/Python, tres
  auditorías de dependencias, quality gates, contrato del Action, Dependency
  Review, CodeQL y ClusterFuzzLite.
- Hallazgo de CI resuelto: el contrato hermético del Action heredaba la
  autodetección de archivos del propio PR, por lo que el fixture LOW podía
  incorporar manifiestos adversariales. Los escenarios LOW/CRITICAL ahora fijan
  `auto-detect-changes: false`; una prueba de contrato impide la regresión. La
  autodetección productiva y sus pruebas permanecen habilitadas.

## Invariantes demostrados

- YAML inválido, objetos incompletos, claves duplicadas/no string, tags o merge
  keys no admitidos, aliases recursivos y límites excedidos producen error
  tipado, sanitizado y sin resultados parciales.
- Comentarios, texto libre y campos de otro objeto/container no constituyen
  evidencia; no existe fallback automático al scanner textual.
- Cada finding estructural contiene identidad del objeto, campo y predicado;
  los containers afectados quedan identificados individualmente.
- Reordenar el mismo conjunto semántico de objetos produce findings serializados
  byte-a-byte iguales.
- `data` y `stringData` de Secret se eliminan antes de las reglas y sus
  marcadores no aparecen en modelos, findings ni errores.
- El análisis core completa aun cuando la creación de sockets está bloqueada.
- `scan_kubernetes_legacy` preserva la forma, ids, scores y severidades
  históricas y nunca se invoca por error desde la ruta estructural.

## Riesgos residuales

- No se validan schemas OpenAPI por versión ni semántica específica de CRDs.
- No se conoce estado live, admission policy, endpoints, selectores efectivos ni
  la interacción combinada de NetworkPolicy y PodDisruptionBudget.
- Un hecho sensitive descartado no puede sostener un finding positivo; los
  consumidores deben tratar ausencia de evidencia según su política de
  confidence, nunca como PASS implícito.
- La cobertura de kinds/campos es deliberadamente acotada y toda ampliación debe
  agregar fixtures versionados y mantener compatibilidad.
- La integración a `main` aún está pendiente; el CI completo del head del PR es
  verde y deberá repetirse si el archivo OpenSpec genera un nuevo head.

## Rollback

Fijar la versión anterior del paquete para restaurar el comportamiento previo.
Durante una migración Python controlada se puede seleccionar temporalmente
`scan_kubernetes_legacy`; el CLI y la Action deben seguir fallando cerrados ante
input inválido. No existe estado persistente, llamada de red ni dato externo que
reparar. Conservar manifiestos y resultados ya emitidos como evidencia histórica
sin reetiquetar errores como LOW/PASS.
