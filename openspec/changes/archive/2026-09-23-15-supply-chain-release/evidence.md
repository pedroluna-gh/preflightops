# Evidencia incremental — etapa 15

## 2026-09-16: clean-install de release

- Etapa 14 cerrada en PR #51: commit main
  7e19f07714096b6458a1f367ea33bd094f8f6bd0. CI 35153668243,
  Security 35153668420, Scorecard 35153668315 y Fuzzing 35153668450 aprobados.
- Propuesta, diseño y escenarios de etapa 15: OpenSpec estricto aprobado.
- Smoke de wheel reforzado: dependencias con hashes obligatorios, ejecución
  fuera del checkout, LOW/CRITICAL y reportes Markdown/JSON/HTML/comentario.
- Ensayo real offline con wheel 0.4.2 de etapa 14: instalación limpia y ambos
  riesgos correctos, exit 0 del verificador. No demuestra build reproducible.
- Seis pruebas focalizadas aprobadas, incluyendo rechazos por exit/risk
  incorrectos, archivos ausentes y vacíos. Ruff focalizado aprobado.
- Workflow de release incorpora el smoke antes de attestation/publicación;
  pendiente validar gates finales y CI remoto de esta etapa.

## Pendiente

Reproducibilidad, bundle/SBOM, controles de seguridad y licencias, soporte/EOL,
rollback, suite integral y publicación/CI/archivo/post-merge. No se ha publicado
una versión ni usado claves reales. La etapa 15 no está completa.

## Ensayo de reproducibilidad

Dos builds secuenciales locales con SOURCE_DATE_EPOCH=1704067200 produjeron
wheels idénticos: SHA-256
663ab8a9e0ca0a31f3c5a8a363ae7252fa1e9e1d08294a8d6fed47534caf2dde.
Los sdists originales difirieron: timestamps de directorios y metadata generada;
ningún payload difería. No se ocultó la discrepancia.

Se añade una etapa explícita de canonicalización tar/gzip que conserva bytes
de payload y fija timestamps, ownership, permisos y orden. No extrae archivos;
rechaza duplicados, traversal, enlaces, entradas ambiguas y sobrescrituras.
Ambos sdists canonicalizados resultaron idénticos: SHA-256
2cc512a0032cba17988f78bd3b269842f04d068525826bef3ec626700cf32db3.
Ocho pruebas focalizadas y Ruff aprobaron. Estos hashes pertenecen al ensayo,
no a una release aprobada ni a una attestation firmada.

Pendiente integrar builds desde contextos limpios independientes, canonicalización
antes del wheel definitivo/checksums/attestation, y gate CI. Este ensayo no
demuestra todavía reproducibilidad entre plataformas ni cierre de etapa.

## Build independiente y gates compartidos

Implementado `scripts/release_build.py`: dos snapshots limpios de entradas de
packaging, sdist canonicalizado y wheel construido desde cada sdist. Comparación
SHA-256 exacta previa a promover un bundle; destino existente rechazado.
Ensayo Windows/Python 3.12.13 con build 1.6.0, setuptools 83.0.0 y wheel 0.48.0:
ambos artefactos idénticos; registro en
`.tooling/stage15-reproducible/reproducible-build.json` (evidencia local de ensayo).
Twine y smoke offline del wheel resultante aprobaron. No es una release publicada.

CI y release invocan el mismo builder. 36 pruebas focalizadas de packaging,
seguridad y contratos CI aprobaron. Pendientes suite integral, ejecución remota,
resto de controles de etapa 15 y endurecimiento final del verificador de bundle.

## Integridad offline del bundle

Añadido `scripts/release_bundle.py` para crear/verificar SHA256SUMS sobre un
inventario exacto de wheel, sdist, SPDX y registro de reproducibilidad. Rechaza
versiones discordantes, cambios de contenido, archivos ausentes/extra/vacíos,
directorios, symlinks y manifiestos ambiguos o inseguros; no sobrescribe evidencia.
13 pruebas focalizadas y Ruff aprobados. Integrado antes de attestation en release.
No acredita autenticidad ni completitud semántica de SBOM: esos controles siguen
separados y pendientes de verificación integral. No se publicó una release.

## Gestión de excepciones y soporte

Registro inicial vacío, validador offline con owner/aprobador distintos,
scope/evidencia/mitigación obligatorios y vigencia máxima 90 días. Diez pruebas
focalizadas aprobaron, incluido rechazo al vencer exactamente, fechas futuras,
autoaprobación, datos incompletos y duplicados. Integrado a CI/release sin
suprimir findings. Ruff aprobado; registro real vacío validado a UTC actual.
Documentados EOL con aviso, backports, política de licencias, checklist de
promoción, migración aditiva y rollback. La identidad del aprobador y controles
remotos siguen requiriendo evidencia independiente; no se simulan con texto.

## Verificación integral y controles remotos (2026-09-16)

- Suite completa: 1177 aprobadas, 31.49 s; cobertura de runtime con ramas 87.19%.
  Esta cobertura corresponde a preflightops, no a los scripts de release.
- Ruff lint aprobado; format detectó una línea larga en un test, corregida y
  repetida la verificación: 391 archivos correctos. mypy: 38 módulos correctos.
  OpenSpec estricto: 11 elementos aprobados.
- Inspección autenticada de GitHub confirmó private vulnerability reporting,
  dependency graph, Dependabot alerts/security updates, Secret Protection y
  push protection activos; CodeQL usa advanced setup. No se leyeron secretos.
- Ruleset de tags `Protect release tags v*` activo: restricciones de creación,
  actualización y borrado, commits firmados y bloqueo de force push. Existe
  bypass explícito del propietario; esto no equivale a tags inmutables frente
  al propietario ni prueba firma criptográfica de cada objeto tag.
- Entorno release tenía timer 15 minutos y tags v*, sin reviewers y con bypass.
  El usuario designó `pedroluna-gh`. Se guardó reviewer obligatorio, prevención
  de self-review y bypass administrativo desactivado; confirmado tras recargar.
  Se conservan timer y restricción v*. Una ejecución iniciada por esa misma
  cuenta necesita otro revisor autorizado; no se simula independencia.
- No se publicó una release, no se alteraron tags ni se generaron claves.
  SBOM y gates finales/remotos de etapa 15 siguen pendientes.

## Decisión explícita del propietario: operación individual

El usuario confirmó desactivar Prevent self-review porque es el único mantenedor.
Se aplicó únicamente ese cambio y se verificó mediante recarga del entorno:
reviewer obligatorio pedroluna-gh, self-review permitido, timer 15 minutos,
bypass administrativo desactivado y restricción v* conservados. Esto sustituye
el estado anterior de self-review descrito arriba; no constituye revisión
independiente. La limitación queda registrada en RELEASE_MANAGEMENT y se revisará
antes de publicar y al incorporarse otro mantenedor. No se publicó una release.

El verificador de bundle también contrasta el registro de reproducibilidad con
hashes reales y exige un inventario SPDX estructural con identidad/version del
paquete publicado. 22 pruebas focalizadas aprobaron. Esto no sustituye validación
completa de SPDX, revisión de licencias ni attestation autenticada.

## SBOM del lock completo

uv 0.12.1 exportó CycloneDX 1.5 offline con todos los grupos y extras: 103
dependencias externas, exactamente las 103 identidades/versiones del lock,
sin faltantes ni extras. Se añade `scripts/lock_sbom.py` con comparación obligatoria
en CI/release y el inventario se incluye en el bundle/checksums. Seis tests y
Ruff aprobados; ensayo real del script aprobado. El exporter está marcado
experimental por uv; versión fijada y contrato testeado. No aporta licencias,
por lo que no reemplaza el inventario SPDX ni su revisión independiente.

## SPDX real y bundle de ensayo (2026-09-18)

Syft 1.52.0 obtenido de la release oficial de Anchore, ZIP Windows verificado
contra SHA-256 publicado de787a374cf961c56fd7b206b2e183295abba32d0af3cb44d9aef2357ca9eda2.
Herramienta y caché locales en .tooling; chequeo de actualizaciones desactivado.
Se analizaron solamente uv.lock, pyproject.toml, wheel y metadata expandida de
la distribución, no el checkout completo ni credenciales.

El primer ensayo no reconoció versión del wheel; exponer metadata .dist-info
resolvió la identidad: preflightops 0.4.2, licencia declarada MIT. Se conserva
también la entrada UNKNOWN del proyecto dinámico detectada por Syft, sin
inventar su versión. El inventario contiene todas las dependencias del lock,
pero sus licencias siguen NOASSERTION: la revisión de licencias no está cerrada.

CI/release ahora fijan Syft v1.52.0 y generan SPDX desde staging explícito; no
publican assets desde la acción SBOM. El bundle local real con ambos inventarios
pasó create/verify de SHA256SUMS. No se atribuye attestation a este ensayo local.
Una prueba ZIP adversarial en Windows encontró normalización de backslash;
se valida orig_filename y se rechazan NUL/backslash. Repetición: 42 pruebas
focalizadas y Ruff correctos. Pendientes validación integral final y CI remoto.

## Revisión de licencias vinculada al lock (2026-09-18)

Metadatos instalados contrastados con 103 identidades del lock: 97 coinciden;
seis ausentes/diferentes y varias licencias ambiguas documentadas en
docs/LICENSE_REVIEW.md. No se infieren permisos desde clasificadores incompletos.
Registro security/license-review.json permanece pending, con owner y hash LF
exacto del lock. Validador distingue tracking válido de autorización para publicar;
release exige approved, vigente <=90 días y mismo hash antes de gh release.
Nueve pruebas focalizadas y Ruff aprobaron; registro real válido, no aprobado.
Se mantiene posible generar/verificar artefactos sin publicar una release no revisada.

## Validación final local (2026-09-23)

- Main remoto sigue en `7e19f07714096b6458a1f367ea33bd094f8f6bd0`, comparación
  idéntica contra el cierre de etapa 14. Se crea rama exclusiva
  `stage-15-supply-chain-release`; no se publican tags ni releases.
- Suite: 1206 pruebas aprobadas en 48.37 s; cobertura runtime con ramas 87.19%.
  Ruff lint y formato: 398 archivos correctos. mypy: 38 módulos correctos.
  OpenSpec estricto: 11 elementos aprobados. La cobertura no incluye scripts.
- Dos builds independientes finales idénticos, Twine aprobado para ambos
  formatos y clean-install offline del wheel final aprobado. Retorno al wheel
  retenido de etapa 14 probado en otro entorno limpio: LOW/CRITICAL y cuatro
  reportes correctos. Alcance y limitaciones en RELEASE_MANAGEMENT.
- SPDX final generado con Syft 1.52.0 sobre staging acotado; CycloneDX completo
  del lock verificado. `release_bundle.py create` y `verify` aprobaron el bundle.
- Registro de excepciones vacío válido; registro de licencias válido y pending.
  Ensayo negativo de publicación con este registro termina con exit 1; esto es
  el comportamiento esperado, no un finding suprimido ni una aprobación.
- Entorno GitHub leído nuevamente: reviewer pedroluna-gh, self-review permitido,
  espera de 15 minutos y bypass administrativo desactivado. Sin cambios nuevos.

SHA-256 de las distribuciones finales (Windows, Python 3.12.13):

| Artefacto | SHA-256 |
| --- | --- |
| preflightops-0.4.2-py3-none-any.whl | 663ab8a9e0ca0a31f3c5a8a363ae7252fa1e9e1d08294a8d6fed47534caf2dde |
| preflightops-0.4.2.tar.gz | dc029e1cc32df087761f6c12facaed8f50c7dbf5cdf3a4e9d833ab0e356b8474 |

Estos hashes identifican el ensayo local, no una release aprobada. SPDX y
CycloneDX conservan timestamps del generador; la repetibilidad byte a byte se
exige a wheel/sdist, no a inventarios o a attestations todavía no emitidas.

## Cobertura de requisitos y límites

| Requisito etapa 15 | Implementación/evidencia |
| --- | --- |
| Lock y actualizaciones | uv.lock, uv fijado, sync/export locked y Dependabot existente |
| Scanning, auditoría y licencias | CodeQL, audits por Python, protección remota; revisión de licencias pending bloquea publicación |
| SBOM por release | SPDX acotado y CycloneDX completo en workflows CI/release |
| Provenance y checksums | Bundle offline validado; attestation nativa sólo en release autorizada |
| Firma | Ruleset de tags inspeccionado; commits firmados no prueban firma de tags; no claves generadas |
| Reproducibilidad e instalación | Dos builds limpios, Twine, clean-install y casos LOW/CRITICAL reales |
| Soporte y vulnerabilidades | SECURITY.md: versiones, disclosure, SLA, backports y EOL |
| Checklist y rollback | RELEASE_MANAGEMENT, CHANGELOG y ensayo local del artefacto anterior |
| Mínimos privilegios | Contratos de workflows y SHA pinning pasan; publicación aislada en entorno protegido |

Pendientes de cierre: CI completo del PR, resolución de hallazgos, archivo,
merge y controles post-merge. Riesgos residuales: licencias aún no aprobadas,
único mantenedor sin revisión independiente, bypass del owner en reglas de tags,
reproducción dependiente de plataforma/toolchain y ausencia de una nueva release
real firmada/atestada. No se declara madurez 5/5 ni se inicia la etapa 16.

## Primer head remoto aprobado y preparación del archivo

PR: https://github.com/pedroluna-gh/preflightops/pull/52
Head: `de217bed6272a1327807cfff712a034bb5892133`.
Los 30 archivos cambiados coinciden con sus hashes de blob locales normalizados
a LF; no hay archivos ajenos al alcance. GitHub muestra 14/14 checks aprobados.

- CI: https://github.com/pedroluna-gh/preflightops/actions/runs/35880884673
  Sus 11 jobs aprobaron: quality (incluidos build doble, SPDX, CycloneDX,
  clean-install y verificación del bundle), cinco combinaciones OS/Python,
  tres auditorías por Python, Action LOW/CRITICAL y Required.
- Security: https://github.com/pedroluna-gh/preflightops/actions/runs/35880883591
  CodeQL y Dependency review aprobaron; también pasó el check de resultados
  CodeQL. No se suprimieron hallazgos ni se relajan reglas para fusionar.
- Ruleset main inspeccionado sin modificar: activo, sin bypass, PR obligatorio,
  firmas, historia lineal, conversaciones resueltas, rama actualizada,
  Required y resultados CodeQL. Cero aprobaciones exigidas y Code Owners no
  obligatorio: se documenta como limitación adicional de operación individual.

Se prepara archivo y promoción de la especificación después de estos resultados.
Estos cambios documentales requieren un nuevo head verde antes del squash merge.
La evidencia definitiva del commit merge y sus runs se registrará en el comentario
de cierre del PR, sin atribuir a esta revisión un resultado futuro.
