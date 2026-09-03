## 1. Contrato y modelo

- [x] 1.1 Implementar errores y límites tipados del plan; verificar versiones, forma,
  profundidad, nodos, bytes y cantidad de recursos con tests negativos.
- [x] 1.2 Implementar modelos inmutables de plan/resource change y acciones canónicas;
  verificar create/read/update/delete/ambos replaces y acciones desconocidas.
- [x] 1.3 Aplicar máscaras sensitive antes de reglas; verificar que secretos no aparecen
  en findings, excepciones ni serialización de evidencia.

## 2. Motor de reglas estructurales

- [x] 2.1 Implementar catálogo declarativo IAM/red/DNS/KMS/database multi-cloud;
  verificar casos AWS, Azure y GCP positivos y negativos.
- [x] 2.2 Implementar exposición pública por paths/predicados permitidos; verificar CIDR,
  booleanos, negaciones, unknown y sensitive.
- [x] 2.3 Normalizar y ordenar findings con address/provider/type/action/evidence;
  verificar determinismo ante permutación de recursos.

## 3. Compatibilidad y corpus

- [x] 3.1 Preservar `scan_terraform` legacy sin fallback silencioso; verificar suite legacy,
  CLI y risk engine focalizados.
- [x] 3.2 Añadir fixtures sanitizados y matriz de precisión; verificar 100% precision/recall
  sobre el corpus conocido y un plan grande dentro de límites.
- [x] 3.3 Documentar contrato, límites, migración, privacidad, limitaciones y rollback;
  verificar enlaces y ejemplos con tests de documentación existentes.

## 4. Quality gates y cierre

- [x] 4.1 Ejecutar tests focalizados positivos, negativos, adversariales y compatibilidad;
  registrar el resultado sin omitir fallos.
- [x] 4.2 Ejecutar suite completa, cobertura >=85%, Ruff y mypy; corregir todo hallazgo.
- [x] 4.3 Validar wheel/sdist con build y twine y comprobar instalación/import limpio.
- [x] 4.4 Validar OpenSpec en modo strict, registrar evidencia/riesgos/rollback y archivar
  únicamente cuando todos los criterios de salida estén demostrados.
