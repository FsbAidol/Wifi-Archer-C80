import { TelegramClient, Api } from "telegram";
import { StringSession } from "telegram/sessions/index.js";
import { NewMessage } from "telegram/events/index.js";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { machineIdSync } = require("node-machine-id") as { machineIdSync: (original?: boolean) => string };
import { mkdir, readFile, writeFile, chmod } from "node:fs/promises";
import { dirname, resolve } from "node:path";

// Reads the exact AES-GCM/HKDF format used by openclaw-channel-telegram-userbot.
async function decodeSession(value: string): Promise<string> {
  if (process.env.TG_SESSION_ENCRYPTED !== "true") return value;
  const packed = Buffer.from(value, "base64");
  if (packed.length <= 12 || packed.toString("base64") !== value) throw new Error("TG_SESSION_ENCRYPTED=true but session is not valid encrypted Base64.");
  const secret = process.env.OPENCLAW_TELEGRAM_SESSION_KEY || machineIdSync(true);
  const material = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), "HKDF", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: new TextEncoder().encode("openclaw-telegram-userbot"), info: new TextEncoder().encode("aes-256-gcm-key") }, material, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
  try {
    const clear = await crypto.subtle.decrypt({ name: "AES-GCM", iv: packed.subarray(0, 12) }, key, packed.subarray(12));
    return new TextDecoder().decode(clear);
  } catch { throw new Error("Cannot decrypt plugin session on this machine; refusing to continue."); }
}

const apiId = Number(process.env.TG_API_ID);
const apiHash = process.env.TG_API_HASH;
const sessionValue = process.env.TG_SESSION_STRING;
const channelName = (process.env.TG_CHANNEL || "SDVGton").replace(/^@/, "");
const discussionName = (process.env.TG_DISCUSSION || "SDVGchate").replace(/^@/, "");
const statePath = resolve(process.env.TG_COMMENT_STATE || "./data/processed-posts.json");
const comment = "Ура, новый пост";
if (!apiId || !apiHash || !sessionValue) throw new Error("Set TG_API_ID, TG_API_HASH and TG_SESSION_STRING in the environment.");

await mkdir(dirname(statePath), { recursive: true, mode: 0o700 });
let done = new Set<string>();
try { done = new Set(JSON.parse(await readFile(statePath, "utf8")) as string[]); } catch { /* first run */ }
const persist = async (id: string) => {
  done.add(id);
  const tmp = `${statePath}.tmp`;
  await writeFile(tmp, JSON.stringify([...done]), { mode: 0o600 });
  await chmod(tmp, 0o600);
  const { rename } = await import("node:fs/promises");
  await rename(tmp, statePath);
};

const client = new TelegramClient(new StringSession(await decodeSession(sessionValue)), apiId, apiHash, { connectionRetries: 5 });
await client.connect();
if (!(await client.isUserAuthorized())) throw new Error("Session is not authorized. Authenticate it with openclaw-channel-telegram-userbot first.");
const channel = await client.getEntity(channelName);
const discussion = await client.getEntity(discussionName);
console.log(`Listening for new posts in @${channelName}; comments go to linked @${discussionName}.`);
client.addEventHandler(async (event) => {
  const msg = event.message;
  const id = `${channelName}:${msg.id}`;
  if (done.has(id) || !msg.post || msg.out) return;
  try {
    const result = await client.invoke(new Api.messages.GetDiscussionMessage({ peer: channel, msgId: msg.id }));
    const root = result.messages.find((m: any) => m.peerId?.channelId?.toString() === (discussion as any).id?.toString() || m.peerId?.chatId?.toString() === (discussion as any).id?.toString());
    if (!root) throw new Error("No matching discussion root found; verify the group is linked and the account can access it.");
    await client.sendMessage(discussion, { message: comment, replyTo: root.id });
    await persist(id);
    console.log(`Commented on post ${msg.id}.`);
  } catch (err) {
    console.error(`Could not comment on post ${msg.id}:`, err instanceof Error ? err.message : "unknown error");
  }
}, new NewMessage({ chats: [channel] }));

const stop = async () => { await client.disconnect(); process.exit(0); };
process.once("SIGINT", stop);
process.once("SIGTERM", stop);
