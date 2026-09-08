# ADR: GCP Evidence Provider v1

Estado: aceptado para implementación de etapa 13; cierre operativo pendiente.

| Diseño | Beneficio | Coste / límite |
| --- | --- | --- |
| Conservador: exports offline | Sin autenticación remota | No verifica acceso actual |
| Balanceado: REST oficial y ADC inyectadas | Alcance, límites y contrato verificables | Mantener mapping y restricciones ADC |
| Enterprise: gateway central | Cuotas y aislamiento centralizados | Infraestructura y operación adicionales |

Se elige el balanceado. Configuración inmutable, requests reconstruibles,
google-auth oficial con refresh separado y lecturas GET, proyección pura y
ProviderRunner común. La autenticación sólo permite intercambios de tokens, no
mutaciones de recursos. No se descubre ADC ambiental ni se expone un cliente
cloud genérico al motor de riesgo.

Identidad efectiva no se infiere de aliases ni de `has_scopes`: se registra
UNKNOWN cuando no existe atestación independiente. El proyecto se vincula a su
número mediante Resource Manager antes de interpretar respuestas. Existencia,
enabled state, freshness y cobertura permanecen separados. No se altera risk,
confidence global, recomendación o decisión humana en este adaptador.

Trade-offs: timeout cooperativo, IAM real no demostrado por mocks, fuentes de
credenciales externas fuera del transporte, convenciones de nombres Asset
Inventory limitadas y API Python aditiva sin autoactivación CLI/Action.
Estos límites se documentan en [el runbook](GCP_PROVIDER_V1.md); no justifican
promocionar evidencia incompleta a PASS. Una futura ampliación de endpoints,
identidad atestada o nombres exige especificación, revisión y pruebas adversariales.

Compatibilidad: ProviderEvidence v1 sin cambios y dependencias GCP opcionales.
Rollback: deseleccionar provider y restaurar distribución previa, conservar
evidencia y salidas legacy. No hay migración destructiva ni escrituras cloud.
