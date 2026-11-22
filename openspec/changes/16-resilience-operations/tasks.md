## 1. Contratos y diseño
- [x] 1.1 Verificar cierre previo y comparar tres diseños sin cambiar permisos.
- [x] 1.2 Validar propuesta y escenarios OpenSpec estrictos.

## 2. Implementación
- [x] 2.1 Implementar recorder local versionado, acotado y sin payloads.
- [x] 2.2 Instrumentar CLI/runner preservando evidencia, caché y códigos legacy.
- [x] 2.3 Acotar espera concurrente y lecturas de inputs antes del parseo.

## 3. Evidencia operacional
- [x] 3.1 Verificar timeout, rate limit, corrupción, auth, parcialidad y outage.
- [x] 3.2 Medir carga, concurrencia, replay, memoria y latencia con fixtures offline.
- [x] 3.3 Documentar SLO/error budget, runbooks ejecutables, privacidad y recuperación.

## 4. Cierre
- [x] 4.1 Ejecutar suite completa, cobertura, Ruff, mypy y packaging.
- [ ] 4.2 Publicar PR descriptivo, resolver hallazgos y exigir CI verde.
- [ ] 4.3 Registrar evidencia final, riesgos residuales y rollback; archivar sólo al verificar.
