# onboarding-app

A deliberately tiny Flask + PostgreSQL app (`/` counts visits, `/health` returns ok)
used to practice the Canonical packaging and deployment toolchain. The same source is
shipped two ways:

| Path       | Package with | Charm with                               | Deploy to                        | Database          |
|------------|--------------|------------------------------------------|----------------------------------|-------------------|
| Kubernetes | rockcraft    | charmcraft, `flask-framework` extension  | Juju on Canonical K8s (`ck8s`)   | `postgresql-k8s`  |
| Machine    | snapcraft    | charmcraft, plain ops machine charm      | Juju on LXD (`lxd`)              | `postgresql`      |

Both paths hand the app its database through the same environment variable,
`POSTGRESQL_DB_CONNECT_STRING`, so `app.py` doesn't know where it's running.

```
app.py, migrate.py, requirements.txt   the Flask app (shared)
```
