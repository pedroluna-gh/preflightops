# GCP Evidence Provider v1

Estado: implementación local de etapa 13; publicación y CI pendientes.
Es una API Python aditiva. No cambia los outputs legacy ni activa consultas
GCP desde CLI/Action automáticamente. El proveedor produce ProviderEvidence v1,
no puntuaciones de riesgo ni aprobaciones de cambios.

## Configuración e integración

Instalar el extra `gcp` desde la distribución aprobada. La aplicación anfitriona
inyecta un objeto oficial `google.auth.credentials.Credentials` mediante un
supplier aprobado. No cargar archivos de credenciales de procedencia desconocida.
Ni configuración ni timestamps se descubren del entorno.

```python
from preflightops.gcp_provider import GcpProvider
from preflightops.gcp_scope import GcpConfig, GcpResource
from preflightops.provider_runtime import ProviderRequest, ProviderRunner

config = GcpConfig(
    project_id="example-project",
    allowed_projects=("example-project",),
    project_reference="project-01",
    principal_reference="principal-01",
    resources=(
        GcpResource(
            "policy-present",
            "policy",
            "projects/example-project/alertPolicies/123",
        ),
    ),
)
provider = GcpProvider(config)


def collect(approved_context_digest, evaluated_at, approved_adc_supplier):
    request = ProviderRequest(
        approved_context_digest,
        config.digest,
        provider.capabilities.controls,
        evaluated_at,
        timeout_seconds=10,
    )
    return ProviderRunner(cache_capacity=0).run(
        provider,
        request,
        credentials=approved_adc_supplier,
    )
```

El ejemplo no se ejecuta al importarlo. Sustituir referencias y selección por
valores aprobados; no usar nombres sensibles como aliases públicos. El supplier
se resuelve una sola vez por ejecución. Su código es una dependencia confiable:
no se garantiza aislamiento frente a código Python arbitrario.

## IAM mínimo por capacidad

Usar roles personalizados con los permisos necesarios en el proyecto elegido,
no Owner/Editor. Todas las ejecuciones requieren `resourcemanager.projects.get`
para verificar el vínculo project ID / project number y estado ACTIVE.

| Selección | Permiso adicional |
| --- | --- |
| Alert policy | `monitoring.alertPolicies.get` |
| Dashboard | `monitoring.dashboards.get` |
| Uptime check | `monitoring.uptimeCheckConfigs.get` |
| Service | `monitoring.services.get` |
| SLO | `monitoring.slos.get` |
| Métrica | `monitoring.timeSeries.list` |
| Asset Inventory explícito | `cloudasset.assets.listResource` |

Referencias: [permisos Monitoring](https://docs.cloud.google.com/iam/docs/roles-permissions/monitoring),
[project GET](https://docs.cloud.google.com/resource-manager/reference/rest/v3/projects/get),
[Asset Inventory list](https://docs.cloud.google.com/asset-inventory/docs/reference/rest/v1/assets/list).
El billing/quota project de ADC puede exigir `serviceusage.services.use` en ese
proyecto: debe aprobarlo el operador, no ampliarlo automáticamente el provider.

Monitoring solicita el scope OAuth `monitoring.read`; Resource Manager y Asset
Inventory solicitan `cloud-platform`. OAuth no sustituye IAM ni concede permisos
por sí solo. En credenciales ya scoped, la librería no garantiza cambiar los
scopes; una lectura denegada sigue siendo ERROR/AUTH. La API confirma acceso al
proyecto, no una identidad completa ni todos los permisos del principal.

El control `identity` queda UNKNOWN: aliases y metadatos de credenciales no son
atestación independiente de identidad/scopes efectivos. Es un límite explícito,
no un PASS implícito ni una afirmación de IAM verificado integralmente.

## Autenticación, red y presupuestos

Recursos: exclusivamente HTTPS GET a los endpoints oficiales construidos desde
la selección inmutable. Sin proxies ambientales, redirects, SDK genérico ni
enumeración de proyectos/organizaciones/carpetas. TLS obligatorio.

Refresh: callback separado admite POST sólo a `oauth2.googleapis.com/token`,
`sts.googleapis.com/v1/token` y `iamcredentials.googleapis.com/...:generateAccessToken`.
No admite signBlob, cambios IAM ni recursos cloud. Presupuesto de cuatro
intercambios por lectura, cuerpo de solicitud hasta 16 KiB y respuesta hasta
128 KiB. ADC de usuario y service account pueden usar estos intercambios;
WIF/impersonación sólo si sus fuentes de subject token no requieren otra red.
Metadata y fuentes externas de subject token están bloqueadas en este transporte;
un supplier aprobado debe obtener o refrescar esas credenciales fuera de él.
El modo de refresh asíncrono de google-auth se rechaza sin mutar las credenciales.
El callback de refresh se revoca al finalizar la autenticación; no queda disponible
para intercambios posteriores al cierre de esa operación.

Lecturas: límites configurables de respuesta, páginas, reintentos e intervalo.
Cada intento revalida su selección. No se retorna una lista parcial por tokens
repetidos, página truncada, error parcial o agotamiento del presupuesto.
La memoria por consulta queda acotada por páginas × bytes más el overhead JSON.
Hay hasta 50 selecciones por familia; el deadline común limita la ejecución.

Los timeouts son cooperativos: conexión hasta 5 segundos y lectura inactiva hasta
1 segundo, ambos limitados por tiempo restante; se comprueba el deadline entre
chunks y operaciones. DNS del sistema, refresh arbitrario o un stream muy lento
pueden devolver control tarde; el runner descarta resultados tardíos. Para un
límite de wall-clock estricto, el anfitrión necesita aislamiento de proceso.
Véase la limitación de timeout del [transporte oficial](https://google-auth.readthedocs.io/en/latest/reference/google.auth.transport.requests.html).

## Semántica y privacidad

- Policies: enabled explícito; disabled o validity no-OK no son PASS. No se
  certifican destinatarios, filtros, cobertura ni entrega de alertas.
- Dashboard/uptime/service: presencia exacta, no salud operativa.
- SLO: definición con objetivo y período válidos, no cumplimiento ni calidad SLI.
- Métricas: todas las series devueltas deben coincidir con proyecto, tipos y
  labels seleccionados. Freshness utiliza el último punto de cada serie y expira
  según el más antiguo de ellos. Se conserva precisión de nanosegundos y se
  redondea la expiración hacia abajo. No afirma que existan todas las series que
  una infraestructura completa debería tener.
- Assets: snapshot al readTime explícito, tipo exacto y nombre esperado. Sin
  contenido del recurso ni IAM policy. Los nombres compatibles deben incluir
  `/projects/<id>/`; otras convenciones requieren evolución explícita.
- HTTP 404: UNKNOWN/MISSING. 401/403: ERROR/AUTH. Cuotas, datos malformados,
  timeout y cancelación nunca se convierten en PASS.

No publicar URLs, labels, valores de métricas, nombres reales, tokens, cuerpos
remotos o mensajes de error. `source_reference` vincula sólo aliases aprobados
de proyecto/principal. Los digests no anonimizan datos predecibles. El mismo
fixture/contexto produce los mismos bytes; múltiples APIs vivas no constituyen
un snapshot transaccional. Rotar el context digest al cambiar principal/IAM.

## Runbook y rollback

1. Aprobar proyecto sandbox, principal, aliases, selecciones e IAM mínimo.
2. Confirmar APIs habilitadas fuera del provider y presupuesto de cuotas.
3. Ejecutar mocks y contrato común antes de cualquier acceso real.
4. En sandbox autorizado, comprobar recurso presente/ausente, policy disabled,
   denied, cuota y muestras vencidas; guardar sólo evidencia redactada.
5. Mantener la decisión humana separada; UNKNOWN no habilita blocking por sí solo.

No se ha ejecutado un sandbox real. Los mocks no prueban IAM efectivo, latencia
real, disponibilidad regional ni compatibilidad de todas las variantes ADC.

Rollback: retirar la selección del provider en el anfitrión, invalidar caché y
restaurar la distribución aprobada anterior. No hay recursos cloud que deshacer.
No borrar evidencia histórica ni outputs legacy. Revocación de credenciales o
roles, si fuera necesaria, corresponde al operador bajo su proceso autorizado.
