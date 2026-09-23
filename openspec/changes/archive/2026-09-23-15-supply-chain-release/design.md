## Context

Existen uv.lock, Dependabot revisado, Actions fijadas por SHA, auditorías por
Python, CodeQL, SPDX SBOM y attestation en release.yml. La release no demuestra
todavía reproducibilidad byte a byte y no ejecuta su propio clean-install.
Los controles de configuración remota requieren inspección, no presunción.

## Goals / Non-Goals

Demostrar integridad, repetibilidad y soporte con pruebas locales y CI.
No publicar una release, generar claves reales, cambiar permisos corporativos
ni certificar cumplimiento regulatorio.

## Decisions

| Opción | Beneficio | Coste/riesgo |
| --- | --- | --- |
| Conservadora/open-source | Scripts locales y documentación | Provenance sin identidad autenticada |
| Balanceada/nativa GitHub | Verificador offline y attestations existentes | Dependencia explícita de configuración GitHub |
| Enterprise | PKI, registro y servicio de políticas externos | Operación y credenciales adicionales |

Se elige la balanceada: verificaciones locales independientes y controles
nativos ya existentes. No introducir un servicio nuevo para firmar artefactos.
El verificador debe rechazar bundles incompletos, alterados o ambiguos; un
checksum acredita integridad respecto de un manifiesto, no identidad del autor.
Las attestations se verifican contra repositorio e identidad esperados.

## Risks / Trade-offs

- La repetibilidad exige entradas y toolchain fijadas; no implica resultados
  idénticos entre plataformas diferentes sin comprobarlos.
- Secret scanning no demuestra ausencia absoluta de secretos.
- Licencias desconocidas requieren revisión y no aceptación silenciosa.
- SLA y EOL documentados son compromisos operativos, no pruebas de ejecución.
- Reglas de tags, reviewers y firma dependen de plataforma y autorización;
  cualquier limitación se registra sin simular una firma.

## Migration Plan

Cambios aditivos en tooling y gates, sin sustituir outputs de assessment.
Ante regresión, restaurar tooling anterior aprobado sin relajar auditorías ni
retargetear tags. Conservar bundles y evidencia histórica.

## Verification outcomes

La evidencia registra dos builds limpios con canonicalización de metadatos del
sdist, SPDX de entradas acotadas y CycloneDX contrastado contra todo el lock.
Se inspeccionaron controles remotos y se documentó la decisión del propietario
de permitir self-review mientras sea único mantenedor. Las licencias desconocidas
permanecen pendientes: un gate separado impide publicar hasta revisión humana
vigente ligada al hash del lock. No se requiere publicar una release para validar
la construcción y la integridad. El primer head del PR pasó todos sus checks;
el archivo queda sujeto a CI del head final, merge y verificación post-merge.
