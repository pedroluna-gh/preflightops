# Etapa 11 — evidencia local

Fecha: 2026-09-08. Estado: implementada y validada localmente; publicación y CI
pendientes. No constituye cierre de la etapa ni evaluación de madurez 5/5.

## Alcance comprobado

Contrato inmutable v1 y schema estricto, serialización canónica, referencia Fake,
lifecycle explícito read-only, credenciales inyectadas, caché acotada y contextual,
freshness, cancelación cooperativa, fallos parciales y agregación determinística.
El motor consume la proyección común y mantiene el resultado legacy intacto.
No se añadieron SDK ni integraciones de Zabbix/GCP.

La revisión adversarial corrigió un fallo terminal después de emitir todos los
controles: invalida ahora el lote completo y nunca se guarda como éxito en caché.
FAIL/ERROR vencidos conservan el estado negativo y confianza cero.

## Verificaciones

Entorno: Windows, Python 3.12.14, entorno local del proyecto.

| Control | Resultado |
| --- | --- |
| Suite completa final | 775 pruebas aprobadas en 73,89 s |
| Cobertura de líneas y ramas combinada | 85,77 %, umbral 85 % |
| Suite focalizada providers y contratos | 92 pruebas aprobadas |
| Ruff lint | Sin hallazgos |
| Ruff format | 55 archivos conformes |
| mypy | Sin errores en 26 módulos |
| OpenSpec validate --all --strict | 7 elementos aprobados, 0 fallos |
| Build sin aislamiento | Wheel y sdist construidos |
| Twine check | Ambos paquetes válidos |
| Wheel instalado en directorio aislado | Import y ejecución FakeProvider aprobados |

Reproducción desde la raíz del repositorio:

```text
python -m pytest --cov=preflightops --cov-report=term --cov-fail-under=85 -q -p no:cacheprovider
python -m ruff check preflightops tests
python -m ruff format --check preflightops tests
python -m mypy preflightops
openspec validate --all --strict
python -m build --no-isolation --outdir .package-check/phase11
python -m twine check .package-check/phase11/*
```

Desactivar telemetría de OpenSpec con OPENSPEC_TELEMETRY=0. El smoke de wheel
se realizó con instalación --no-deps --no-index en .package-check/phase11-installed,
Python aislado y verificación de que el módulo importado provenía de ese directorio.
Los paquetes son artefactos locales de validación; no una nueva release publicada.

## Pendientes de cierre

- Cargar los archivos en stage-11-evidence-provider-contract, creada desde main.
- Abrir PR y comprobar el diff contra el alcance de esta etapa.
- Obtener CI completo verde, resolver hallazgos y registrar SHA/runs.
- Promover y archivar la especificación sólo después de cumplir los controles.
- Fusionar según aprobación aplicable y verificar CI posterior a la fusión.

## Riesgos residuales y rollback

Cancelación y timeout son cooperativos; no aíslan código no confiable. La espera
por el bloqueo del runner queda fuera del timeout de ejecución. El consumidor
debe delimitar su cola y proporcionar tiempos y digests aprobados, incluyendo
tenant/alcance de autorización en el contexto de caché.

La redacción de datos requiere una proyección aprobada por cada adapter; el filtro
de cadenas no es una garantía universal contra secretos. El schema estructural
no reemplaza al decoder semántico. N/A se proyecta conservadoramente a UNKNOWN
en el Trust Kernel v1. CLI/Action no invocan estos providers automáticamente.

Rollback: retirar la llamada a assess_risk_with_provider_evidence y continuar con
assess_risk; conservar los contratos ya emitidos para auditoría. No hay cambios
en servicios externos ni migraciones destructivas.
