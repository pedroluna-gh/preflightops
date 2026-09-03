# Evidencia de implementación — etapa 08

Fecha local: 2026-09-03. Alcance exclusivo: transformación offline de Assessment
Contract v1 en JSON canónico, informe Markdown, resumen PR y resumen ticket. No se
ejecutaron APIs externas ni se modificaron outputs legacy.

## Resultados locales verificables

- Pruebas focalizadas de contrato, CLI, Action, compatibilidad y renderizado: 176
  exitosas.
- Suite completa: 605 pruebas exitosas en Python 3.12.13 sobre Windows.
- Cobertura branch-aware: 86,57%, superior al gate de 85%.
- Ruff check y format check: exitosos sobre 207 archivos.
- mypy: 22 módulos sin hallazgos.
- Build sin aislamiento: wheel y sdist 0.4.2 exitosos.
- Twine check: wheel y sdist exitosos.
- Instalación `--no-index --no-deps` e import desde target limpio: exitosos.
- OpenSpec 1.12.0 `validate --all --strict` y `doctor`: exitosos, 4/4 elementos.

## Resultados remotos verificables

- Pull request de etapa: `#45`, 21 archivos y alcance exclusivo de reportes
  auditables.
- CI inicial `33776320818`: quality gates, matriz Python 3.11/3.12/3.13 en Linux,
  Python 3.12 en Windows y macOS, auditorías de dependencias y contrato de Action
  exitosos.
- Security `33776320855`: CodeQL y dependency review exitosos.
- Fuzzing `33776320792`: ClusterFuzzLite exitoso en 4m56s.
- Code scanning del commit inicial: exitoso, sin hallazgos bloqueantes.

## Invariantes demostrados

- Mismo Assessment Contract y configuración produce JSON, report ID e integrity
  byte-a-byte idénticos; el golden fuerza LF en todos los sistemas.
- PASS, FAIL, UNKNOWN y ERROR permanecen en categorías independientes; ERROR/UNKNOWN
  conserva `INDETERMINATE` y `DO_NOT_PROCEED`.
- Risk, confidence, recomendación técnica y decisión humana se copian sin
  recalibración ni mezcla; `grants_approval` siempre es false.
- Los reportes muestran primero decisión, blockers y acciones, y luego freshness,
  provenance y metadata de auditoría.
- Automation Details puede omitirse sin cambiar decisión o scores.
- Patrones Bearer/JWT/access key/secret, HTML, pipes, saltos y controles adversariales
  se redactan o escapan antes de renderizar.
- Los resúmenes PR/ticket respetan budgets determinísticos y declaran truncación.
- URLs no HTTPS, con credenciales, query o fragment se omiten sin resolverlas.
- El subcomando exige destinos explícitos, rutas únicas y rechaza archivos existentes
  salvo `--overwrite`; los sockets pueden estar bloqueados.
- El Action sólo activa la ruta nueva con Assessment Contract y outputs explícitos;
  no publica archivos, comentarios o tickets.

## Riesgos residuales

- La redacción por patrones no reconoce semánticamente todos los secretos internos;
  producers deben mantener data minimization.
- Hashes e IDs son content-free pero correlatables y requieren retención/control de
  acceso adecuados.
- La verificación de lectura menor a un minuto está respaldada por orden y budgets,
  pero depende de cantidad de findings y experiencia humana.
- Publicación, retención y permisos de artifacts pertenecen al workflow consumidor.
- La etapa aún no está integrada en `main`; después del archivo OpenSpec resta
  verificar el CI final del PR y la ejecución posterior a la fusión.

## Rollback

Dejar de invocar las APIs nuevas o `preflightops report render` y retirar los inputs
opcionales del Action. Los generadores y archivos legacy permanecen disponibles. No
existe base de datos, credencial, llamada externa o estado remoto que reparar. Conservar
reportes v1 ya emitidos como evidencia histórica sin re-sellarlos.
