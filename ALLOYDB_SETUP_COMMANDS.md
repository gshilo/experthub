# AlloyDB Setup Commands

Creates the AlloyDB cluster, primary instance, database and table used by ExpertHub
in the lab project.

| Setting | Value |
|---|---|
| Project | `my-db-demos` (number `596582393106`) |
| Region | `us-central1` |
| Cluster / instance / database | `apex` / `apex` / `apex` |
| `postgres` password | `apex1234` (hard-coded in `customer_agent/agent.py`, see `ALLOYDB_PASSWORD_CHANGE.md`) |

---

## 1. Cluster (about 5–10 minutes)

```bash
gcloud alloydb clusters create apex \
  --region=us-central1 \
  --password=apex1234 \
  --enable-private-service-connect \
  --project=my-db-demos
```

## 2. Primary instance (about 5–10 minutes)

```bash
gcloud alloydb instances create apex \
  --cluster=apex \
  --region=us-central1 \
  --instance-type=PRIMARY \
  --cpu-count=2 \
  --allowed-psc-projects=596582393106 \
  --assign-inbound-public-ip=ASSIGN_IPV4 \
  --database-flags="alloydb.iam_authentication=on,password.enforce_complexity=on,password.min_pass_length=8,password.min_uppercase_letters=0,password.min_lowercase_letters=0,password.min_numerical_chars=0,password.min_special_chars=0" \
  --ssl-mode=ENCRYPTED_ONLY \
  --project=my-db-demos
```

`password.enforce_complexity` must stay on when the instance has a public IP. The `password.min_*`
flags lower the minimums so AlloyDB accepts `apex1234`.

### Optional: IAM database user for the Compute service account

```bash
gcloud alloydb users create 596582393106-compute@developer \
  --cluster=apex --region=us-central1 \
  --type=IAM_BASED --db-roles=alloydbsuperuser \
  --project=my-db-demos
```

## 3. Database and table

gcloud has no command for creating a database inside the instance. The instance has no
authorized networks, so connect with `psql` through the AlloyDB Auth Proxy:

```bash
curl -o alloydb-auth-proxy https://storage.googleapis.com/alloydb-auth-proxy/v1.13.3/alloydb-auth-proxy.linux.amd64
chmod +x alloydb-auth-proxy
./alloydb-auth-proxy --public-ip \
  projects/my-db-demos/locations/us-central1/clusters/apex/instances/apex &

export PGPASSWORD=apex1234
psql -h 127.0.0.1 -U postgres -d postgres -c "CREATE DATABASE apex;"
psql -h 127.0.0.1 -U postgres -d apex <<'SQL'
CREATE TABLE IF NOT EXISTS customer_ratings (
    customer_id BIGINT NOT NULL,
    customer_name TEXT NOT NULL,
    rating INTEGER NOT NULL,
    description TEXT NOT NULL,
    timestamp TIMESTAMPTZ
);
GRANT ALL PRIVILEGES ON SCHEMA public TO PUBLIC;
GRANT ALL PRIVILEGES ON TABLE customer_ratings TO PUBLIC;
SQL
```

The proxy version in the URL (`v1.13.3`) is an example; use the latest release.

### Alternatives

- **AlloyDB Studio:** Console → AlloyDB → `apex` → `apex` instance → AlloyDB Studio. Log in as
  `postgres` / `apex1234` and run the same SQL.
- **`apply_lab_changes.sh`:** `STEPS="5" ./apply_lab_changes.sh` creates the cluster, instance,
  database and table.
- **The agent:** creates the database and table on its first rating write if they are missing.
