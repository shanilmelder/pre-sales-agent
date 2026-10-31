# pre-sales-agent Helm chart

Deploys the api, worker and web app, and runs database migrations, on the Tiqri k3s
platform (or any cluster with an ingress controller and a Postgres you provide).
No dependency charts: Postgres comes from the platform's CloudNativePG, TLS from
cert-manager.

## What it creates

| Resource | Purpose |
| --- | --- |
| Deployment `<release>-api` + Service :8000 | FastAPI; internal only |
| Deployment `<release>-worker` | Job queue worker (same image family, `python -m app.main_worker`) |
| Deployment `<release>-web` + Service :3000 | Next.js; the only public endpoint |
| Ingress | `host` → web, TLS from `ingress.clusterIssuer` |
| Job `<release>-migrations` | `alembic upgrade head` as the schema owner, before api/worker roll out |
| PVC `<release>-files` | Uploaded files, shared by api and worker (ReadWriteMany, Longhorn); kept on uninstall |
| ConfigMaps | Backend settings, web settings, research allowlist |

Rollout order under Argo CD: ConfigMaps/PVC → migrations (Sync hook, wave 1) → api and
worker (wave 2) → web (wave 3).

## Secrets it expects (created outside the chart, e.g. SealedSecrets)

| Secret (value key) | Keys |
| --- | --- |
| `database.appSecret` (`db-psa-app`) | `username`, `password`: role `psa_app` |
| `database.ownerSecret` (`db-psa`) | `username`, `password`: schema owner `psa` (migrations only) |
| `backendSecret` (`pre-sales-agent`) | `PSA_DOWNLOAD_SIGNING_KEY` (required with `PSA_ENV=prod`), `PSA_OPENAI_API_KEY`, `PSA_RESEND_API_KEY` |
| `auth.existingSecret` (`pre-sales-agent-auth0`) | `AUTH0_CLIENT_SECRET`, `AUTH0_SECRET`; may also hold `AUTH0_CLIENT_ID` (it overrides `auth.clientId`) |
| `auth.backendSecret` (optional) | Settings the identity provider generates for the api/worker, e.g. `PSA_AUTH0_AUDIENCE` |
| `imagePullSecrets` | Registry credentials if the images are private |

On the Tiqri platform, `scripts/new-db-credentials.sh` in tiqri-k8s-gitops creates the two
database secrets together with the matching Postgres role passwords.

## Identity provider

Auth0 by default; any OIDC provider works (Zitadel on the Tiqri platform). For a non-Auth0
provider set, in `config` (backend, `PSA_AUTH_*`): `ISSUER`, `JWKS_URL`, optionally
`USERINFO_URL` (when access tokens carry no email/name), `EMAIL_CLAIM`, `NAME_CLAIM`,
`ROLES_CLAIM`, `ROLES_FORMAT` (`list` or `keys`) and `PERMISSIONS_FROM_ROLES`; and in `auth`
(web): `domain` (the provider's host), `scope`, and the client id and secret. The token `aud`
must equal `PSA_AUTH0_AUDIENCE`. User roles must equal the platform role names
(`presales_engineer`, `platform_administrator`, ...). The tiqri-k8s-gitops repo has a worked
example in `projects/pre-sales-agent/*/values/`.

## Demo data

`backend/scripts/seed_demo.py` adds a demo presales engineer and five demo Opportunities, as
the app role; it is idempotent, and `--dry-run` lists what it would do. The image holds only
`app/` (no `scripts/`), so run it by piping the file into the api pod:

```bash
kubectl -n <namespace> exec -i deploy/<release>-api -- python - < backend/scripts/seed_demo.py
```

## Key values

| Value | Default | Notes |
| --- | --- | --- |
| `host` | `pre-sales-agent.example.com` | Public hostname; also APP_BASE_URL / PSA_WEB_BASE_URL |
| `api.image.tag`, `worker.image.tag`, `web.image.tag` | `""` → `appVersion` | Image Updater sets these in test |
| `database.host` | `pg-rw.postgres-test.svc.cluster.local` | `pg-rw.postgres-<stage>.svc.cluster.local` on the platform |
| `config.*` | see values.yaml | Non-secret `PSA_*` settings; empty values are left out so app defaults apply |
| `files.*` | Longhorn RWX 10Gi | Or `files.existingClaim` |
| `*.resources` | see values.yaml | Must fit the namespace quota |

## Versioning

The chart is versioned separately from the app. Bump `version` in `Chart.yaml` for every
chart change; on merge to `main` the `helm-chart` workflow tags the commit
`pre-sales-agent-chart-v<version>`. The GitOps repo pins each stage to such a tag, so a
chart change reaches a stage only through a pull request there.

## Render locally

```sh
helm template pre-sales-agent deploy/helm/pre-sales-agent -n pre-sales-agent-test \
  -f path/to/stage-values.yaml
```
