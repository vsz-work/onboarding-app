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

# Desktop hosts with NetworkManager: keep LXD's "lxd" DNS search domain out of
# the host resolver (see Troubleshooting below)
sudo tee /etc/NetworkManager/conf.d/99-unmanaged-veth.conf <<'EOF'
[keyfile]
unmanaged-devices=driver:veth
EOF
sudo systemctl reload NetworkManager
sudo systemctl restart systemd-resolved
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
# 1. Build the snap (optionally try it locally: sudo snap install --dangerous ./vsz-onboarding-app_0.1_amd64.snap)
snapcraft pack

# 2. Build the machine charm
cd machine-charm && charmcraft fetch-libs && charmcraft pack && cd ..

# 3. Deploy, attaching the snap as a charm resource (no store upload needed)
juju add-model onboarding-machine -c lxd
juju deploy postgresql --channel 16/stable
juju deploy ./machine-charm/onboarding-app-machine_amd64.charm \
    --resource app-snap=./vsz-onboarding-app_0.1_amd64.snap
juju integrate onboarding-app-machine postgresql
juju status --watch 5s

curl http://<onboarding-app-machine unit address>:8000/
```

How the machine charm wires things up (`machine-charm/src/charm.py`):

1. `install`/`upgrade-charm`: fetch the `app-snap` resource and `snap install --dangerous` it.
2. When the database relation provides credentials, it runs `snap set vsz-onboarding-app db-uri=...`.
   The snap's `configure` hook enables and restarts the `server` daemon.
3. It then runs `vsz-onboarding-app.migrate`, opens port 8000 and goes active.
4. `relation-broken`: `snap unset` the db-uri (which stops the daemon) and goes blocked.

Unit tests: `cd machine-charm && tox -e unit`

## Finding and reaching the apps

The apps listen on port 8000. The addresses below are reachable **from the host only**:
other devices on your network can't route to the K8s pod/service network or the LXD bridge.

### Juju's view (same command on both substrates)

```bash
juju status -m ck8s:onboarding-k8s          # K8s: units and pod IPs ("Address" column)
juju status -m lxd:onboarding-machine       # LXD: units, machine IPs ("Public address") and open ports

juju switch ck8s:onboarding-k8s             # after switching, -m can be dropped
juju status --relations                     # also show integrations
juju status --watch 5s                      # live refresh
juju status onboarding-app                  # just one application
juju models -c lxd                          # models on a controller
juju controllers                            # all controllers
```

### The substrate's view (what Juju created underneath)

```bash
# Kubernetes: one pod per unit, a service in front of the app, the database's disk
sudo k8s kubectl -n onboarding-k8s get pods -o wide
sudo k8s kubectl -n onboarding-k8s get svc
sudo k8s kubectl -n onboarding-k8s get pvc

# LXD: one container per Juju machine (juju-<id>-N), plus the controller's container
lxc list
```

### Calling the apps

On K8s, prefer the **service** address: pod IPs change whenever a pod is recreated, but the
`onboarding-app` service keeps its IP while the application is deployed, and it balances across all units.

```bash
# K8s, through the service
K8S_IP=$(sudo k8s kubectl -n onboarding-k8s get svc onboarding-app -o jsonpath='{.spec.clusterIP}')
curl http://$K8S_IP:8000/

# LXD, one machine unit
LXD_IP=$(juju status -m lxd:onboarding-machine onboarding-app-machine --format=json \
    | python3 -c 'import json,sys; u=json.load(sys.stdin)["applications"]["onboarding-app-machine"]["units"]; print(next(iter(u.values()))["public-address"])')
curl http://$LXD_IP:8000/
curl http://$LXD_IP:8000/health
```

The two counters differ because each path has its own database.

### Getting a shell on a unit

```bash
juju ssh -m lxd:onboarding-machine onboarding-app-machine/0                    # the LXD machine
juju ssh -m ck8s:onboarding-k8s --container flask-app onboarding-app/0 bash    # the rock's container
```

### Reaching the apps from other devices

Not set up. The usual options:
- **K8s:** deploy `nginx-ingress-integrator` and integrate it with `onboarding-app` to get a hostname.
- **LXD:** add an LXD proxy device that forwards a host port to the machine.

## Accessing the database directly

Nobody types database passwords here: on `juju integrate`, the PostgreSQL charm creates a
user and stores its credentials in a **Juju secret** that it shares with the app. As model
admin you can read those secrets too.

### Which secret is which

```bash
juju secrets -m ck8s:onboarding-k8s               # IDs, owners, labels
juju show-secret -m ck8s:onboarding-k8s <id>      # metadata, including who has access
juju show-secret -m ck8s:onboarding-k8s <id> --reveal   # the content (live passwords!)
```

| Label | Contents | Shared with |
|---|---|---|
| `database.<N>.user.secret` | the app's DB credentials: `username`, `password`, `uris`, `read-only-uris` | the app |
| `database.<N>.tls.secret` | TLS settings for that integration | the app |
| `database-peers.<charm>.app` | the DB charm's internal passwords (`operator-password`, `replication-password`, …) | nobody |
| `database-peers.<charm>.unit` | per-unit internal data | nobody |

`<N>` is the integration ID. Removing and re-adding an integration creates a new ID and new
credentials; the old `database.<N>.*` secrets may stay behind unused.

### Connecting with psql as the app's user

`uris` is a complete connection string. This helper finds the current integration's secret
and prints it:

```bash
# usage: db_uri <model> <app-unit> <endpoint>
db_uri() {
    local rel_id label secret_id
    rel_id=$(juju exec -m "$1" --unit "$2" -- relation-ids "$3" | cut -d: -f2)
    label="database.${rel_id}.user.secret"
    secret_id=$(juju secrets -m "$1" --format=json | LABEL="$label" python3 -c \
        'import json,os,sys; print(next(k for k,v in json.load(sys.stdin).items() if v.get("label")==os.environ["LABEL"]))')
    juju show-secret -m "$1" "$secret_id" --reveal --format=json | python3 -c \
        'import json,sys; print(next(iter(json.load(sys.stdin).values()))["content"]["Data"]["uris"])'
}
```

The endpoint is the name in each charm's `requires:` section: `postgresql` for the K8s charm,
`database` for the machine charm. The easiest place to run `psql` is the database unit itself,
where the client is already installed:

```bash
# Kubernetes: psql inside the DB pod's postgresql container
URI=$(db_uri ck8s:onboarding-k8s onboarding-app/0 postgresql)
juju ssh -m ck8s:onboarding-k8s --container postgresql postgresql-k8s/0 "psql '$URI'"

# LXD: PostgreSQL is installed as the charmed-postgresql snap
URI=$(db_uri lxd:onboarding-machine onboarding-app-machine/0 database)
juju ssh -m lxd:onboarding-machine postgresql/0 "charmed-postgresql.psql '$URI'"
```

Try `select count(*) from visits;`: it matches the counter the app returns. The databases are
named differently. paas-charm names the K8s one after the app (`onboarding-app`); our machine
charm requests `onboarding`.

Capturing the URI in a variable keeps the password off the screen, but it is still a live
credential: avoid echoing it or pasting it anywhere.

### Your own user: data-integrator

Logging in with the app's credentials means you act **as the app**. For your own separate,
revocable user, use the `data-integrator` charm, which requests credentials on your behalf.
(Not deployed here.)

```bash
juju deploy -m lxd:onboarding-machine data-integrator --config database-name=onboarding
juju integrate -m lxd:onboarding-machine data-integrator postgresql
juju run -m lxd:onboarding-machine data-integrator/leader get-credentials
# remove the integration to revoke that user
```

On K8s, use `-m ck8s:onboarding-k8s`, `postgresql-k8s`, and add `--trust` to the deploy.

### From the host instead of the DB unit

- **LXD:** the DB is at the `postgresql/0` public address, port 5432. Install a client with
  `sudo apt install postgresql-client`. Not tested here: the charm's access rules may reject
  hosts that aren't integrated with it.
- **K8s:** the DB is only reachable inside the cluster. Forward a port, then connect to
  `localhost:5432` with the username and password from the secret:
  ```bash
  sudo k8s kubectl -n onboarding-k8s port-forward svc/postgresql-k8s-primary 5432:5432
  ```

## Things to try

Each application lives in one model, so every command below names its model with `-m`.
Without `-m`, `juju` uses the current model (`juju switch` changes it, and `juju add-model`
switches to the new model, which is why the deploy steps above don't need it).

```bash
K8S=ck8s:onboarding-k8s
LXD=lxd:onboarding-machine

# Kubernetes path
juju scale-application -m $K8S onboarding-app 2              # one more pod; units share one counter
juju remove-relation   -m $K8S onboarding-app postgresql-k8s # app goes blocked...
juju integrate         -m $K8S onboarding-app postgresql-k8s # ...and recovers
juju config            -m $K8S onboarding-app                # options added by the flask-framework extension
juju debug-log         -m $K8S --include onboarding-app

# Machine path
juju add-unit          -m $LXD onboarding-app-machine        # one more LXD machine; same shared counter
juju remove-relation   -m $LXD onboarding-app-machine postgresql
juju integrate         -m $LXD onboarding-app-machine postgresql
juju debug-log         -m $LXD --include onboarding-app-machine
```

Upgrading: bump `version` in `rockcraft.yaml` / `snap/snapcraft.yaml`, rebuild, then:

```bash
juju refresh -m ck8s:onboarding-k8s onboarding-app --path ./charm/onboarding-app_amd64.charm \
    --resource flask-app-image=localhost:32000/onboarding-app:0.2
juju attach-resource -m lxd:onboarding-machine onboarding-app-machine \
    app-snap=./vsz-onboarding-app_0.2_amd64.snap
```

## Troubleshooting

### Every K8s request that touches the database takes ~6 seconds

`/health` is instant, but `/` takes about 6 s, and `/etc/resolv.conf` on the host shows `search lxd`.

**Cause:** when LXD starts a container (craft builds, Juju machines), the container's
veth briefly appears on the host. NetworkManager auto-creates a "Wired connection N"
profile for it and runs DHCP against LXD's dnsmasq, which hands out the search domain `lxd`.
That domain leaks into the host resolver and from there into every pod's `resolv.conf`.
With `ndots:5`, resolving `postgresql-k8s-primary.onboarding-k8s.svc.cluster.local` also
tries `….lxd`. CoreDNS forwards that to the upstream router, which drops it, so every new
DB connection waits for the timeout.

Diagnose:

```bash
grep search /etc/resolv.conf                         # "search lxd" = affected
sudo k8s kubectl -n onboarding-k8s exec onboarding-app-0 -c charm -- \
    grep search /etc/resolv.conf                     # pod inherited "lxd"
journalctl -u systemd-resolved | grep "search domain list to: lxd"
```

Fix: apply the NetworkManager config from *One-time setup* (it makes NM ignore veth
devices, which LXD, Juju and Cilium manage themselves). Then recreate the pods, because a
pod's `resolv.conf` is fixed when the pod is created:

```bash
sudo k8s kubectl -n onboarding-k8s delete pod -l app.kubernetes.io/name=onboarding-app
```

To undo: `sudo rm /etc/NetworkManager/conf.d/99-unmanaged-veth.conf && sudo systemctl reload NetworkManager`.

### The K8s charm takes 10+ minutes to pack

The `flask-framework` extension uses charmcraft's `charm` plugin, which compiles every Python
dependency from source (`pip install --no-binary=:all:`), including Rust-based ones such as
pydantic-core. Rebuilds reuse the build container and are faster. The machine charm uses
the `uv` plugin and prebuilt wheels, so it packs in about 2 minutes.
