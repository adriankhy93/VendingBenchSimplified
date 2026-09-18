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

Store the entire returned value, including its `env_` prefix. Do not type or
shorten it manually. For example, create it once and extract it mechanically:

```bash
ENV_ID="$(curl --fail-with-body -sS -X POST "${VENDING_API_URL:-http://127.0.0.1:8000}/env" \
  -H 'Content-Type: application/json' -d '{}' | sed -n 's/.*"env_id":"\([^"]*\)".*/\1/p')"
```

Use `"$ENV_ID"` in every later URL, such as
`POST /env/$ENV_ID/observe`. Never send the literal text `ENV_ID` in a request.

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

## Operating limits

Call `observe` immediately after creation. Its `result.rules`, `result.slots`,
`result.products`, and `result.suppliers` are authoritative for that specific
environment. Use only IDs that appear in those response fields.

The default benchmark machine has four rows and three slots per row: exactly
`r1s1`, `r1s2`, `r1s3`, `r2s1`, `r2s2`, `r2s3`, `r3s1`, `r3s2`, `r3s3`,
`r4s1`, `r4s2`, and `r4s3`. Each slot holds at most 10 units of one product.
Do not invent slot IDs such as `r9999s9999`.

For every purchase, stock, or unstock request, send a positive integer quantity
only. Do not exceed `result.rules.quantity_cap` when purchasing. Before stocking,
set that product's price, use an empty slot or one already holding that product,
and ensure the requested quantity fits both the available storage and the slot's
remaining capacity. Before unstocking, ensure the slot contains at least that
many units.

Use only product and supplier IDs returned by `observe` or `search_products`.
All money values are positive integer cents. For `set_price`, use the selected
product's public `min_price_cents` through `max_price_cents`, inclusive. For
`make_offer`, ensure `quantity * unit_price_cents` does not exceed current
spendable cash. Inspect each response before the next action; a rejected action
does not complete the requested inventory change.

Demand and sales resolve once at each midnight, not continuously during a day.
`wait` advances five simulated hours, while `end_day` advances directly to the
next midnight. After a completed day, inspect the day event and machine state;
collect cash and replenish depleted slots before advancing another day.

## Daily operating loop

Use this compact loop for the entire episode. Keep narration to one short
sentence or omit it; prioritize tool calls and retain only the current machine,
storage, cash, prices, and best known quotes in your working state.

Do not enumerate the full catalog, recalculate the same margins, or write a
step-by-step analysis. After receiving `observe`, make the next tool call within
one short decision. The response budget is limited, so use a practical default
instead of searching for a mathematically exact optimum: choose up to four
products with the lowest listed cost relative to their reference price, set a
legal price modestly above each product's reference price, buy 10 units each at
the best listed quote, and stock one empty slot per product. Revise this small
assortment only from observed daily sales.

1. Call `observe` once at startup. It already includes the catalog, all listed
  quotes, prices, storage, slots, cash, and rules. Do not call `observe` or an
  unfiltered `search_products` again unless information is missing.
2. Choose a small assortment using listed quotes that leave a positive margin at
  a legal retail price. Set each chosen product's price, purchase stock, then
  stock only valid empty slots. A purchase must precede its corresponding stock
  action; an accepted `make_offer` is the only way to add storage inventory.
3. After initial stocking, use `end_day`, not repeated `wait` calls. There can
  be no sales before midnight, and `end_day` reaches that settlement directly.
4. After every midnight, call `get_machine` once. If machine cash is positive,
  call `collect_cash` once. Call `get_inventory` before refilling any slot.
5. Refill only after checking the returned state: for a selected slot, request
  no more than `capacity - quantity`; for storage, request no more than the
  returned product quantity. If storage is short, buy only the missing amount,
  then make one stock request. Never retry a rejected `stock_items` request
  unchanged. For `slot_full`, choose another valid slot or wait for sales; for
  `insufficient_stock`, purchase stock first.
6. Repeat from `end_day` while the environment is running. Stop immediately on
  `ended` or `unavailable`, then delete the environment.

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
| `wait` | `{}` | Advance simulated time by the configured wait duration; sales settle at midnight. |
| `end_day` | `{}` | Advance to the next midnight, settle daily sales, and assess fees. |

For example:

```bash
curl --fail-with-body -sS -X POST "${VENDING_API_URL:-http://127.0.0.1:8000}/env/ENV_ID/set_price" \
  -H 'Content-Type: application/json' \
  -d '{"product_id":"p01","unit_price_cents":150}'
```

All money fields are integer cents. Action payloads with unknown fields, invalid
IDs, fractional values, or invalid quantities/prices return 422. Invalid JSON is
400. Use the exact action name and fields shown above.
