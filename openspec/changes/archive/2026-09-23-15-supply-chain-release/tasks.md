## 1. Baseline

- [x] Leer índice y etapa 15; verificar cierre post-merge de etapa 14.
- [x] Inspeccionar workflow de release, CI, lock strategy y documentación.
- [x] Contrastar controles remotos y completar inventario de brechas.

## 2. Implementación

- [x] Implementar y probar bundle verificable, SBOM y checksums offline.
- [x] Probar builds repetibles y clean-install del artefacto de release.
- [x] Integrar gates en CI/release preservando permisos mínimos y SHA pinning.
- [x] Verificar secret scanning, auditoría, licencias y excepciones acotadas.
- [x] Completar soporte, EOL, disclosure, SLA, checklist, migración y rollback.

## 3. Evidencia

- [x] Pruebas positivas, negativas, adversariales, compatibilidad y rollback.
- [x] Suite completa, cobertura, Ruff, mypy, OpenSpec, packaging y Twine.
- [x] Publicar PR exclusivo, resolver hallazgos y verificar CI completo.
- [ ] Archivar, fusionar, verificar post-merge y registrar riesgos residuales.

PR #52: los 14 checks del head inicial pasaron. El último punto requiere
verificación del head final y comentario de cierre post-merge; el archivo de
documentación no equivale por sí mismo al cierre de la etapa.
