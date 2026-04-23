# AY-25-26-labs
Laboratories

## Documentation for Lab1 and Lab2

Read in order — each document builds on the previous one.

| # | Document | Contents |
|---|---|---|
| 1 | [Laboratory Introduction](docs/01-laboratory-introduction.md) | What MZinga is, why a real system matters, and the four-state architecture journey |
| 2 | [Architecture Evolution: Four States from Monolith to Event-Driven](docs/02-architecture-evolution.md) | Pattern-by-pattern walkthrough of each architectural state with code references |
| 3 | [Communications Email Flow & Decoupling Guide](docs/03-communications-email-flow.md) | Line-by-line walkthrough of the current email flow and the specific code changes to decouple it |
| 4 | [The Strangler Fig Pattern](docs/04-strangler-fig-pattern.md) | Deep dive into the primary migration pattern: origin, mechanics, and limitations |
| 5 | [Supporting Patterns Catalogue](docs/05-supporting-patterns-catalogue.md) | Full catalogue of patterns relevant across all four states |
| 5b | [Infrastructure Reference: MongoDB and RabbitMQ](docs/05b-infrastructure-reference.md) | MongoDB standalone vs replica set, RabbitMQ exchanges, queues, vhosts, and auth |
| 6 | [Lab 1 Step by Step](docs/06-lab1-step-by-step.md) | DB-coupled Python worker, feature flag, status field, end-to-end verification |
| 6b | [Lab 1 Code Snippets](docs/06-lab1-code-snippets.md) | All code snippets for Lab 1 with macOS, Linux, and Windows variants |
| 7 | [Lab 2 Step by Step](docs/07-lab2-step-by-step.md) | REST API worker (core) + event-driven RabbitMQ worker (optional extension) |
| 7b | [Lab 2 Code Snippets](docs/07-lab2-code-snippets.md) | All code snippets for Lab 2 with macOS, Linux, and Windows variants |

---

# My Lab 1 Implementation — DB-Coupled External Email Worker (State 1)

## Overview

This lab implements **State 1** of the architecture evolution:

**Strangler Fig → DB-Coupled External Worker**

The goal is to remove email sending from the MZinga monolith process and move it into an external Python worker that reads directly from MongoDB.

At the end of this lab:

- MZinga no longer sends emails in-process when the feature flag is enabled
- MZinga stores the `Communication` document and marks it as `pending`
- A Python worker polls MongoDB for pending communications
- The worker sends the email
- The worker writes the final status back to MongoDB

---

## Architecture Goal

### Before
When a `Communication` document was created in MZinga:

- the `afterChange` hook ran immediately
- recipients were resolved
- the body was serialized to HTML
- emails were sent inside the MZinga process
- the request blocked until all SMTP calls finished

### After
When a `Communication` document is created in MZinga:

- the document is stored
- status is set to `pending`
- the request returns immediately
- a separate Python worker later picks up the document
- the worker sends the email
- the worker updates the status to `sent` or `failed`

---

## What I Implemented

### 1. Added a `status` field to `Communications`
A new `status` field was added to the `Communications` collection with the following values:

- `pending`
- `processing`
- `sent`
- `failed`

The field is:

- type `select`
- shown in the admin sidebar
- read-only in the admin UI
- visible in the list view through `defaultColumns`

### 2. Added feature-flag-based external worker behavior
The following environment variable was used:

```env
COMMUNICATIONS_EXTERNAL_WORKER=true