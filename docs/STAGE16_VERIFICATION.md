# Verificación de etapa 16 — 2026-11-21

## Alcance y base

Resiliencia, observabilidad local y operación. Base: `main`
`0e5f47b0dc4b91721370ff00211c8dc81358c4ba`, después de #53 y #54. No se activan
integraciones ni se ejecutan etapas 17/18. Los cambios locales preexistentes en
contratos, ADR y especificaciones anteriores se conservan fuera de este cambio.

OpenSpec: `16-resilience-operations`; ADR 0016, schema `operations-v1`, pruebas y
[runbook](OPERATIONS_RUNBOOK.md). El diseño balanceado mantiene el core offline y
la telemetría separada de la evidencia reproducible.

## Evidencia local

Windows, Python 3.12.13; entorno congelado con el lock corregido en #53.

- **1,248 tests aprobados**, cobertura de ramas **87.71%**, 25.26 s.
- Ruff format/lint: **104 archivos**; mypy: **41 módulos**.
- OpenSpec strict: cambio activo y 11 especificaciones válidos.
- Fault injection: timeout, rate limit, auth expiry, outage, respuesta corrupta,
  parcialidad y freshness; caché no transforma incertidumbre en PASS.
- Concurrencia: 64 solicitudes sobre 8 workers, una recolección y 63 cache hits;
  una solicitud en cola con 20 ms de presupuesto expira sin tocar el provider activo.
- Privacidad/schema: categorías arbitrarias, payloads, labels libres, identificadores
  no aprobados y cifras inválidas rechazados. Secretos sintéticos no aparecen en telemetría.
- CLI legacy idéntico con/sin recorder; CRITICAL conserva código 1. Errores de
  persistencia, archivo existente y colisiones devuelven 2. `report render` enlaza
  el assessment ID validado sin generar uno para reportes legacy.
- Dos builds independientes byte-idénticos, Twine, inventario SBOM congelado y
  wheel instalado en entorno vacío con LOW/CRITICAL y telemetría aprobados.

| Artefacto local de verificación | SHA-256 |
| --- | --- |
| `preflightops-0.4.2-py3-none-any.whl` | `5ff35eea709a916a8a7dc344fbc638d0f79dc6d041b1dc41cb163aa72d9dda31` |
| `preflightops-0.4.2.tar.gz` | `733e77f00b0d92749b2afada38485a3355af9af0d06c802da296e9499df5df3c` |

Son builds de desarrollo de esta fuente; no una nueva release/tag 0.4.2 publicada.
La aprobación de licencias sigue pendiente y no se inventa procedencia autenticada.

## Medición reproducible como procedimiento

`python -m preflightops.operational_probe --iterations 100 --output probe.json`
con fixture LOW, warm, un proceso y `tracemalloc` activado:

| Medida | Resultado local | Objetivo |
| --- | --- | --- |
| p50 / p95 / máximo | 0.268 / 0.334 / 0.380 ms | p95 <=250 ms |
| Throughput | 3,582 evaluaciones/s | Se registra; sin promesa para otros workloads |
| Pico Python | 81,830 bytes | <=64 MiB |
| Diferencias de replay | 0 / 100 | 0 |
| Evidencia faltante | UNKNOWN/MISSING | Nunca PASS |

Las mediciones varían por host; el procedimiento y el resultado semántico son
reproducibles, no los cronómetros. Memoria Python no equivale a RSS. La sonda se
ejecuta también en CI y conserva su JSON sintético durante 7 días.

## Gate remoto y cierre

Antes del cierre se requieren el PR publicado, checks verdes sobre su head final,
verificación de los archivos remotos y evidencia enlazada en el PR. Este documento
registra resultados locales; no sustituye ese gate. El checklist OpenSpec conserva
pendientes los pasos que todavía requieren verificación remota.

## Riesgos residuales y rollback

- Deadlines cooperativos <=120 s: un adapter no cooperativo necesita timeout duro
  del supervisor; no hay terminación forzada de Python dentro del runner.
- 256 eventos por recorder y contadores hasta 2^53-1; consultar `events_dropped`.
  No hay recolector ni almacenamiento remoto. Retención local propuesta: 7 días.
- La caché tiene 32 entradas por defecto (máximo 1024); dimensionar memoria con
  controles y workload propios. El host limita su pool, no el runner.
- El objetivo de finalización >=99.9% en 30 días todavía no tiene muestra productiva;
  requiere al menos 1,000 ejecuciones clasificadas. No se afirma SLA ni madurez 5/5.
- UI de larga duración, proveedores reales y piloto permanecen fuera de esta sonda.
  Licencias y gobierno de release conservan sus gates previos.

Rollback: desactivar `--telemetry-output`, conservar evidencia y revertir sólo etapa
16 mediante un PR verificado. Mantener las dependencias corregidas de #53 y los pins
de workflows de #54. Eliminar la instrumentación no autoriza relajar el Trust Kernel
ni convertir ERROR/UNKNOWN en PASS. Recuperar desde wheel verificado e inputs/contexto
privados conservados siguiendo el runbook; sin esos inputs no hay replay fiel.
