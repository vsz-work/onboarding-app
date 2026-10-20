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
rockcraft.yaml                         rock (OCI image), flask-framework extension
charm/                                 K8s charm, flask-framework extension (paas-charm)
snap/                                  snap: gunicorn daemon + migrate command + configure hook
machine-charm/                         machine charm: installs the snap, relates to postgresql
deploy/registry.yaml                   local image registry for K8s (localhost:32000)
```

## One-time setup

```bash
lxd init --auto                       # craft tools build inside LXD
sudo k8s enable local-storage         # postgresql-k8s needs PVCs
sudo k8s kubectl apply -f deploy/registry.yaml
# Juju controllers: one on K8s, one on LXD
juju bootstrap ck8s ck8s              # skip if it already exists
juju bootstrap localhost lxd
```

## Kubernetes path: rockcraft → charmcraft → juju

```bash
# 1. Build the rock and push it to the local registry
rockcraft pack
rockcraft.skopeo --insecure-policy copy --dest-tls-verify=false \
    oci-archive:onboarding-app_0.1_amd64.rock \
    docker://localhost:32000/onboarding-app:0.1

# 2. Build the charm (the extension declares its own charm libs)
cd charm && charmcraft fetch-libs && charmcraft pack && cd ..

# 3. Deploy
juju add-model onboarding-k8s -c ck8s
juju deploy postgresql-k8s --channel 16/stable --trust
juju deploy ./charm/onboarding-app_amd64.charm \
    --resource flask-app-image=localhost:32000/onboarding-app:0.1
juju integrate onboarding-app postgresql-k8s
juju status --watch 5s                # wait for active/idle

curl http://<onboarding-app unit address>:8000/
```

The 12-factor charm runs `migrate.py` automatically once the database relation is ready.

## Machine path: snapcraft → charmcraft → juju

```bash
# 1. Build the snap (optionally try it locally: sudo snap install --dangerous ./onboarding-app_0.1_amd64.snap)
snapcraft pack

# 2. Build the machine charm
cd machine-charm && charmcraft fetch-libs && charmcraft pack && cd ..

# 3. Deploy, attaching the snap as a charm resource (no store upload needed)
juju add-model onboarding-machine -c lxd
juju deploy postgresql --channel 16/stable
juju deploy ./machine-charm/onboarding-app-machine_amd64.charm \
    --resource app-snap=./onboarding-app_0.1_amd64.snap
juju integrate onboarding-app-machine postgresql
juju status --watch 5s

curl http://<onboarding-app-machine unit address>:8000/
```

How the machine charm wires things up (`machine-charm/src/charm.py`):

1. `install`/`upgrade-charm`: fetch the `app-snap` resource and `snap install --dangerous` it.
2. When the database relation provides credentials, it runs `snap set onboarding-app db-uri=...`.
   The snap's `configure` hook enables and restarts the `server` daemon.
3. It then runs `onboarding-app.migrate`, opens port 8000 and goes active.
4. `relation-broken`: `snap unset` the db-uri (which stops the daemon) and goes blocked.

Unit tests: `cd machine-charm && tox -e unit`
