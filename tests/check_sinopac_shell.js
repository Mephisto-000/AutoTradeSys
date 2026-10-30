// AutoTradeSys fork addition (2026-10-26)
// 永豐金(sinopac)在電腦版畫面上的四件事,加上選單列那一行:
//   ① 選單列(traytext):模擬環境寫「模擬」;實盤寫「永豐金證券」(字由 renderer 交,沒交就整行不出,不拿 Sinopac 頂)
//   ② renderer 交給主行程的字(tradeLabels)多 venueSinopac,主行程的預設表也有這一格;更新確認框的模擬記號
//   ③ 純邏輯(trade.js 原文切出來跑):envMoney 把券商模擬環境(報告 venues.sinopac.simulation)當模擬;
//      頂列記號 / 視窗標題寫「永豐金證券（模擬）」;存金額框的記號照模擬(trCfPaperOnly)
//   ④ 真的開畫面(隨包 Electron + 真的 index.html,window.blave 換成假的):資產分頁價值寫 TWD、整數、現股／交割戶;
//      設定分頁模擬不標「真錢」、實盤標「真錢」;頂列記號;下單方式不列限價追價、多一行說明;啟動確認框的記號
// 跑法:node tests/check_sinopac_shell.js(BLAVE_TEST_WINDOW=1 才跑 ④ 的 Electron)
const path = require("path"), fs = require("fs"), vm = require("vm");
const SHELL = path.join(__dirname, "..", "shell");
const GATE = require("./_electron_gate");
let red = 0; const ok = (n, c, d) => { console.log((c ? "PASS  " : "FAIL  ") + n + (c || d === undefined ? "" : "  " + JSON.stringify(d))); if (!c) red++; };
const J = JSON.stringify;
const V = { credentials: true, pair: true, order: true, account: true };

if (!process.versions.electron) (() => {
  // ── ① 選單列 ──
  const TT = require(path.join(SHELL, "traytext.js"));
  const now = Math.floor(Date.now() / 1000);
  const st = (ven) => ({ alive: true, running: true, report: { venues: ven, reconciler: { alive: true, heartbeat_at: now }, daemon: { reconciler: { running: true } } } });
  const sim = TT.localLine(st({ sinopac: { ...V, simulation: true } })), live = TT.localLine(st({ sinopac: { ...V, simulation: false } }));
  ok("① localLine:永豐模擬環境 → money paper;實盤 → money real、venue sinopac", sim.money === "paper" && live.money === "real" && live.venue === "sinopac", [sim, live]);
  const L = { moneyPaper: "模擬", moneyReal: "真錢", venueSinopac: "永豐金證券", stOn: "執行中", stPaused: "已暫停", stUnknown: "讀不到狀態", stMayTrade: "可能還在下單",
    stNotStarted: "尚未啟動下單", noAccount: "還沒連接交易所", runningZ: "沒有設金額" }, TPL = "這台電腦：{money} · {state}";
  const ls = TT.statusLine(TPL, sim, L), ll = TT.statusLine(TPL, live, L);
  ok("① statusLine:模擬寫「模擬」;實盤寫「永豐金證券」(不是 Sinopac、不是真錢)", /模擬/.test(ls) && /永豐金證券/.test(ll) && !/Sinopac|真錢/.test(ll), [ls, ll]);
  ok("① 字還沒交(venueSinopac 空的):整行不出,不拿 id 首字大寫頂", TT.statusLine(TPL, live, { ...L, venueSinopac: "" }) === null);
  ok("① 其他交易所照舊:Binance 寫名字、只綁模擬寫模擬", TT.statusLine(TPL, TT.localLine(st({ binance: V })), L).indexOf("Binance") >= 0
    && TT.localLine(st({ paper: V })).money === "paper");

  // ── ② 主行程與 renderer 的字表 ──
  const mainSrc = fs.readFileSync(path.join(SHELL, "main.js"), "utf8"), src = fs.readFileSync(path.join(SHELL, "renderer", "trade.js"), "utf8");
  ok("② 主行程的預設字表有 venueSinopac(空的 = 還沒交);renderer 交 t(\"sino.venue\")", /venuePresident: "", venueSinopac: "",/.test(mainSrc)
    && /venuePresident: t\("pres\.venue"\), venueSinopac: t\("sino\.venue"\),/.test(src));
  const tpoAt = mainSrc.indexOf("function tradePaperOnly(");
  const tpo = new Function("venueReady", "_tradeHost", mainSrc.slice(tpoAt, mainSrc.indexOf("\n}\n", tpoAt) + 2) + "\nreturn tradePaperOnly;")(
    (v) => !!(v && v.credentials && v.pair && v.order && v.account), null);
  const venRep = (ven) => ({ report: { venues: ven } });
  ok("② 更新確認框的記號(主行程 tradePaperOnly):永豐模擬 = 模擬;實盤 = 真錢;模擬環境加另一家真錢 = 真錢;Blave 模擬交易照舊",
    tpo(venRep({ sinopac: { ...V, simulation: true } })) === true && tpo(venRep({ sinopac: { ...V, simulation: false } })) === false
    && tpo(venRep({ sinopac: { ...V, simulation: true }, binance: V })) === false && tpo(venRep({ paper: V })) === true);

  // ── ③ 純邏輯 ──
  const ctx = {}; vm.createContext(ctx);
  const R = path.join(SHELL, "renderer");
  vm.runInContext(fs.readFileSync(path.join(R, "strings.js"), "utf8").replace(/^const /gm, "var ") + "\n" + fs.readFileSync(path.join(R, "i18n.js"), "utf8").replace(/^(const|let) /gm, "var "), ctx);
  const cut = (n) => { const i = src.indexOf("function " + n + "("); if (i < 0) throw new Error(n); let d = 0; for (let k = src.indexOf("{", i); k < src.length; k++) { if (src[k] === "{") d++; else if (src[k] === "}" && --d === 0) return src.slice(i, k + 1); } throw new Error(n); };
  vm.runInContext(src.slice(src.indexOf("const PAPER = "), src.indexOf("const cxVenuesFor")).replace(/^const /gm, "var ") + "\n"
    + ["trVenueIds", "trVenueLabel", "envMoney", "trReport", "trCfPaperOnly"].map(cut).join("\n") + "\n" + src.match(/const envVenueText = [^\n]*/)[0].replace(/^const /, "var "), ctx);
  const rep = (simFlag) => ({ venues: { sinopac: simFlag === undefined ? V : { ...V, simulation: simFlag } } });
  ctx.LANG = "zh";
  const em = (r) => vm.runInContext(`envMoney(${J({ report: r })})`, ctx);
  ok("③ envMoney:永豐模擬環境 = paper;實盤 = real;沒帶旗標(舊 runtime)= real;Blave 模擬交易 = paper;沒連 = null",
    em(rep(true)) === "paper" && em(rep(false)) === "real" && em(rep()) === "real" && em({ venues: { paper: V } }) === "paper" && em({ venues: {} }) === null);
  const evt = (m, v) => vm.runInContext(`envVenueText(${J(m)}, ${J(v)})`, ctx);
  ok("③ 頂列記號 / 視窗標題:永豐模擬「永豐金證券（模擬）」、實盤「永豐金證券」;Blave 模擬交易照舊「模擬」、Binance 照舊",
    evt("paper", "sinopac") === "永豐金證券（模擬）" && evt("real", "sinopac") === "永豐金證券" && evt("paper", "paper") === "模擬" && evt("real", "binance") === "Binance",
    [evt("paper", "sinopac"), evt("real", "sinopac")]);
  ctx.LANG = "en";
  ok("③ 英文:SinoPac Securities (simulation)", evt("paper", "sinopac") === "SinoPac Securities (simulation)", evt("paper", "sinopac"));
  ctx.LANG = "zh";
  const cfp = (r) => { ctx.TR = { st: { report: r } }; return vm.runInContext("trCfPaperOnly()", ctx); };
  ok("③ 存金額框的記號(trCfPaperOnly):永豐模擬 → 模擬;實盤 → 實盤;Blave 模擬交易照舊", cfp(rep(true)) === true && cfp(rep(false)) === false && cfp(rep()) === false && cfp({ venues: { paper: V } }) === true);

  // ── ④ 交給 Electron ──
  const bin = GATE.bin(SHELL, "④");
  if (!bin) { console.log(red ? `\n${red} 紅` : "\nALL PASS"); process.exit(red ? 1 : 0); }
  const r = require("child_process").spawnSync(bin, [__filename], { stdio: "inherit" });
  process.exit(red || r.status !== 0 ? 1 : 0);
})();
else {

const { app, BrowserWindow } = require("electron");
const os = require("os");
app.setPath("userData", fs.mkdtempSync(path.join(os.tmpdir(), "blave-sinopac-")));
const now = Math.floor(Date.now() / 1000);
const LIST = [{ name: "tw_sinopac_ma", displayName: "0050 SMA", hasBacktest: true, symbol: "0050" }];
const report = (sim, exec) => ({
  venues: { sinopac: { ...V, simulation: sim } },
  account: { read_at: now - 20, venues: { sinopac: { ok: true, equity: 356000, currency: "TWD", error: null, positions: {},
    holdings: [{ asset: "0050", amount: 1000, usdt_value: 200000, wallet: "stock" }, { asset: "TWD", amount: 126000, usdt_value: 126000, wallet: "cash" },
      { asset: "00679B", amount: 1000, usdt_value: 30000.4, wallet: "stock" }] } } },
  config: { amounts: { tw_sinopac_ma: 100000 }, exchanges: { tw_sinopac_ma: "sinopac" }, execution_default: exec || { type: "market" } },
  quote_ccy: { tw_sinopac_ma: "TWD" }, states: { tw_sinopac_ma: { symbol: "0050", position: 1, market: "spot", ts: now - 300 } },
  self_ledger: true, can_flatten: true, reconciler: { alive: true, heartbeat_at: now - 10 }, daemon: { heartbeat_at: now - 5, reconciler: { running: true } },
  last_reconcile: { ts: now - 30, actual: {}, ledger: {}, gates: {} }, halt: null, order_errors: [], orders: [], events: [],
});
const STUB = `window.__over = {}; window.__calls = [];
window.blave = new Proxy({}, { get: (_, k) => typeof k !== "string" ? undefined
  : k.startsWith("on") ? () => {} : k === "tradeLabels" ? () => {}
  : async (...a) => { window.__calls.push([k, a]); if (k in window.__over) return window.__over[k](...a);
      return ({ getLocale: "zh-TW", loadConnection: { kind: "claude" }, detectAgents: { claude: { installed: true, loggedIn: true }, codex: { installed: false } },
        listStrategies: ${J(LIST)}, listSessions: [], loadSession: [], loadSessionImages: [], updateState: { phase: "idle", current: "0.0.0" } })[k]; } });`;
const wait = (ms) => new Promise((res) => setTimeout(res, ms));

app.whenReady().then(async () => {
  if (app.dock) app.dock.hide();
  setTimeout(() => { console.log("FAIL  ④ 逾時(90 秒內沒跑完)"); app.exit(1); }, 90000).unref();
  const pre = path.join(app.getPath("userData"), "stub.js"); fs.writeFileSync(pre, STUB);
  const w = new BrowserWindow({ width: 1280, height: 900, show: false, webPreferences: { offscreen: true, preload: pre, contextIsolation: false, sandbox: false } });
  const errs = []; w.webContents.on("console-message", (_e, level, msg) => { if (level >= 3) errs.push(msg.slice(0, 200)); });
  await w.loadFile(path.join(SHELL, "renderer", "index.html"));
  await wait(1200);
  const js = (s) => w.webContents.executeJavaScript(s, true);
  const load = async (rp) => { await js(`(() => { trPollSoon = () => {}; trPoll = async () => {}; envSwitch("local"); TR_BAGS.local.st = { alive: true, report: ${J(rp)} };
    TR.list = ${J(LIST)}; TR.listLoaded = true; TR.sig = {}; $("tr-nav").click(); })()`); await wait(400); };
  const tab = async (k) => { await js(`(() => { trSetTab(${J(k)}); TR.sig = {}; trPaint(); })()`); await wait(300); };

  // 模擬環境
  await load(report(true));
  await tab("assets");
  const rows = await js(`[...$("tr-assets").querySelectorAll("table tbody tr")].map((tr) => ({ a: tr.cells[0].firstChild.textContent, tag: (tr.cells[0].querySelector(".mkt-tag") || {}).textContent,
    v: tr.cells[2].childNodes[0].textContent, ccy: (tr.cells[2].querySelector(".ccy") || {}).textContent }))`);
  ok("④ 資產分頁:持倉價值的單位是 TWD(不是 USDT)、整數(同淨值的 TWD 規則)", rows.length === 3 && rows.every((x) => x.ccy === "TWD") && J(rows.map((x) => x.v)) === J(["200,000", "126,000", "30,000"]), rows);
  ok("④ 資產分頁:帳戶標籤是「現股」「交割戶」(不是 stock / cash)", J(rows.map((x) => x.tag)) === J(["現股", "交割戶", "現股"]), rows);
  await tab("set");
  const mk = await js(`(() => { const m = $("tr-set").querySelector(".cx-row .mode"); return m ? { t: m.textContent, c: m.className } : null; })()`);
  // 「模擬」只留頂列記號與確認框標題(上游設計;check_shell_trade.js 守著):帳戶列跟 Blave 模擬交易一樣不掛記號
  ok("④ 設定分頁(模擬環境):帳戶列不標「真錢」(跟模擬交易一樣不掛記號)", mk === null, mk);
  const tb = await js(`({ t: $("tr-tb-mode").textContent, c: $("tr-tb-mode").className, hidden: $("tr-tb-mode").hidden, title: document.title })`);
  ok("④ 頂列記號與視窗標題:「永豐金證券（模擬）」、模擬的樣式", tb.t === "永豐金證券（模擬）" && /\bpaper\b/.test(tb.c) && !tb.hidden && tb.title.indexOf("永豐金證券（模擬）") >= 0, tb);
  const ex = await js(`({ opts: [...$("tr-exec-sel").options].map((o) => o.value), note: ($("tr-set").querySelector(".tr-exec-note") || {}).textContent, want: t("tr.exec.sino") })`);
  ok("④ 下單方式:永豐不列「限價追價」(會變市價);市價、TWAP、自訂入口照列;下面一行講為什麼", J(ex.opts) === J(["market", "twap", "custom-ask"]) && ex.note === ex.want && /限價追價/.test(ex.want), ex);
  await js(`window.__box = null; confirmBox = (o) => { window.__box = o; }; trAskStart(null)`); await wait(200);
  const sb = await js(`window.__box && { mark: window.__box.mark, kind: window.__box.markKind, want: t("tr.mode.paper") }`);
  ok("④ 啟動下單確認框(模擬環境):記號是「模擬」", !!sb && sb.mark === sb.want && sb.kind === "paper", sb);

  // 已經設成限價追價(agent 改的):選單照列出來才看得到現況,原理 tooltip 不講(那個說明對永豐不成立)
  await load(report(true, { type: "chase" })); await tab("set");
  const ch = await js(`({ opts: [...$("tr-exec-sel").options].map((o) => o.value), val: $("tr-exec-sel").value, tip: !!$("tr-set").querySelector(".tr-tipb") })`);
  ok("④ 已設成限價追價:選單列得出現況、沒有追價原理的 tooltip", ch.opts.indexOf("chase") >= 0 && ch.val === "chase" && !ch.tip, ch);

  // 實盤
  await load(report(false)); await tab("set");
  const mk2 = await js(`(() => { const m = $("tr-set").querySelector(".cx-row .mode"); return m ? { t: m.textContent, c: m.className } : null; })()`);
  const tb2 = await js(`({ t: $("tr-tb-mode").textContent, c: $("tr-tb-mode").className })`);
  ok("④ 實盤(SINOPAC_LIVE=true):帳戶列標「真錢」;頂列寫「永豐金證券」", !!mk2 && mk2.t === "真錢" && /\breal\b/.test(mk2.c) && tb2.t === "永豐金證券" && /\breal\b/.test(tb2.c), [mk2, tb2]);
  await js(`window.__box = null; trAskStart(null)`); await wait(200);
  const sb2 = await js(`window.__box && { mark: window.__box.mark, want: t("tr.mode.real") }`);
  ok("④ 啟動下單確認框(實盤):記號是「真錢」", !!sb2 && sb2.mark === sb2.want, sb2);
  ok("④ 整個過程畫面沒有丟出錯誤", errs.length === 0, errs);
  console.log(red ? `\n${red} 紅` : "\nALL PASS");
  app.exit(red ? 1 : 0);
});
}
