# Claude Adapter

Claude-compatible files are included at the plugin root:

- `.claude-plugin/plugin.json`
- `.mcp.json`
- `commands/*.md`
- `hooks/hooks.json`
- `skills/easygee/SKILL.md`
- `skills/geomaster/SKILL.md`

The hooks are intentionally lightweight:

- `SessionStart` injects compact EasyGEE context and requests skill reload.
- `Stop` is reserved for future cleanup without printing credentials.

Do not copy OAuth tokens, auth URLs, credential files, or service account keys into Claude settings.
