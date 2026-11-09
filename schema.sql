PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS automations (
  id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  platform TEXT NOT NULL,
  keyword TEXT NOT NULL,
  reply_text TEXT NOT NULL,
  prompt_text TEXT NOT NULL,
  link_text TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(workspace_id, id, version)
);

CREATE TABLE IF NOT EXISTS inbox_events (
  provider_event_id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workflow_runs (
  id TEXT PRIMARY KEY,
  automation_id TEXT NOT NULL REFERENCES automations(id),
  automation_version INTEGER NOT NULL,
  workspace_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  participant_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('waiting_for_email', 'completed', 'failed')),
  context_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS waiters (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL UNIQUE REFERENCES workflow_runs(id),
  workspace_id TEXT NOT NULL,
  automation_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  participant_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_waiter_per_participant
  ON waiters(automation_id, platform, participant_id, kind) WHERE active = 1;

CREATE TABLE IF NOT EXISTS outbox (
  id TEXT PRIMARY KEY,
  run_id TEXT REFERENCES workflow_runs(id),
  kind TEXT NOT NULL CHECK(kind IN ('reply_to_comment', 'send_dm')),
  payload_json TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'processing', 'sent', 'dead')),
  attempts INTEGER NOT NULL DEFAULT 0,
  available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  sent_at TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
