## 1. Contratos y brechas

- [x] Leer índice y prompt 14 completos; verificar cierre post-merge de etapa 13.
- [x] Inspeccionar implementación, contratos y pruebas existentes; registrar ADR.
- [x] Cerrar validación ambigua y verificar alineación schema/runtime.

## 2. Gobierno reproducible

- [x] Simular política activa con claves explícitas y timestamp reproducible.
- [x] Evaluar fail-open/fail-closed por error sin aprobación automática.
- [x] Verificar versionado, contexto, conflictos, waivers y decision record.
- [x] Probar rollback e invariancia de resultados históricos.

## 3. Verificación y publicación

- [x] Pruebas positivas, negativas, adversariales y compatibilidad.
- [x] Suite completa, cobertura >=85%, Ruff, mypy, packaging y wheel limpio.
- [x] OpenSpec estricto y documentación de invariantes, privacidad y operación.
- [ ] Publicar rama y PR independientes; resolver hallazgos y exigir CI verde.
- [ ] Archivar, fusionar y verificar post-merge; registrar riesgos y rollback.
