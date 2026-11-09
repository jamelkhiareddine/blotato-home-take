# Comment-to-DM Automation Engine

This repository is a small, runnable reference implementation for Blotato's
comment-triggered automations. It deliberately focuses on the hard part:
durably coordinating asynchronous social events and side effects. It is not a
full social-network integration or visual workflow builder.

## Scenario implemented

When a person comments `pricing` on an Instagram post, the engine:

1. replies `Sent you a DM!`;
2. sends a DM asking for their email address;
3. waits for a later inbound DM from the same person;
4. extracts an email address and sends a link.

```bash
python -m unittest discover -s tests -v
python demo.py
```

The only runtime dependency is Python 3.11+ and SQLite.

## Architecture

```text
Platform webhooks -> webhook endpoint -> inbox_events (dedupe) -> workflow engine
                                                                |          |
                                                          runs + waiters   outbox
                                                                |          |
Inbound DMs ----------------------------------------------------+          v
                                                        outbox dispatcher -> platform API
```

### Components

* **Webhook intake** validates the provider signature before accepting a
  payload (shown as a boundary in `AutomationService`; provider verification
  belongs in the HTTP adapter). It persists the provider event ID in an inbox
  table in the same transaction as creating/updating workflow state. A retry
  therefore cannot create duplicate runs.
* **Workflow engine** evaluates a versioned automation definition. This demo
  has a compact, typed definition for the requested flow; production would
  store a JSON DSL whose nodes include `trigger`, `send_comment_reply`,
  `send_dm`, `wait_for_message`, `condition`, and `end`.
* **Wait registry** records the correlation key `(workspace, platform,
  participant)` and the run that is waiting. On a DM, the engine claims at
  most one appropriate waiter and advances it.
* **Transactional outbox** holds commands to call a social platform. State
  transitions and outgoing commands commit atomically. A separate dispatcher
  delivers a command with an idempotency key, then marks it sent.

The platform client is intentionally an interface: Blotato already supports
receiving and sending platform events, so the integration adapter should live
at that boundary, not inside workflow logic.

## Data model

The SQLite schema is in [`schema.sql`](schema.sql).

| Table | Purpose |
| --- | --- |
| `automations` | Workspace-owned, versioned definitions and enablement. |
| `inbox_events` | Provider event IDs used for at-least-once webhook deduplication. |
| `workflow_runs` | A per-trigger execution with its current step and context. |
| `waiters` | The durable subscription for a future inbound DM. |
| `outbox` | Pending platform side effects with a stable idempotency key. |

The unique partial index on active waiters prevents two active email waits for
the same automation and social participant. Depending on the desired product
semantics, this can instead be scoped by post, campaign, or conversation.

## Execution and failure semantics

Webhook delivery and platform APIs are both **at least once**. Exactly-once
delivery is not realistic across those systems, so the implementation targets
effectively-once *observable* behavior:

1. Inbox-event insertion, run creation, waiter creation, and outbox insertion
   are a single database transaction.
2. Duplicate provider event IDs become no-ops.
3. The dispatcher leases pending outbox records (production: `FOR UPDATE SKIP
   LOCKED`; SQLite demo: atomic state update) and supplies the row's stable
   idempotency key to the provider API.
4. A worker crash after the API call but before `sent_at` may repeat the call;
   the provider idempotency key makes it safe. If the provider lacks that
   feature, persist provider message IDs where available and accept/mitigate
   rare duplicate sends.
5. Failed outbox messages get exponential backoff and eventually a dead-letter
   state plus alerting. The sample leaves retry scheduling visible rather than
   hiding it in a queue library.

The comment and DM handlers take a short transaction. In Postgres, concurrent
workers should use row locking on the candidate waiters, and all external API
calls must remain outside that transaction. Runs carry the automation version
used when started, so editing an automation does not silently change people
already in the middle of it.

### Routing ambiguities and product decisions

This reference chooses one active email collection per participant per
automation. A person can run several unrelated automations concurrently;
incoming DMs are routed to every eligible waiter only if product semantics
allow it. In a real product I would make that explicit in the builder:
`first matching run wins`, `fan out`, or require an identifiable conversation
thread. I would also define timeouts (for example 7 days), consent/rate limits,
opt-out handling, and platform-specific DM eligibility before enabling this
for customers.

## Project layout

* `automation_engine.py` — schema setup, durable state transitions, and outbox
  dispatcher.
* `demo.py` — end-to-end example using a recording platform client.
* `tests/test_automation_engine.py` — executable behavioral and deduplication
  coverage.

## AI-use disclosure

I developed the architecture, trade-offs, schema, implementation, and tests
myself. I used an AI coding assistant as a drafting and review aid: it helped
turn my design into initial documentation/code scaffolding and check edge cases
around transactions and idempotency. I reviewed, edited, and take
responsibility for the final submission.
# blotato-home-take
