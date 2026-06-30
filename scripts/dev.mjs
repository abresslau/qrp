// QRP dev runner — starts the FastAPI API (:8001), the Next console (:3000), and Dagster (:3333)
// together. Usage: `npm run dev` (from the repo root). Ctrl-C stops all three.
// Note: uvicorn is run WITHOUT --reload (WatchFiles is unreliable on this Windows box);
// restart this script after API code changes. `dagster dev` runs both the webserver (the UI the
// Data Monitor card links to) and the daemon (schedules/sensors); the API probes its GraphQL at
// :3333 (DAGSTER_GRAPHQL_URL / DAGSTER_UI_URL default there). Dagster needs DAGSTER_HOME set.
import { spawn } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

const defs = [
  {
    name: "api",
    color: "\x1b[36m",
    cmd: "uv run uvicorn qrp_api.main:app --port 8001 --host 127.0.0.1",
    cwd: root,
  },
  { name: "web", color: "\x1b[32m", cmd: "npm run dev", cwd: join(root, "apps", "web") },
  {
    name: "dagster",
    color: "\x1b[35m",
    cmd: "uv run dagster dev -m lineage.definitions -p 3333",
    cwd: root,
    env: { ...process.env, DAGSTER_HOME: join(root, ".dagster_home") },
  },
];

const children = [];
for (const d of defs) {
  const child = spawn(d.cmd, { cwd: d.cwd, shell: true, env: d.env ?? process.env });
  const tag = (buf) =>
    buf
      .toString()
      .split(/\r?\n/)
      .filter(Boolean)
      .forEach((line) => process.stdout.write(`${d.color}[${d.name}]\x1b[0m ${line}\n`));
  child.stdout.on("data", tag);
  child.stderr.on("data", tag);
  child.on("exit", (code) => process.stdout.write(`${d.color}[${d.name}]\x1b[0m exited (${code})\n`));
  children.push(child);
}

function shutdown() {
  for (const c of children) {
    try {
      c.kill();
    } catch {
      /* ignore */
    }
  }
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);

process.stdout.write(
  "QRP dev — API http://127.0.0.1:8001 · console http://localhost:3000 · Dagster http://127.0.0.1:3333 (Ctrl-C to stop)\n",
);
