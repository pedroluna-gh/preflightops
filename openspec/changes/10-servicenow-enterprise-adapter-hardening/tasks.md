# Tareas

## 1. Contrato y preview

- [x] 1.1 Implementar mapping v2 estricto y sin YAML aliases/includes.
- [x] 1.2 Implementar plan, canonicalización, IDs y digests determinísticos.
- [x] 1.3 Añadir schema del plan y helper de dual preview v1/v2.

## 2. Transporte y seguridad

- [x] 2.1 Implementar transporte desacoplado, no-redirect y timeouts.
- [x] 2.2 Implementar OAuth client credentials y policy URL/DNS/proxy/mTLS.
- [x] 2.3 Implementar redacción de errores/eventos sin target ni secretos completos.

## 3. Ejecución enterprise

- [x] 3.1 Implementar lookup read-only y target pinning Change API.
- [x] 3.2 Implementar gateway capability, enrich, CAS, idempotencia y read-back.
- [x] 3.3 Implementar draft detrás de mapping + feature flag, off por defecto.
- [x] 3.4 Implementar retries, rate-limit y reconciliation fail-closed.

## 4. Verificación y operación

- [x] 4.1 Añadir unit, integration-mock, contract, adversarial y regression tests.
- [x] 4.2 Publicar runbook, sandbox separado, migración y rollback.
- [x] 4.3 Ejecutar suite, cobertura, Ruff, mypy, OpenSpec y packaging.
- [ ] 4.4 Registrar CI, riesgos residuales y evidencia verificable.
- [ ] 4.5 Archivar OpenSpec sólo después de CI verde.
