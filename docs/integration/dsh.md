# Connecting to DeepSeek Harness

Two transports are supported. Both expose the same four tools: `search`, `detail`,
`export`, `status`.

## DSH bundle (recommended when the client is DSH)

Install `@hui-xu-ai/dsh-wensu` from the plugin market (or through `plugin_manager`);
it is a config-only bundle that mounts `@deepseek-ai/dsh-mcp-client` for you. It supports
DSH **0.2.2-rc.1 up to (not including) 0.3.0** — the pinned MCP client's DSH peer ranges are
exact, so a mismatched DSH admits the bundle but silently denies the MCP row and no tools appear.
`wensu` must still be on the PATH of the DSH process. Tools show up as
`mcp__wensu__{search,detail,export,status}`.

## stdio

```jsonc
{
  "mcpServers": {
    "wensu": {
      "command": "wensu",
      "args": ["serve", "--transport", "stdio"]
    }
  }
}
```

## HTTP (loopback + token)

Start the server locally:

```bash
wensu serve --transport http --host 127.0.0.1 --port 8765
```

On first start a random token is written to
`%LOCALAPPDATA%\scholar-search\http-token`. The client must send:

```
Authorization: Bearer <token>
```

Register it as a streamable HTTP MCP server pointing at
`http://127.0.0.1:8765/mcp`.

Why a token: the port is visible to every local process, and a browser page can
attempt DNS rebinding. The token plus a `Host` header check keeps other local
software from spending your quota or reading your search history. It is not an
account credential and carries no personal data.

## Notes

- The server never binds to `0.0.0.0`.
- No CORS headers are sent.
- `status` reports login state, institution, cooldown, and remaining quota.
- If a risk signal fires, every tool returns `blocked` with
  `action_required: manual_verification`; nothing is retried automatically.
