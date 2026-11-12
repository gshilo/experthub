# AlloyDB Password Change – `apex1234`

The agents now connect to AlloyDB as the built-in `postgres` user with the hard-coded
password `apex1234`, instead of IAM database authentication as the Compute service account.

## 1. Application code

### `customer_agent/agent.py`

This is the only module that opens AlloyDB connections. The Cloud Run frontend
(`frontend/app.py`) imports `write_customer_rating_to_alloydb` from it, so the change covers
both the frontend and the Agent Engine deployment.

| Location | Change |
|---|---|
| Constants, after `ALLOYDB_DATABASE` | Added `ALLOYDB_USER = "postgres"` and `ALLOYDB_PASSWORD = "apex1234"` |
| `_get_alloydb_connector()` | `Connector(refresh_strategy="lazy", enable_iam_auth=True)` → `Connector(refresh_strategy="lazy")` |
| `_connect_alloydb()` | `user=iam_user, enable_iam_auth=True` → `user=ALLOYDB_USER, password=ALLOYDB_PASSWORD` |
| `_get_alloydb_iam_user()` | Removed (no longer used) |
| `ensure_alloydb_ratings_table()` | `PermissionError` hint now names `ALLOYDB_USER` |
| Imports | Removed the unused `google.auth` and `urllib.request` |

The other agents (`customer_service_agent`, `auditor_agent`) do not connect to AlloyDB.

## 2. Provisioning script

### `apply_lab_changes.sh`

| Location | Change |
|---|---|
| Settings block | `ALLOYDB_PASSWORD_SECRET` replaced by `ALLOYDB_PASSWORD="apex1234"`. Added `ALLOYDB_FLAGS`. |
| `alloydb_password()` | Returns `ALLOYDB_PASSWORD` instead of reading Secret Manager |
| Step 3 (Secrets) | No longer creates `alloydb-postgres-password`; only `github-pat` is created |
| Step 5 (AlloyDB) | New instances use `ALLOYDB_FLAGS`. Existing instances are updated to those flags if they are missing (this restarts the instance). `postgres` password is set to `apex1234`. |
| Step 6 (BigQuery) | The `alloydb` connection is deleted and recreated every run so it stores `apex1234` |

`ALLOYDB_FLAGS` keeps `password.enforce_complexity=on` (AlloyDB requires it when the instance
has a public IP) but lowers the minimums so `apex1234` is accepted:

```
alloydb.iam_authentication=on
password.enforce_complexity=on
password.min_pass_length=8
password.min_uppercase_letters=0
password.min_lowercase_letters=0
password.min_numerical_chars=0
password.min_special_chars=0
```

## 3. Applying it to the lab project

Nothing has been changed in GCP yet. To apply:

```bash
STEPS="5 6 7 8 9" ./apply_lab_changes.sh
```

- Step 5 updates the instance flags (restart) and sets the `postgres` password.
- Step 6 recreates the BigQuery `alloydb` connection with the new password.
- Steps 7 and 8 redeploy the agents and the frontend so they pick up the code change.
  Step 7 creates new Reasoning Engines; delete the old ones afterwards.

The Secret Manager secret `alloydb-postgres-password` is no longer used and can be deleted:

```bash
gcloud secrets delete alloydb-postgres-password --project=my-db-demos --quiet
```

## 4. Security note

`apex1234` is in source control and gives `alloydbsuperuser` access. Network access still
requires the AlloyDB connector (mTLS, no authorized networks) and the `alloydb.client` IAM role,
but anyone with those can log in as `postgres`. Use this only for the lab.
