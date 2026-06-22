# Browser verification — `indexes-add-vix` (VIX on the Indexes page)

**Verdict: PASS** (2026-06-22, real headless Chrome over CDP, against the live dev stack — API :8001, console :3000). Covers commits `0b8ac0f` (impl) + `963c389` (review patches).

## What was verified (and observed)
- **VIX in the index list** — `CBOE Volatility Index (VIX)` appears as a clickable list entry.
- **VIX detail** (after clicking it — real React `onClick`): header "CBOE Volatility Index (VIX)", latest level **16.40**, as-of 2026-06-18, from 1990-01-02; the level chart renders.
- **Honest framing (AC3)** — the amber note "…every figure on this card (including 'Since start') is a % **change in the level**, not an investment return…" is shown; the trailing cards carry **no annualised "p.a." (CAGR)** sub-lines; the monthly table is relabelled **"Monthly level change (%)"** (not "returns").
- **WEI board (AC4)** — `/monitor/wei` shows **0** VIX mentions (equity rows present), confirming VIX is excluded from the equity board.
- **Probe (positive control)** — the default equity selection (MSCI World) still shows `p.a.` CAGR cards + "Monthly returns (%)" + no vol-note, proving the framing is conditional on `category`, not a global change.

See `vix_verify.png` for the captured VIX detail screen.

## Replay
The dev stack must be up (`npm run dev` → API :8001, console :3000). Then:

```pwsh
# 1. launch a headless Chrome with a CDP port
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --headless=new --disable-gpu --no-sandbox `
   --remote-debugging-port=9223 --user-data-dir=$env:TEMP\cdpverify --window-size=1400,2200 about:blank

# 2. drive it (Node 22+ — uses the global browser-style WebSocket, not the `ws` pkg)
node cdp_verify.mjs vix_verify.png   # main flow + screenshot
node cdp_probe.mjs                   # equity positive-control probe
# 3. Stop-Process the chrome when done
```

Notes:
- `cdp_verify.mjs` / `cdp_probe.mjs` are CDP drivers (navigate → click the real list button → read the rendered DOM → screenshot). No puppeteer/playwright dependency — raw CDP over the Node global `WebSocket`.
- `innerText` reflects CSS `text-transform:uppercase`, so heading comparisons are case-insensitive (a gotcha, not a bug).
