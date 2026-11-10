# Bridge protocol

The bridge is the only component allowed to touch a browser. It executes named
actions and returns page content; site knowledge stays in the channel plugin.

There are two hops, with different framing:

```
MCP server ──TCP, line-delimited JSON──▶ native host ──native messaging, 4-byte length + JSON──▶ extension
```

## Hop 1: TCP (MCP server ↔ native host)

Loopback only, one JSON object per line, authenticated with the per-run token
written to `bridge.json`.

Request:

```json
{"id":"7f3a","token":"…","action":"goto","params":{"url":"https://kns.cnki.net/"},
 "timeout_ms":15000,"domains":["kns.cnki.net"]}
```

Reply: the same `id`, `ok`, optional `error`, `data`, `url`, `duration_ms`.

- `domains` is the selected channel manifest's allowlist; the host enforces it
  in addition to the kernel.
- `timeout_ms` must be `1..15000`; larger values are rejected before forwarding.
- The adapter rejects a reply whose `id` does not match, unless the reply still
  carries a navigation URL (that URL is risk-relevant and is evaluated).

## Hop 2: native messaging (host ↔ extension)

Chrome/Edge framing: a 4-byte little-endian length followed by a UTF-8 JSON
object. stdout carries frames only; diagnostics go to stderr.

First exchange is a handshake:

```json
{"type":"hello","id":"…","protocol":1}
{"type":"hello_ack","id":"…","protocol":1}
```

A host that gets no acknowledged handshake sends no action frame. After that,
each action frame carries `id`, `action`, `params`; the reply is
`{"type":"action_result","id":"…","ok":…,"data":…}` with the same id.

## Verbs and parameters

| Verb | Params | Returns |
|---|---|---|
| `goto` | `url` (https)，或 `reload: true` 就地刷新 | `{url, title, status, captcha_visible, auth_required}` |
| `wait_for` | `selector`, `state?` (`visible`/`hidden`), `timeout_ms?` | `{matched}` |
| `type` | `selector`, `text`, `clear?` | `{}` |
| `click` | `selector` | `{}` |
| `select` | `selector`, `value` | `{}` |
| `read_html` | — | `{html, truncated}` |
| `read_text` | `selector`, `mode` (`inner`/`text`) | `{text}` |
| `scroll` | `to` (`top`/`bottom`) 或 `by` (1..10000 px) | `{}` |
| `sleep` | `ms` (≤3000) | `{}` |

Unknown verbs and unknown parameter keys are rejected, never ignored. The
closed schema lives in `src/scholar_search/core/params.py` and is used by both
the kernel and the host.

## Validation layers

1. **Kernel** – whole plan before the first action: verb set, manifest domains,
   parameter schema, action count (≤40), duration (≤200s).
2. **Host** – re-validates verb, parameter schema, deadline, domains supplied
   with the request, and frame size. A request failing here never reaches the
   browser.
3. **Extension** – only the nine verbs; parameters arrive already validated.

## Risk signals

Every action result carries a risk snapshot from the content script:
`captcha_visible` (visible, non-zero-size captcha element intersecting the
viewport), `auth_required` (visible login gate), `title`, `url`, `status`.

`goto` additionally reports the final URL after redirects and the page's HTTP
status; a `status >= 400` becomes an action failure (`HTTP <code>`), and the
kernel maps `403` to a risk stop.

## Error codes

| Code | Meaning |
|---|---|
| `policy.verb` | verb not allowed |
| `policy.domain` | host not in the channel allowlist |
| `policy.params` | parameter schema violation |
| `policy.deadline` | timeout outside 1..15000 ms |
| `bridge.timeout` | no reply within the deadline (including handshake) |
| `bridge.closed` | host or browser went away |
| `HTTP 403` | forbidden response reported by the page |

Risk stops are terminal: the kernel writes a 24h cooldown and refuses further
plans until `wensu reset --confirm`.

## Size limits

- each frame ≤ 2 MiB; `write_frame` refuses to emit more;
- `read_html` truncates by UTF-8 bytes (1 MB) and sets `truncated: true`;
- per-action deadline ≤ 15s, whole plan ≤ 200s.

## Versioning

`protocol` is exchanged in the handshake. A host that does not receive
`hello_ack` with the same version does not send actions.
