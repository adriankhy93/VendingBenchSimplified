---
name: vending-machine
description: Operate a simplified vending-machine simulation through its REST API. Use when asked to run, inspect, stock, price, purchase from, or finish a vending environment.
---

# Simplified vending-machine REST API

You operate the simulation only through HTTP requests. The API base URL is
`$VENDING_API_URL` when set, otherwise `http://127.0.0.1:8000`.

Use the `bash` tool with `curl --fail-with-body -sS` and JSON request bodies. Keep
the `env_id` returned by creation in the conversation and include it in every
later path. Never read the server filesystem, engine source, environment JSON, or
private artifacts to decide an action.

The API server is already running. Do not start a server, create configuration
files, inspect the project, or invoke any script. `ENV_ID` below is a placeholder,
never a literal ID. At the beginning of a fresh run there is no environment ID:
your first API call must be `POST /env`, then use its returned `env_id`.

## Lifecycle

The lifecycle endpoints are `POST /env`, `GET /env/ENV_ID/status`, and
`DELETE /env/ENV_ID`.

Create a new environment once:

```bash
curl --fail-with-body -sS -X POST "${VENDING_API_URL:-http://127.0.0.1:8000}/env" \
  -H 'Content-Type: application/json' -d '{}'
```

This returns `{"env_id":"env_..."}`. To select a pre-generated environment,
send `{"environment_name":"NAME"}` instead. Creation can also set `seed`,
`scenario_id`, `runtime_seconds`, and, only for `smoke-v1`, `max_days`.

Check lifecycle state at any time:

```bash
curl --fail-with-body -sS "${VENDING_API_URL:-http://127.0.0.1:8000}/env/ENV_ID/status"
```

The response is exactly one of `{"state":"running"}`, `{"state":"ended"}`,
or `{"state":"unavailable"}`. Do not make further action calls unless it is
`running`. When finished, release resources:

```bash
curl --fail-with-body -sS -o /dev/null -w '%{http_code}\n' -X DELETE \
  "${VENDING_API_URL:-http://127.0.0.1:8000}/env/ENV_ID"
```

Deletion returns HTTP 204. The server's real-time deadline can end a run even if
simulated time remains. A known ended environment rejects an action with 410;
an unavailable environment may return 409; an unknown ID or action returns 404.

## Actions

Every action is `POST /env/ENV_ID/ACTION` with `Content-Type: application/json`.
Successful actions return a public result envelope. Read it before choosing the
next request because a valid request can be rejected as a business outcome.

| Action | JSON body | Purpose |
| --- | --- | --- |
| `observe` | `{}` | Full public snapshot: catalog, supplier quotes, inventory, slots, prices, balances, and rules. |
| `search_products` | `{}` or `{"product_id":"p01"}` | Find public products, suppliers, and quotes. |
| `get_inventory` | `{}` | Current storage inventory. |
| `get_balance` | `{}` | Spendable cash, machine cash, and fee debt. |
| `get_machine` | `{}` | Slot IDs, contents, and capacities. |
| `make_offer` | `{"supplier_id":"s01","product_id":"p01","quantity":10,"unit_price_cents":100}` | Purchase stock. Only `accepted` delivers immediately. |
| `set_price` | `{"product_id":"p01","unit_price_cents":150}` | Set retail price within public bounds. Set a price before stocking that product. |
| `stock_items` | `{"slot_id":"r1s1","product_id":"p01","quantity":10}` | Move purchased storage stock into a machine slot. |
| `unstock_items` | `{"slot_id":"r1s1","quantity":10}` | Move items from a slot back to storage. |
| `collect_cash` | `{}` | Move machine cash into spendable cash. |
| `wait` | `{}` | Advance simulated time by the configured wait duration. |
| `end_day` | `{}` | Advance to the next day and assess sales and fees. |

For example:

```bash
curl --fail-with-body -sS -X POST "${VENDING_API_URL:-http://127.0.0.1:8000}/env/ENV_ID/set_price" \
  -H 'Content-Type: application/json' \
  -d '{"product_id":"p01","unit_price_cents":150}'
```

All money fields are integer cents. Action payloads with unknown fields, invalid
IDs, fractional values, or invalid quantities/prices return 422. Invalid JSON is
400. Use the exact action name and fields shown above.
