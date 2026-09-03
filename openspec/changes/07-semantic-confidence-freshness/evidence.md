# Evidencia de implementación — etapa 07

Fecha local: 2026-09-03. Alcance exclusivo: validación semántica, confidence y
freshness de rollback, monitoring y validation plans. No se modificaron scores
de risk, recomendación técnica, decisión humana, conectores ni outputs legacy.

## Resultados locales verificables

- Pruebas focalizadas de contrato, adversariales, compatibilidad, Assessment
  Contract y validadores legacy: 127 exitosas.
- Suite completa: 572 pruebas exitosas en Python 3.12.13 sobre Windows.
- Cobertura branch-aware: 86,81%, superior al gate de 85%; el módulo nuevo queda
  cubierto por casos positivos, negativos, adversariales y de tamper.
- Ruff check y format check: exitosos sobre 155 archivos.
- mypy: 21 módulos sin hallazgos.
- Build sin aislamiento: wheel y sdist 0.4.2 exitosos.
- Twine check: wheel y sdist exitosos.
- Instalación `--no-index --no-deps` e import desde target limpio: exitosos.
- OpenSpec 1.12.0 `validate --strict` y `doctor`: exitosos.
- CI remoto, rama, PR e integración: pendientes de publicación.

## Invariantes demostrados

- Un plan estructurado completo sólo obtiene PASS con provider disponible,
  parser OK, SHA-256 válido y evidencia FRESH.
- `todo`, gibberish allowlisted, repetición, campos ausentes, listas vacías,
  referencias rotas/invalid URLs y contradicciones declaradas no obtienen PASS.
- Provider ausente produce UNKNOWN; parser/provider error, digest inválido,
  timestamp futuro o intervalo invertido producen ERROR.
- Un PASS/N/A vencido se degrada a UNKNOWN. Un FAIL demostrado permanece FAIL,
  pero freshness STALE reduce su confidence mediante cap.
- Confidence se deriva sólo de determinability, freshness y provenance; un FAIL
  fresco y demostrado puede tener 100, mientras UNKNOWN/ERROR no llega a HIGH.
- Repetir los mismos inputs y timestamps produce bytes, IDs y hashes idénticos;
  el golden contract fuerza LF entre plataformas.
- Planes, acciones, triggers, owner, criteria, steps, contradicción libre y
  marcadores sensibles no se serializan. Los errores usan mensajes fijos.
- Re-sellar un contrato con componentes de confidence inconsistentes sigue
  siendo rechazado por invariantes cruzados, además de la protección de hash.
- El core completa con sockets bloqueados y no resuelve dashboard/alert URLs.
- Los tres validadores legacy, risk report, CLI, Action y Assessment Contract v1
  permanecen sin cambios; el adaptador nuevo es explícito y no infiere prosa.

## Riesgos residuales

- La política lexical es determinística pero no entiende lenguaje natural ni
  verifica la veracidad operacional de una afirmación.
- Las URLs sólo se validan por forma/estado declarado; disponibilidad y ownership
  real requieren evidencia de provider en una etapa posterior.
- Las contradicciones en prosa no se infieren: el producer estructurado debe
  declararlas.
- Callers deben aportar timestamps explícitos y digests SHA-256 aprobados no
  sensibles; cambios de campos o calibración exigen evolución compatible o una
  versión nueva.
- La etapa aún no está integrada en `main`; rama, PR y CI completo están
  pendientes.

## Rollback

Dejar de invocar `SemanticValidator` o fijar la versión anterior restaura el
flujo previo. No existe estado persistente, llamada de red o dato externo que
reparar. Conservar contratos ya emitidos como evidencia histórica, sin reetiquetar
UNKNOWN/ERROR ni recalcularlos con otra policy bajo la misma versión. Los outputs
legacy continúan disponibles durante toda la migración.
