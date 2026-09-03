# Tareas

## 1. Contrato y parser

- [x] 1.1 Implementar límites, errores tipados y modelo de objeto Kubernetes.
- [x] 1.2 Implementar carga multi-documento segura, claves duplicadas, aliases, ciclos
  y expansión acotada de List.
- [x] 1.3 Sanitizar Secret antes de exponer objetos a las reglas.

## 2. Reglas estructurales

- [x] 2.1 Implementar identidad y evidencia estable por objeto/campo.
- [x] 2.2 Evaluar workloads y containers individualmente, incluidas probes y recursos.
- [x] 2.3 Evaluar exposición, configuración peligrosa, estrategias y PDB sólo cuando
  pueda demostrarse desde el manifest.
- [x] 2.4 Ordenar findings de forma determinística.

## 3. Compatibilidad e integración

- [x] 3.1 Conservar el scanner textual como `scan_kubernetes_legacy` explícito.
- [x] 3.2 Integrar la ruta estructural en API, motor, CLI y changed-files sin fallback.
- [x] 3.3 Preservar ids, scores, umbrales y outputs legacy existentes.

## 4. Verificación

- [x] 4.1 Añadir fixtures multi-documento y pruebas positivas/negativas por kind.
- [x] 4.2 Añadir pruebas adversariales para comentarios, aliases, vacíos, YAML inválido,
  duplicados, límites, ciclos y Secret.
- [x] 4.3 Ejecutar pruebas focalizadas, suite completa, cobertura, Ruff y mypy.
- [x] 4.4 Validar build, twine e instalación/import limpios.

## 5. Documentación y cierre

- [x] 5.1 Documentar invariantes, privacidad, límites, migración y rollback.
- [ ] 5.2 Registrar evidencia, riesgos residuales y resultado de CI.
- [ ] 5.3 Validar y archivar el cambio OpenSpec antes de integrarlo.
