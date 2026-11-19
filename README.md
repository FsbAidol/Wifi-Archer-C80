# Telegram channel commenter for OpenClaw

Listens to new posts in `@SDVGton` and posts **«Ура, новый пост»** as a reply to the corresponding root message in its linked discussion group `@SDVGchate`.

Uses GramJS (the MTProto client also used by `openclaw-channel-telegram-userbot`) and accepts the same session string format, including the plugin's machine-bound AES-256-GCM encrypted value. It does not print credentials or message content. It keeps a local processed-post ID list to avoid duplicate comments after restart. Failed attempts are not marked as done, so they can be retried on a later run; Telegram/API errors can still occur.

## Setup

1. Install and configure `openclaw-channel-telegram-userbot` as documented by that plugin. Log in on the same machine, and make sure the account can view the channel and send messages in its discussion group.
2. Use the same API ID, API hash and session string as the plugin. Set `TG_SESSION_ENCRYPTED=true` only if the session value is the plugin's AES-GCM-encrypted output; plain GramJS session strings are not encrypted. Supply values through a private environment manager, not a committed `.env` file. For encrypted sessions, the process uses the plugin's default machine ID key when no custom key is configured.
3. Install dependencies and start:

```sh
npm ci
export TG_API_ID='…' TG_API_HASH='…' TG_SESSION_STRING='…'
npm start
```

Optional variables and defaults are documented in `.env.example`. The session value is read only from the process environment. Keep it private; session encryption is not a guarantee against malware or access to the same machine. Restrict host access, use a dedicated Telegram account, and inspect Telegram **Settings → Devices** periodically.

The account needs access to both public entities. Telegram must return a matching discussion root for each channel post; otherwise this tool logs a short error and skips that post. Test with a non-sensitive post first. Respect channel rules and Telegram rate limits. Stop with Ctrl+C.
