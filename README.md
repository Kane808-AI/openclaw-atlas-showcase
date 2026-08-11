# Chris Kaneshiro — AI systems portfolio

I build practical AI-assisted systems for operations, marketing, and customer
workflows. My focus is not autonomous novelty for its own sake. It is making a
useful process observable, reviewable, and safe enough to run repeatedly.

This repository is a small, personal portfolio for technical conversations. It
does not contain client work, production credentials, private infrastructure,
or a deployable copy of any live system.

## What I care about

- **Human control at consequential moments.** A model can prepare a draft or
  recommendation, but a person makes the final send, publish, or record change.
- **Clear system boundaries.** Inputs, permissions, approvals, execution, and
  audit records should be explicit rather than implied by a prompt.
- **Useful automation.** I start with a bounded workflow, measure whether it
  helps, and expand only after the failure modes are understood.

## Portfolio highlights

### Approval-gated communications

An inbound event is classified, assigned a confidence level, and turned into a
draft. The system stops there until an authorized reviewer approves it. This
reduces manual prep work without letting an agent send customer-facing content
unattended.

See the [architecture note](docs/approval-gated-workflow.md) and a small,
dependency-free [Python example](examples/approval_gate.py).

### Search and brand-intelligence monitoring

I have built monitoring workflows that combine search performance, site health,
and AI-search observations into a review queue. The useful part is the
decision loop: collect signals, flag exceptions, give a person evidence, and
record the disposition. It is not a promise of fully automated marketing.

## Repository map

```text
docs/       Design notes for the portfolio workflows
examples/   Small, runnable examples of the control patterns
scripts/    Checks that keep this public portfolio client-neutral
.github/    Verification workflow for the examples and content checks
```

## Run the example

```bash
python3 -m unittest discover -s examples -p '*_test.py'
python3 scripts/check_public_content.py
```

## Scope and contact

This is a personal portfolio, not an active agency site or a copy of a
production environment. I am pursuing a full-time role where I can build and
operate reliable AI-enabled products and workflows.

Built by Chris Kaneshiro.
