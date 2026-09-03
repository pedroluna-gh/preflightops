# Diseño: validación semántica determinística

## Context

Los tres planes tienen formas legacy diferentes y validaciones superficiales. La capa
nueva debe ser auditable, offline y compatible, y debe diferenciar la calidad de la
evidencia de la conclusión técnica. La ausencia o expiración no puede producir PASS.

## Design Options

| Opción | Beneficio | Desventaja |
| --- | --- | --- |
| Conservadora: endurecer los tres booleanos legacy | Cambio pequeño y adopción inmediata | Rompe semántica histórica, no expresa UNKNOWN/ERROR/N/A y sigue mezclando presencia con confianza |
| Balanceada: contrato estructurado aditivo, evaluador puro y adaptador legacy explícito | Determinismo, explicabilidad, migración gradual y cero red | Requiere que consumidores produzcan campos y metadatos de evidencia explícitos |
| Enterprise: reglas configurables con NLP/modelos y verificación live | Mayor cobertura de lenguaje libre y estado real | Introduce variabilidad, red, credenciales, privacidad y una superficie operativa fuera de esta etapa |

## Decision

Se elige la opción balanceada. La semántica positiva sólo se demuestra con campos
estructurados; no se infiere contenido faltante ni se interpreta lenguaje libre.

## Contracts

`semantic-change-controls-v1` define tres controles estrictos. Todos declaran
`applicable` y `contradictions`. Un `NOT_APPLICABLE` requiere razón explícita y
evidencia vigente. Los planes aplicables exigen:

- rollback: action, trigger, owner, duración, success criteria y pasos observables;
- monitoring: owner, duración, success criteria, dashboards, alerts y pasos;
- validation: owner, duración, success criteria y pasos.

Cada paso contiene acción, señal observable y resultado esperado. Cada referencia
declara ID, URL segura cuando corresponde y estado `ACTIVE`, `BROKEN` o `UNKNOWN`.
Una referencia `BROKEN` falla; `UNKNOWN` nunca pasa. Las URLs se validan por forma,
sin resolver DNS ni realizar solicitudes.

`SemanticEvidenceReference` aporta provider/parser status, collected_at, valid_until y
digest. El output `semantic-validation-v1` no incluye el input: sólo metadatos seguros,
issues estables, scores, compatibilidad e integridad canónica.

## Status Precedence

1. parser/provider error o timestamp futuro/inconsistente: `ERROR`;
2. provider ausente o evidencia insuficiente: `UNKNOWN`;
3. defecto semántico demostrado: `FAIL`;
4. referencia incierta: `UNKNOWN`;
5. plan completo y evidencia fresca: `PASS`;
6. exclusión explícita, justificada y fresca: `NOT_APPLICABLE`.

La evidencia expirada conserva un `FAIL` demostrado de forma conservadora, pero
degrada un PASS o N/A a UNKNOWN. Ningún camino convierte ERROR o UNKNOWN en PASS.

## Confidence

Confidence es independiente de risk y de la bondad del resultado. Un FAIL claro con
input parseable, evidencia fresca y provenance puede tener confidence 100.

- determinability: 60 puntos cuando la semántica concluye PASS/FAIL/N/A, 20 para una
  incertidumbre semántica y 0 para error técnico;
- freshness: 25 FRESH, 5 STALE, 0 UNKNOWN;
- provenance: 15 con provider disponible, parser OK y SHA-256 válido.

Se suma y luego se aplica el menor cap: ERROR 20, UNKNOWN 49, STALE 49, freshness
UNKNOWN 40, provider ausente 25. Los niveles son LOW < 50, MEDIUM 50–79 y HIGH >= 80.
El confidence agregado es el promedio entero de los tres controles; N/A sigue contando
porque su justificación también necesita evidencia confiable.

## Freshness

El caller entrega `evaluated_at`, `collected_at` y `valid_until`. La expiración efectiva
es el mínimo entre `valid_until` y `collected_at + policy.max_age_seconds`. No se usa el
reloj del sistema. Un tiempo futuro o un intervalo invertido es ERROR; faltantes son
UNKNOWN; un deadline anterior a evaluación es STALE.

## Determinism and Privacy

Se ordenan controles/issues, se normalizan timestamps a UTC y se usa JSON canónico.
El ID y hash cubren todo el resultado salvo sus propios campos de identidad. Los
mensajes son allowlisted y nunca interpolan valores rechazados. No se serializa el
contenido de planes ni se accede a filesystem, entorno, red, reloj o aleatoriedad.

## Migration

Consumidores nuevos deben emitir el schema estructurado. `adapt_legacy_change_request`
permite evaluar Change Request v1 sin retirar los booleanos existentes; no extrae
semántica de texto y por ello los planes no estructurados fallan o quedan indeterminados.
La migración puede hacerse en paralelo y comparar outputs antes de usar el contrato
nuevo como gate.

## Residual Risks

- La política lexical rechaza placeholders conocidos, pero no comprende lenguaje
  natural ni verifica que una afirmación sea verdadera.
- URLs sólo se validan sintácticamente; disponibilidad real pertenece a una etapa de
  provider evidence.
- La declaración `contradictions` depende del productor estructurado; no se infieren
  contradicciones desde prosa.
- Cambios de campos o fórmula requieren evolución compatible o una nueva versión.

## Implementation Outcome

El diseño balanceado se implementó sin dependencias nuevas ni cambios a contratos
legacy. Los checks locales y los 15 checks remotos del PR #44 concluyeron exitosamente.
