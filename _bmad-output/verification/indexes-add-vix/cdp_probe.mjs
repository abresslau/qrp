const PORT = 9223;
let _id = 1;
function rpc(ws, id, method, params = {}) {
  return new Promise((resolve, reject) => {
    const onMsg = (ev) => { const m = JSON.parse(typeof ev.data === "string" ? ev.data : ev.data.toString());
      if (m.id === id) { ws.removeEventListener("message", onMsg); m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result); } };
    ws.addEventListener("message", onMsg); ws.send(JSON.stringify({ id, method, params })); });
}
const send = (ws, m, p) => rpc(ws, _id++, m, p);
const evals = async (ws, e) => (await send(ws, "Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true })).result.value;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const targets = await (await fetch(`http://localhost:${PORT}/json`)).json();
  const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = () => j(new Error("ws")); });
  await send(ws, "Page.enable"); await send(ws, "Runtime.enable");
  await send(ws, "Page.navigate", { url: "http://localhost:3000/sym/indexes" });
  // default selection is the marquee MSCI World Net (an EQUITY index) — wait for its chart
  for (let i = 0; i < 40; i++) { if (await evals(ws, `!!document.querySelector('svg[aria-label="Index level time series"]')`)) break; await sleep(250); }
  await sleep(500);
  const r = await evals(ws, `(() => { const low=document.body.innerText.toLowerCase();
    return JSON.stringify({ header:(document.body.innerText.match(/MSCI World/)||[''])[0],
      hasPa:/p\\.a\\./.test(document.body.innerText), monthlyReturns:low.includes('monthly returns (%)'),
      monthlyLevel:low.includes('monthly level change (%)'), hasVolNote:/change in the level/i.test(document.body.innerText) }); })()`);
  console.log("EQUITY_DEFAULT=" + r);
  ws.close(); process.exit(0);
})().catch((e) => { console.error("ERR " + e.message); process.exit(1); });
