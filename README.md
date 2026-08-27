# eiu-mcp-server

A [Model Context Protocol](https://modelcontextprotocol.io) server that gives
Claude (or any MCP-compatible LLM client) structured, token-efficient access to
the [EIU](https://www.eiu.com/) data API — around 200 countries and 320
economic indicator series, history and forecasts.

It exposes three tools:

| Tool | Purpose |
|------|---------|
| `eiu_browse` | List available geographies and series, optionally filtered by keyword |
| `eiu_search` | Keyword search across the series catalogue (e.g. `"current account"`) |
| `eiu_get_data` | Fetch data by country and series code, with frequency and date filters |

Reference data is fetched once per session and cached in memory, so browse and
search cost no further API calls.

## Prerequisites

- **EIU API Developer Portal access.** This is not self-service. Email
  [economicssupport@economist.com](mailto:economicssupport@economist.com) and
  ask for Developer Portal access. They will set up your account by hand.
  You need all three of: your portal email address, your portal password, and
  the API key shown in the portal.
- [`uv`](https://docs.astral.sh/uv/) installed on your machine. One-liner:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

You do **not** need to clone this repo or manage a virtual environment —
`uvx` handles everything from the git URL.

## Install

### Claude Code

The one-line install, run from a folder whose `.env` holds your three EIU
values. The shell reads them, so the credentials never appear in your
conversation:

```bash
set -a; source .env; set +a
claude mcp add --scope user eiu \
  -e EIU_API_KEY="$EIU_API_KEY" \
  -e EIU_EMAIL="$EIU_EMAIL" \
  -e EIU_PASSWORD="$EIU_PASSWORD" \
  -- uvx --from git+https://github.com/joshua-bailey/eiu-mcp-server.git eiu-mcp-server
```

Or add the entry to `.mcp.json` by hand:

```json
{
  "mcpServers": {
    "eiu": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/joshua-bailey/eiu-mcp-server.git",
        "eiu-mcp-server"
      ],
      "env": {
        "EIU_API_KEY": "${EIU_API_KEY}",
        "EIU_EMAIL": "${EIU_EMAIL}",
        "EIU_PASSWORD": "${EIU_PASSWORD}"
      }
    }
  }
}
```

Then restart Claude Code. The three `eiu_*` tools should appear under `/mcp`.

### Claude Desktop

Same JSON snippet, placed under `mcpServers` in:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

Claude Desktop does not expand `${VAR}` references, so put the literal values
there instead.

### Pinning a version

`uvx` installs the latest commit on `main` by default. To pin to a tagged
release, append `@<tag>` to the git URL, e.g.:

```
"git+https://github.com/joshua-bailey/eiu-mcp-server.git@v0.1.0"
```

## Environment variables

| Variable | Required? | Purpose |
|----------|-----------|---------|
| `EIU_API_KEY` | **Yes** | Your EIU API key from the Developer Portal. |
| `EIU_EMAIL` | **Yes** | The email address your portal account uses. |
| `EIU_PASSWORD` | **Yes** | Your portal password. |

All three are needed. The server logs in with the email and password to obtain
a bearer token, then sends that token alongside the API key on every request.
The token is cached in memory and refreshed before it expires.

## Using it

Once the MCP is registered, ask Claude things like:

- "Search EIU for current account balance series"
- "What EIU series codes cover consumer prices?"
- "Pull EIU annual GDP growth (DGDP) for the US, UK and China from 2015 to 2030"
- "Show me EIU quarterly inflation forecasts for Brazil, Mexico and Chile"

Claude picks the right tool and calls it.

### Codes

- **Geographies** are ISO two-letter codes in capitals: `US`, `GB`, `CN`, `BR`.
- **Series** are EIU's own short codes in capitals, e.g. `DGDP`, `DCPI`. Use
  `eiu_search` or `eiu_browse` to find them rather than guessing.
- **Frequency** is one of `Yearly`, `Quarterly` or `Monthly`.

`eiu_get_data` caps its response at 200 data points to stay token-efficient and
says so when it truncates. Narrow the date range or the country list to see the
rest.

## API reference

The underlying API is documented at
[developer.eiu.com/help/overview](https://developer.eiu.com/help/overview).
The server talks to `https://api.eiu.com/v1`.

## Licence

MIT — see [LICENSE](LICENSE). Applies to the wrapper code in this repository
only. Dependencies retain their own licences. EIU data is a paid subscription
and its terms of use apply independently of this wrapper.
