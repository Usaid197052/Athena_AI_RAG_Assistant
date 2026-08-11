# Athena Security

## Rules

1. LLM proposes tools; Python validates and executes.
2. Permissions gate every tool (`security/permissions.py`).
3. Path guard blocks writes/deletes under Windows / Program Files.
4. Secrets stay in `.env` or OS credential stores — never in RAG, prompts, or logs.
5. External content (web, email, PDFs) is untrusted — prompt injection defense.

## Prompt injection

`security/sanitizer.py` wraps untrusted text:

```text
<<<BEGIN_UNTRUSTED_…_CONTENT>>>
…quoted data only…
<<<END_UNTRUSTED_…_CONTENT>>>
```

Used for RAG document context and IMAP email bodies. Models must treat that
block as DATA, not instructions.

## Risk levels

| Level | Policy |
|-------|--------|
| LOW | Auto when allowed |
| MEDIUM | Configurable confirmation |
| HIGH | Always confirm |
| CRITICAL | Deny by default |

## Audit

Tool executions record to the audit log without passwords, tokens, or private bodies.

## Email

`draft → confirm → send`. IMAP reads are LOW risk; send is HIGH.
