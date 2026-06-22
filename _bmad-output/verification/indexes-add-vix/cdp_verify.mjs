// Drive real headless Chrome over CDP to verify the VIX feature end-to-end.
const PORT = 9223;
const SHOT = process.argv[2]; // screenshot output path

async function rpc(ws, id, method, params = {}) {
  return new Promise((resolve, reject) => {
    const onMsg = (ev) => {
      const m = JSON.parse(typeof ev.data === "string" ? ev.data : ev.data.toString());
      if (m.id === id) { ws.removeEventListener("message", onMsg); m.error ? reject(new Error(method + ": " + JSON.stringify(m.error))) : resolve(m.result); }
    };
    ws.addEventListener("message", onMsg);
    ws.send(JSON.stringify({ id, method, params }));
  });
}
let _id = 1;
const send = (ws, method, params) => rpc(ws, _id++, method, params);
const evals = async (ws, expr) => (await send(ws, "Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result.value;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function pollFor(ws, expr, label, tries = 40) {
  for (let i = 0; i < tries; i++) {
    if (await evals(ws, expr)) return true;
    await sleep(250);
  }
  throw new Error("timeout waiting for: " + label);
}

(async () => {
  // find a page target
  const targets = await (await fetch(`http://localhost:${PORT}/json`)).json();
  const page = targets.find((t) => t.type === "page");
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = (e) => j(new Error("ws open failed")); });
  await send(ws, "Page.enable");
  await send(ws, "Runtime.enable");

  // ---- /sym/indexes ----
  await send(ws, "Page.navigate", { url: "http://localhost:3000/sym/indexes" });
  await pollFor(ws, `!!document.body && document.body.innerText.includes('Benchmark indexes')`, "page shell");
  // VIX must be in the LIST (a clickable button)
  await pollFor(ws, `[...document.querySelectorAll('button')].some(b => b.textContent.includes('CBOE Volatility Index'))`, "VIX list button");
  const listOk = await evals(ws, `[...document.querySelectorAll('button')].filter(b => b.textContent.includes('CBOE Volatility Index')).length`);
  // click the VIX list button (the real React onClick)
  await evals(ws, `(() => { const b=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('CBOE Volatility Index')); b.click(); return true; })()`);
  // wait for the detail to load (chart svg present after the /levels fetch)
  await pollFor(ws, `!!document.querySelector('svg[aria-label="Index level time series"]')`, "VIX level chart");
  // extract detail facts
  const facts = await evals(ws, `(() => {
    // innerText reflects CSS text-transform:uppercase, so compare case-insensitively
    const txt = document.body.innerText;
    const low = txt.toLowerCase();
    const hasNote = /change in the level/i.test(txt) && /not an investment return/i.test(txt);
    const hasPa = /p\\.a\\./.test(txt);                       // CAGR annualised marker — should be ABSENT
    const monthlyLevel = low.includes('monthly level change (%)');
    const monthlyReturns = low.includes('monthly returns (%)');
    const headerVix = txt.includes('CBOE Volatility Index (VIX)');
    const latest = (low.match(/latest level\\s*([\\d.,]+)/) || ['',''])[1];  // the rendered level value
    return JSON.stringify({ hasNote, hasPa, monthlyLevel, monthlyReturns, headerVix, latest });
  })()`);
  await sleep(400);
  const shot = await send(ws, "Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  const fs = await import("node:fs");
  fs.writeFileSync(SHOT, Buffer.from(shot.data, "base64"));

  // ---- /monitor/wei ----
  await send(ws, "Page.navigate", { url: "http://localhost:3000/monitor/wei" });
  await pollFor(ws, `!!document.body && document.body.innerText.length > 200`, "wei shell");
  await sleep(1500); // let the board fetch resolve
  const weiVix = await evals(ws, `(document.body.innerText.match(/CBOE Volatility Index/g) || []).length`);
  const weiHasRows = await evals(ws, `(document.body.innerText.match(/S&P 500|FTSE|MSCI|Nikkei/g) || []).length > 0`);

  console.log("LIST_VIX_BUTTONS=" + listOk);
  console.log("DETAIL=" + facts);
  console.log("WEI_VIX_COUNT=" + weiVix);
  console.log("WEI_HAS_EQUITY_ROWS=" + weiHasRows);
  ws.close();
  process.exit(0);
})().catch((e) => { console.error("ERR " + e.message); process.exit(1); });
