# Inbox Agent Design Overview

This document outlines the goals, capabilities, and technical approach for an Outlook-integrated inbox agent that reduces noise, automates safe actions, and keeps a clear audit trail.

## Goals and Capabilities
- **Primary goal:** reduce noise and surface what needs attention while automating safe, repeatable inbox tasks.
- **Continuous monitoring:** watches incoming mail via Microsoft Graph.
- **Priority triage:** uses rules plus an ML/heuristic score to categorize messages.
- **Auto-actions:** move, flag, mark read/unread, archive, create draft replies, and optionally send based on user configuration.
- **Thread processing:** summarizes threads and extracts action items or meeting invites.
- **Follow-up support:** creates tasks, Planner/Teams items, or calendar events.
- **Digests:** produces daily/weekly digests for low-priority mail such as newsletters and receipts.
- **Governance:** maintains an audit trail, supports undo, and offers human-in-the-loop confirmation for sensitive actions.
- **Configuration UI:** policies, whitelists/blacklists, strictness level, and templates.

## Architecture and Data Flow
1. **Connector / Auth**
   - OAuth 2.0 to Microsoft Graph with scopes: `Mail.ReadWrite`, `Mail.Send` (optional), and `offline_access`.
   - Prefer delegated permissions for user-level agents; app-only is also possible.
2. **Eventing / Ingest**
   - Microsoft Graph webhooks on `me/mailFolders('Inbox')/messages` or delta queries for new/changed mail.
   - Lightweight queue (Azure Service Bus / SQS / PubSub) buffers events.
3. **Preprocessor**
   - Fetches metadata and body (subject, recipients, attachments, headers, `receivedDateTime`).
   - Extracts attachment metadata and runs quick regexes for dates, phone numbers, invoice numbers.
4. **Classifier & Prioritizer**
   - Combines deterministic rules with an optional ML model to assign `priority_score`, tags, and recommended action.
   - Feature examples: sender trust/role (manager, VIP), delivery channel (direct vs CC), meeting intent, urgency keywords, attachments, time sensitivity, domain reputation, and past interactions.
5. **Action Engine**
   - Executes actions (move, flag, mark read, create draft, or send via Graph) and integrates with Teams/Planner/Slack.
   - Supports **safe mode** (create draft + notify) and **auto mode** (send without confirmation for low-risk rules).
6. **LLM Service**
   - Summarizes threads, extracts action items, and generates reply drafts using configurable prompts and privacy rules.
7. **UI / Dashboard**
   - Rule editor, action logs, undo controls, settings, digests, and manual triage view.
8. **Persistence & Audit**
   - Stores message hashes, actions taken, decision metadata, and logs with retention and encryption.

**Data flow (simplified):** New mail → webhook → queue → preprocessor → classifier → action engine (LLM if needed) → execute action → log & notify.

## Detailed Component Design
### Eventing and Sync
- **Webhook subscriptions:** create subscriptions scoped to `me/mailFolders('Inbox')/messages` with a secret `clientState` per tenant; rotate `expirationDateTime` every ~24 hours using a background job.
- **Delta queries:** fall back to `GET /me/mailFolders('Inbox')/messages/delta` to close gaps after downtime; persist `deltaToken` for restart safety.
- **Idempotency:** de-duplicate events by `messageId` + `changeKey` and persist a `processed_at` stamp.

### Preprocessor
- Normalize sender and recipient addresses, extract domain reputation, and detect `replyTo` overrides.
- Record attachment counts, types, sizes; drop payload download unless rules require it.
- Lightweight regex extraction for dates, invoice numbers, POs, and explicit urgency markers.
- Persist a normalized `MessageEnvelope` record with hashes of subject/body to avoid storing sensitive content when disabled.

### Classifier & Rules
- Deterministic rule engine runs before ML; ML can only raise/lower priority within configured bounds.
- **Rule evaluation order:** denylist → VIP/allowlist → structured rules → ML score adjustments → threshold bucketing.
- **Conflict resolution:** highest `priority_score` wins; deterministic actions (quarantine, move) run even when ML is disabled.
- **Tracing:** store matched rule IDs, feature vector snapshot, and ML model version for audit and reproducibility.

#### Example scoring rubric
- VIP sender or direct manager: +40
- Sent directly to you (not CC): +20
- Meeting invite or time string: +15
- Subject contains “urgent”/“ASAP”: +10
- Known automation/newsletter: −15
- One attachment or large attachment: +10
- Older thread with assigned follow-up: +5

#### Thresholds
- ≥ 70 → **High:** notify real-time and flag.
- 40–69 → **Medium:** move to Action folder; include in hourly digest.
- < 40 → **Low:** send to Low Priority/Newsletters; summarize in daily digest.

#### Rule examples
```json
{
  "rules": [
    {
      "id": "vip",
      "match": { "sender_in": ["ceo@company.com", "direct_manager@company.com"] },
      "action": ["flag", "move:VIP", "notify:push"],
      "auto_send": false
    },
    {
      "id": "newsletter",
      "match": { "subject_regex": "(unsubscribe|newsletter)", "has_many_recipients": true },
      "action": ["move:Newsletters", "summarize:daily_digest"],
      "auto_archive_days": 30
    },
    {
      "id": "receipt",
      "match": { "subject_regex": "(receipt|order|invoice)" },
      "action": ["extract:receipt", "save_to:AccountingFolder", "tag:receipt"]
    }
  ]
}
```

## Safety, Governance, and UX
- **Human-in-the-loop:** default behavior creates drafts for medium/higher-risk categories; users approve before sending. Auto-send is limited to low-risk categories.
- **Attachment safety:** quarantine unknown/malicious types, allow virus scanning, and require manual review for dangerous extensions.
- **Audit & undo:** keep a 30-day audit trail of actions and provide undo. Automated sends add a “Sent by Inbox Agent” header for transparency.
- **Privacy & compliance:** encrypt data at rest and in transit, respect DLP, and avoid third-party LLMs unless allowed; support on-prem/enterprise LLMs and compliance logging.

## Data Model (storage-agnostic)
- `users`: id, tenant_id, email, auth_config, preferences, strictness_level, created_at, updated_at.
- `mailboxes`: id, user_id, graph_mailbox_id, subscription_id, delta_token, last_sync_at.
- `messages`: id, mailbox_id, graph_message_id, change_key, subject_hash, body_hash, metadata_json, priority_score, bucket, state, received_at, processed_at.
- `attachments`: id, message_id, filename, media_type, size, sha256, quarantined, scanned_at.
- `rules`: id, user_id, definition_json, enabled, version, created_at, updated_at.
- `actions`: id, message_id, action_type, payload_json, status, executed_at, undo_token, actor (system/user).
- `digests`: id, user_id, period, content_json, delivered_at.

## APIs and Integrations
- **Auth:** OAuth authorization code flow with PKCE; refresh tokens stored encrypted; background job refreshes subscriptions.
- **Webhook handler:** validates `clientState`, enqueues events with `messageId` and `changeKey`, returns 202 quickly.
- **Message fetcher:** batches `GET /me/messages/{id}`; optionally uses `$select` to limit fields; retries with backoff on 429.
- **Action executor:** wraps Graph calls (`/me/messages/{id}/move`, `/createReply`, `/sendMail`) and logs results with request IDs.
- **External hooks:** optional webhooks to Teams/Slack for high-priority notifications and Planner task creation for action items.

## LLM Usage Guidelines
- Keep prompt templates versioned and scoped per-tenant; include PII minimization rules.
- Prefer retrieval-limited context: include trimmed thread, sender profile, and prior actions; never send full attachments without explicit consent.
- Enforce deterministic post-processing (JSON schema validation) and reject/redo on malformed outputs.
- Allow on/off toggle per workspace with a clear audit trail of LLM calls and token usage.

## Operational Runbook
1. **Provisioning:** create Azure AD app registration with required scopes; configure webhook URL and secrets.
2. **Key rotation:** rotate webhook secrets and encryption keys regularly; update `clientState` on subscription renewal.
3. **Monitoring:** track event lag, queue depth, Graph error codes, rule evaluation latency, and send/undo success rates.
4. **Incident response:** disable auto-send and switch to draft-only mode; drain queue while preserving order; re-run delta sync after outages.
5. **Backups & retention:** snapshot configuration (rules, prompts) and audit tables; enforce retention and deletion policies per tenant.

## MVP Plan
1. Implement OAuth and webhook subscriptions.
2. Build preprocessor and rule engine with VIP/newsletter/receipt rules.
3. Add LLM-backed summary and reply draft creation (draft-only initially).
4. Produce daily digest and a simple UI to view drafts and action items for approval.
5. Add monitoring, logging, undo, and metrics.
6. Introduce controlled auto-send for safe categories and escalation for urgent mail.

## Metrics and Monitoring
Track processed messages/day, automated actions, drafts created, manual approvals, reversals (false positives), triage latency, and user satisfaction feedback.

