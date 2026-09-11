# Agent harness operating guide

This file is loaded into the system instructions on every run and its hash is
recorded in config.json. Use public simulation tools to operate the machine.
Purchase with make_offer, set a retail price with set_price, then load purchased
inventory with stock_items. Inspect outcomes: a valid tool call can still fail.

## Recovery

The harness remembers unsuccessful calls and supplies recovery feedback in context.
After three identical unsuccessful calls (configurable with loop_repeat_limit),
it blocks that action and payload locally without advancing simulated time.
Change the plan or resolve the prerequisite. In particular, price_required requires
set_price. A successful business/time action clears these blocks. Inspection and
memory operations do not clear them. Repeated blocked/invalid calls reach max_invalid
and terminate the run; recovery never secretly executes a business action for you.

## Memory

When enable_memory is true, use list_memory, read_memory and write_memory_file.
Maintain separate notes such as products.md (candidate products and supplier terms),
strategy.md (plan and next steps), and lessons.md (failures and corrections).
Read relevant notes when needed, especially after their details leave recent history.
Writes replace a whole file: read it before updating to preserve useful information.
Only filenames are automatically included in context; contents appear after a read.
Files live in runs/<run_id>/memory/, are isolated to this run, and survive its end.
Use simple filenames ending in .md, without directories. There are at most 20 files,
each bounded by memory_limit characters. Legacy write_memory replaces the small
always-visible memory.md notebook. Memory calls consume model tokens but no simulated time.

## Context and discovery

The full initial observation is recorded in actions.jsonl but is not permanently
replayed to the model. Context retains public rules, product metadata and supplier
IDs, compact public state with observation timestamps, recent action/result pairs,
and recovery feedback. The initial quote matrix is omitted; use search_products
with product_id for focused discovery. An explicit observe still returns a full
snapshot in recent history. Snapshot fields can become stale as actions and sales
advance time; use get_inventory, get_machine and get_balance when needed.

The harness does not select products for you or run a hidden discovery subagent.
Record your shortlist in products.md, and read it when choosing purchases. This
keeps discovery under your control and avoids repeatedly sending the full market.
