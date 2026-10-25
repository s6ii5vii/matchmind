// Browser check of the whole app: playback, the agents in every mode, matches, added time, following a
// question, history, the player duel. Needs the app running (API + built dashboard on one URL):
//   APP_URL=http://127.0.0.1:8000 node e2e/smoke.mjs
import { chromium } from "playwright";

const url = process.env.APP_URL ?? "http://127.0.0.1:8000";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
let failed = 0;
const check = (name, ok) => { console.log(`${ok ? "PASS" : "FAIL"}  ${name}`); if (!ok) failed += 1; };
const slider = page.locator('input[aria-label="Match minute"]');
const scrub = async (minute) => { await slider.fill(String(minute)); await page.waitForTimeout(900); };
const clock = () => page.locator(".scoreboard .minute").textContent();
const ask = async (button) => {
  await button.click();
  await page.waitForFunction(() => document.querySelector(".ask button")?.textContent !== "Agents working…", null, { timeout: 60000 });
  await page.waitForSelector(".room .answer", { timeout: 60000 });
};

await page.goto(url);
await page.waitForSelector(".scoreboard strong:not(:empty)");

// playback and the match clock
await page.getByRole("button", { name: "Play" }).click();
await page.waitForTimeout(2500);
await page.getByRole("button", { name: "Pause" }).click();
check("Play advances the clock", !(await clock()).startsWith("0'"));
await scrub(20);
check("Score after the first goal is 1-0", (await page.locator(".big-score").textContent()).replace(/\s/g, "") === "1–0");
check("Key moments list goals and chances", (await page.locator(".moment-list li").count()) > 0);
await scrub(47);
check(`First-half added time on the clock: ${await clock()}`, /45\+\d'/.test(await clock()) && (await page.locator(".added-board").count()) === 1);
check("Timeline runs past 90 minutes", Number(await slider.getAttribute("max")) > 90);

// the agents, in all three modes
await scrub(85);
for (const mode of ["New to football", "Fan", "Analyst"]) {
  await page.getByRole("button", { name: mode, exact: true }).click();
  await ask(page.getByRole("button", { name: "Why did Riverside lose control after 60?" }));
  const answer = await page.locator(".room .answer p").textContent();
  check(`Agents answer in "${mode}": ${answer.slice(0, 80)}…`, answer.length > 30 && (await page.locator(".take").count()) >= 1);
}
check("Answer header uses football minutes", /60'/.test(await page.locator(".room .answer b").textContent()));
await page.locator(".trace-wrap summary").click();
check("Trace shows all five agents",
  /Orchestrator.*Stats.*Pundit.*Skeptic.*Narrator/s.test((await page.locator(".trace-step").allTextContents()).join(" ")));
await page.locator('input[aria-label="Question for the agents"]').fill("Is Northbridge's press working?");
await ask(page.getByRole("button", { name: "Ask the agents", exact: true }));
check("A question's assumption is checked", (await page.locator(".take.premise").count()) === 1);

// follow a question, and question history
await page.getByRole("button", { name: "Follow this question as the match goes on" }).click();
check("Followed question appears", (await page.locator(".followed-item").count()) === 1);
await page.reload();
await page.waitForSelector(".scoreboard strong:not(:empty)");
check("Question history survives a reload", (await page.locator(".history li").count()) >= 1);

// player duel
await scrub(85);
await page.locator(".duel select").first().selectOption("K. Mensah");
await page.locator(".duel select").nth(1).selectOption("S. Walker");
await page.waitForTimeout(1200);
const verdict = await page.locator(".duel-verdict p").textContent();
check(`Player duel verdict: ${verdict.slice(0, 80)}…`, verdict.includes("Mensah") || verdict.includes("Walker"));
check("Duel shows category rows and moments",
  (await page.locator(".duel-board .stat-row").count()) === 6 && (await page.locator(".moments li").count()) > 0);

// switching match
await page.getByRole("button", { name: /Hollowmere FC/ }).click();
await page.waitForFunction(() => document.querySelector(".scoreboard strong")?.textContent === "Hollowmere FC");
check("Match picker switches match and restarts it", (await slider.inputValue()) === "0" && (await page.locator(".room").count()) === 0);
check("Suggested questions follow the match", (await page.locator(".suggestions").textContent()).includes("Are Hollowmere dominating the ball?"));
await scrub(Number(await slider.getAttribute("max")));
check("Hollowmere v Stanton Vale ends 0-0", (await page.locator(".big-score").textContent()).replace(/\s/g, "") === "0–0");
check("Saves are counted", /Saves/.test(await page.locator(".stats-panel").textContent()));
await page.locator(".every-event summary").click();
await page.getByRole("tab", { name: "Cards, subs & stoppages" }).click();
check("Stoppages and substitutions in the event feed", (await page.locator(".event-item").count()) > 0);

await page.getByRole("button", { name: "Toggle theme" }).click();
check("No browser errors", errors.length === 0 || (console.log(errors), false));
await browser.close();
process.exit(failed ? 1 : 0);
