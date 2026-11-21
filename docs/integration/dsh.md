# Connecting to DeepSeek Harness

Two transports are supported. Both expose the same seven tools: `search`, `detail`,
`detail_many`, `export`, `page_read`, `snapshot`, `status`.

`status` carries what an integration needs to decide before spending anything: `version`
(the package), `bridge_protocol`, `channel_capabilities` / `detail_capabilities` (what each
endpoint can actually fill), `quota_remaining`, `cooldown_until`, `action_cost` (the price
of each action, per channel — one unit is one network action), and
`browser_profile.extension_version` / `extension_version_mismatch`: the extension copy the
browser loads versus this build. A mismatch (`true`) means the copied assets are older than
the package — run `wensu setup`, then reload the extension.

## DSH bundle (recommended when the client is DSH)

Install `@hui-xu-ai/dsh-wensu` from the plugin market (or through `plugin_manager`);
it is a config-only bundle that mounts `@deepseek-ai/dsh-mcp-client` for you.

**A bundle works on exactly one DSH build.** The MCP client declares its peers at exact
versions, so the bundle's dependency and `engines.dsh` are pinned to a single release —
0.12.57 pins `0.2.2-rc.3`, 0.12.56 pins `0.2.2-rc.2`, and so on. The wrong pair is refused at
install/activation time (`error.code: incompatible-version` in the bundle list), the row never
mounts, and no tools appear while `wensu` itself keeps working. Run
`python scripts/check-bundle-compat.py` to see which bundle the installed DSH needs. **Every
DSH release needs a matching bundle release** — that is the price of exact peers.

`wensu` must still be on the PATH of the DSH process. Tools show up as
`mcp__wensu__{search,detail,detail_many,export,status}`.

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
