# Nanobot Team Digital Employee — Setup Guide

Deploy nanobot as an autonomous digital team employee on Slack (and optionally Teams).

## Prerequisites

- Python 3.11+
- A Slack workspace where you can create apps
- An LLM provider API key (e.g., NVIDIA, OpenAI, Anthropic)

## 1. Create Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From scratch**
2. Name it (e.g., "TeamBot") → select your workspace

### Enable Socket Mode

3. Left sidebar → **Socket Mode** → toggle **Enable**
4. Create an App-Level Token → name: "socket" → scope: `connections:write` → **Generate**
5. Copy the `xapp-...` token

### Set Bot Permissions

6. Left sidebar → **OAuth & Permissions** → **Bot Token Scopes** → add:
   - `app_mentions:read`
   - `channels:history`
   - `channels:read`
   - `chat:write`
   - `groups:history`
   - `groups:read`
   - `im:history`
   - `im:read`
   - `im:write`
   - `reactions:write`
   - `files:write`

### Subscribe to Events

7. Left sidebar → **Event Subscriptions** → toggle **Enable**
8. **Subscribe to bot events** → add:
   - `app_mention`
   - `message.channels`
   - `message.groups`
   - `message.im`

### Install

9. **Install App** → **Install to Workspace** → **Allow**
10. Copy the `xoxb-...` Bot User OAuth Token

### Invite Bot to Channels

In Slack, for each channel you want the bot in:
```
/invite @TeamBot
```

To find a channel ID: right-click channel name → **View channel details** → scroll to bottom (starts with `C`).

## 2. Configure Nanobot

Run the interactive wizard:

```bash
uv run python -m nanobot onboard --wizard
```

Configure each section:

| Menu | Setting | Value |
|------|---------|-------|
| **[P] Provider** | Provider | Your LLM provider (e.g., custom for NVIDIA) |
| | API Key | Your API key |
| | API Base | Your endpoint URL |
| **[C] Channel** → Slack | enabled | `true` |
| | botToken | `xoxb-...` |
| | appToken | `xapp-...` |
| | replyInThread | `true` |
| | groupPolicy | `mention` (responds only when @mentioned) |
| | allowFrom | `*` (all users, or specific user IDs) |
| **[G] Gateway** → Heartbeat | enabled | `true` |
| | intervalS | `1800` (30 min; use `300` for testing) |
| | notifyChannel | `slack` |
| | notifyChatId | Channel ID for heartbeat notifications (e.g., `C06ABCDEF`) |
| **[S] Save** | | |

## 3. Set Up Agent Identity

Edit `~/.nanobot/workspace/SOUL.md`:

```markdown
You are a digital team employee — an autonomous AI agent working alongside the team.

- You act on behalf of yourself, not as anyone's personal assistant
- You participate in team channels when mentioned
- You remember context from ALL channels (shared memory)
- Be concise and direct in group channels
- When multiple people talk to you, address each by name
```

Optionally edit `~/.nanobot/workspace/USER.md` with team context:

```markdown
# Team Context

- **Team**: (your team name)
- **Timezone**: (e.g., US/Pacific)

## Members
- Alice — Backend Engineer — U0123ABC
- Bob — PM — U0456DEF

## Active Projects
- Project Alpha — launching Friday — #project-alpha
```

## 4. Run

```bash
NANOBOT_MAX_CONCURRENT_REQUESTS=10 uv run python -m nanobot gateway
```

You should see:
```
✓ Channels enabled: slack
✓ Heartbeat: every 1800s
Agent loop started
```

## 5. Test

| Test | How | Expected |
|------|-----|----------|
| Basic response | `@TeamBot hello` in any channel | Replies in thread |
| Sender identity | `@TeamBot who am I?` | Knows your Slack user ID |
| Shared memory | Tell it something in Channel A, ask about it in Channel B | Remembers across channels |
| Concurrent | Two people @mention in different channels simultaneously | Both get correct responses |
| Thread isolation | Two separate threads in same channel | Independent conversations |

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NANOBOT_MAX_CONCURRENT_REQUESTS` | `3` | Max parallel LLM calls. Set to `10-20` for team use. |

### Key Config Fields (config.json)

```json
{
  "agents": {
    "defaults": {
      "model": "your-model",
      "provider": "custom",
      "temperature": 0.1,
      "contextWindowTokens": 200000,
      "reasoningEffort": null
    }
  },
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "replyInThread": true,
      "groupPolicy": "mention",
      "allowFrom": ["*"]
    }
  },
  "gateway": {
    "heartbeat": {
      "enabled": true,
      "intervalS": 1800,
      "notifyChannel": "slack",
      "notifyChatId": "C_CHANNEL_ID"
    }
  }
}
```

### Workspace Files

| File | Purpose |
|------|---------|
| `SOUL.md` | Agent personality and behavior instructions |
| `USER.md` | Team context (members, projects, norms) |
| `AGENTS.md` | Agent capabilities description |
| `TOOLS.md` | Custom tool usage instructions |
| `HEARTBEAT.md` | Active tasks for heartbeat to check on |
| `memory/MEMORY.md` | Long-term memory (auto-managed) |
| `memory/HISTORY.md` | Event log (auto-managed) |

## Troubleshooting

**Bot doesn't respond:**
- Check terminal for errors
- Verify bot is invited to the channel (`/invite @TeamBot`)
- With `groupPolicy: "mention"`, you must @mention the bot

**"LLM returned error: temperature must be 1 when thinking is enabled":**
- Set `reasoningEffort` to `null` in config, OR set `temperature` to `1`

**Slow responses with multiple users:**
- Increase `NANOBOT_MAX_CONCURRENT_REQUESTS` (default 3)

**Bot responds to wrong channel:**
- This was a known race condition, fixed by the ContextVar routing change. Ensure you're running the latest code.

## Architecture Notes

Key changes for team agent support (vs personal assistant):

- **Per-session locks** — concurrent sessions process in parallel without blocking each other
- **ContextVar routing** — tool calls (message, cron, spawn) use task-local context, preventing cross-session contamination
- **Memory write lock** — prevents concurrent consolidations from clobbering MEMORY.md
- **Sender identity** — runtime context includes sender ID/name so the agent knows who's talking
- **Heartbeat targeting** — configurable channel instead of random most-recent-session
- **Session cleanup** — idle sessions evicted from memory every 30 minutes
- **Concurrency gate** — configurable via `NANOBOT_MAX_CONCURRENT_REQUESTS` (default 3, recommend 10-20 for team use)
