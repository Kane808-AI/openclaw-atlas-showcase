# Approval-gated workflow

## The problem

Teams often want faster responses and more consistent follow-through, but an
unreviewed agent should not decide what is sent to a customer, prospect, or
partner. The workflow needs to help a human make the decision, not quietly
make it for them.

## The pattern

```text
Event or request
        |
        v
Classify and gather context
        |
        v
Create a draft + evidence
        |
        v
Human review and approval
        |
        +--> rejected: record reason and stop
        |
        v
Execute the approved action
        |
        v
Write an audit record
```

## Design decisions

1. **Drafts are inert.** Creating a draft is different from sending,
   publishing, or modifying a system of record.
2. **Approval is scoped.** An approval applies to one identified draft, not to
   a general category of future actions.
3. **Evidence travels with the draft.** The reviewer sees the source context,
   proposed action, and confidence signal together.
4. **Rejection is useful data.** A rejected draft remains in the record with a
   reason so the workflow can be improved without concealing mistakes.
5. **Execution is idempotent.** Retrying an approved action should not create
   duplicate sends or records.

## What the included example demonstrates

`examples/approval_gate.py` models the narrow state machine at the heart of
this pattern. It has no network access and no model call. That is deliberate:
the safety boundary should be understandable and testable without a live
account.

## What it does not claim

This portfolio note is not a production deployment guide, a promise of
autonomous messaging, or a description of a specific customer's system. Real
implementations need authentication, authorization, durable storage, audit-log
retention, monitoring, and domain-specific review rules.
