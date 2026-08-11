# Athena Configuration

Primary sources:

- `.env` — secrets and environment overrides (never commit)
- `.env.example` — safe template
- `config/settings.py` — typed settings
- `config/permissions.yaml` — risk lists and permission policy

## Important variables

| Variable | Purpose |
|----------|---------|
| `ATHENA_NAME` | Assistant display name |
| `ATHENA_VERSION` | Semantic version |
| `OLLAMA_HOST` / `OLLAMA_MODEL` | Local LLM |
| `EMBEDDING_MODEL` | RAG embeddings |
| `OPENCLAW_*` | Optional execution gateway |
| `SMTP_*` / `IMAP_*` | Email send / inbox |
| `WAKE_WORD` | Wake phrase |
| `CONFIRM_*` | Permission policy |

## Permissions

```yaml
permissions:
  auto_execute_low_risk: true
  confirm_medium_risk: true
  confirm_high_risk: true
```

Risk buckets live under `risk:` in `permissions.yaml`.

## Paths

Writable data under the project (or beside `Athena.exe` when frozen):

- `data/cache/` — status + dashboard
- `data/sessions/` — tasks, drafts
- `data/application_registry/`
- `logs/athena.log`
