# KediMeet MCP server

<!-- mcp-name: app.kedimeet/kedimeet -->

[![Kedicode-TR/kedimeet-mcp MCP server](https://glama.ai/mcp/servers/Kedicode-TR/kedimeet-mcp/badges/score.svg)](https://glama.ai/mcp/servers/Kedicode-TR/kedimeet-mcp)

Ask Claude, Cursor, Codex or any other MCP client about your calls. This read-only server lets an AI assistant search
and read the meetings that [KediMeet](https://kedimeet.app) recorded on your Mac: transcripts by speaker, and summaries
with decisions, tasks and open questions.

> **You:** What did Daniel promise me this week?
>
> **Claude:** The screenshots for your onboarding copy, by Wednesday noon. He said it at 0:16 on Launch sync, Nov 18.

The assistant finds the right meeting itself, names it and its date, and gives the minute in the recording for quotes.
More examples: [kedimeet.app/ai](https://kedimeet.app/ai).

## Requirements

- A Mac with [KediMeet](https://kedimeet.app/download), free. The server reads the meetings folder KediMeet keeps on
  your Mac (`~/Library/Application Support/KediMeet`). KediMeet doesn't need to be running.
- [uv](https://docs.astral.sh/uv/). `uvx` downloads Python and the `mcp` library on first run.

## Connect

**From KediMeet, no Terminal.** Open Settings → Integrations and click Connect next to Claude, Claude Code, Cursor or
Codex. KediMeet ships this server inside the app and writes the app's settings for you. Restart Claude or Cursor
afterwards; Claude Code and Codex pick it up in a new session.

**By hand, any MCP client** (`claude_desktop_config.json`, `~/.cursor/mcp.json` and the like):

```json
{
  "mcpServers": {
    "kedimeet": {
      "command": "uvx",
      "args": ["kedimeet-mcp"]
    }
  }
}
```

Apps opened from the Dock don't see your shell's `PATH`, so if the app can't start `uvx`, put its full path in
`command` (`which uvx` prints it).

Claude Code:

```bash
claude mcp add --scope user kedimeet -- uvx kedimeet-mcp
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.kedimeet]
command = "uvx"
args = ["kedimeet-mcp"]
startup_timeout_sec = 60
```

If you moved your meetings to another folder in KediMeet, add its path as the last argument:
`uvx kedimeet-mcp "/Volumes/Archive/KediMeet"`.

## Tools

| Tool | What it does |
| --- | --- |
| `search` | Finds words in transcripts and summaries over a period, best matches first. Matches words with different endings. |
| `list_meetings` | Meetings in a period, newest first: title, date, participants, the main point of the summary. |
| `get_meeting` | The full summary: decisions, tasks with done marks, open questions, who spoke how much, the call link and your own notes. |
| `get_transcript` | The transcript turn by turn, `[time] Name: text`, whole or a part of the recording. |
| `open_tasks` | Tasks not marked done, across all meetings in a period, newest first: who, what, due date and the meeting. Ask your agent to put them into Jira, Linear or your to-do app. |

All five are marked read-only (`readOnlyHint`). None of them writes, deletes or goes to the network.

## Privacy

The server runs on your Mac over stdio and only reads files in the meetings folder. KediMeet's servers aren't involved.
What the assistant reads becomes part of your conversation, and its provider (Anthropic, OpenAI and others) handles it
under their own terms, as with anything you paste into a chat.

## Development

```bash
uv run test_server.py
```

`server.py` is the whole server. The KediMeet app ships the same file and runs it with `uv run --script`.

## License

MIT, see [LICENSE](LICENSE). The KediMeet name and the cat mascot are not covered, see [NOTICE](NOTICE).
