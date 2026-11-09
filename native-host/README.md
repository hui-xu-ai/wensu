# Native host

The host is started by Edge/Chrome through native messaging and stays alive as
long as the extension port is open.

## Two channels

```
Edge extension  <-- native messaging (stdin/stdout) -->  this host
MCP server      <-- loopback TCP + token ------------>  this host
```

Native messaging can only be initiated by the extension, so the MCP server
cannot talk to the browser directly. The host bridges the two: it accepts
line-delimited JSON on `127.0.0.1:<ephemeral>` and forwards each request to the
extension.

## Files at runtime

| File | Purpose |
|---|---|
| `%LOCALAPPDATA%\scholar-search\host\bridge.json` | `{port, token, pid, started}` for the MCP server |
| `%LOCALAPPDATA%\scholar-search\host\logs\host.log` | what the host did, and when it lost the extension |
| stderr | diagnostics only; stdout carries protocol frames exclusively |

`bridge.json` is written on start and removed on exit. A stale file means the
host died without cleanup; the adapter surfaces the connection error instead of
retrying forever.

`wensu status` reports both paths, so a caller does not have to guess where they
are — `bridge.endpoint` and `bridge.log_path`.

## Install

```powershell
# 1. load extension/ as an unpacked extension in edge://extensions
# 2. copy the extension id it shows
.\install.ps1 -ExtensionId <id>
```

The script writes `com.scholar.search.json` and the registry key under both
Microsoft Edge and Google Chrome. There is no `run-host.cmd`: the launcher
compiles to `scholar-host.exe` beside it, and the browser starts that directly
through the registry entry. Use `-Uninstall` to remove.

## Security boundary
- verbs are limited to the nine in `adapters/bridge/policy.py`;
- `goto` is https-only and restricted to the CNKI host allowlist;
- unknown parameters and oversized frames are rejected before reaching the page;
- the TCP port binds to loopback only and every request must carry the token
  generated for that process.
