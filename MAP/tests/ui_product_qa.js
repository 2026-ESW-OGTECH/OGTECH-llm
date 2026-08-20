/* 1024×600 제품 UI의 부팅 잠금·터치 크기·야간 모드 회귀 검사.
 * 실행 환경에는 Playwright가 필요하며 제품 런타임에는 포함하지 않는다. */

"use strict";

const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const baseUrl = process.argv[2] || "http://127.0.0.1:8899/product/";
const outputDir = path.resolve(process.argv[3] || "test-results");

function requireCondition(condition, message) {
  if (!condition) throw new Error(message);
}

async function main() {
  fs.mkdirSync(outputDir, { recursive: true });
  const launchOptions = { headless: true };
  if (process.env.SAFEAID_BROWSER_EXECUTABLE) {
    launchOptions.executablePath = process.env.SAFEAID_BROWSER_EXECUTABLE;
  }
  const browser = await chromium.launch(launchOptions);
  const page = await browser.newPage({ viewport: { width: 1024, height: 600 } });
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });

  try {
    await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 10_000 });
    await page.locator("#bootNotice").waitFor({ state: "visible" });
    const initiallyDisabled = await page.locator("#bootAcknowledge").isDisabled();

    await page.keyboard.press("N");
    await page.waitForTimeout(150);
    const lockedVoiceState = await page.evaluate(async () => {
      const response = await fetch("/api/voice", { cache: "no-store" });
      return response.json();
    });
    await page.keyboard.press("Tab");
    const lockedFocus = await page.evaluate(() => document.activeElement?.id || "");

    let backgroundClickBlocked = false;
    try {
      await page.locator("#btnNight").click({ timeout: 700 });
    } catch (_error) {
      backgroundClickBlocked = true;
    }

    await page.waitForFunction(
      () => !document.querySelector("#bootAcknowledge").disabled,
      null,
      { timeout: 8_000 },
    );
    const boot = await page.evaluate(() => {
      const card = document.querySelector(".boot-notice-card");
      const rect = card.getBoundingClientRect();
      const details = [...document.querySelectorAll("#bootChecks small")].map((item) => ({
        text: item.textContent.trim(),
        display: getComputedStyle(item).display,
        height: item.getBoundingClientRect().height,
      }));
      return {
        viewport: { width: innerWidth, height: innerHeight },
        document: {
          scrollWidth: document.documentElement.scrollWidth,
          scrollHeight: document.documentElement.scrollHeight,
        },
        card: {
          top: rect.top,
          bottom: rect.bottom,
          width: rect.width,
          height: rect.height,
          scrollHeight: card.scrollHeight,
          clientHeight: card.clientHeight,
          scrollTop: card.scrollTop,
        },
        summary: document.querySelector("#bootDiagnosticSummary").textContent.trim(),
        states: [...document.querySelectorAll("#bootChecks li")].map((item) => item.dataset.state),
        details,
        screenInert: document.querySelector("#screen").inert,
        screenAriaHidden: document.querySelector("#screen").getAttribute("aria-hidden"),
        acknowledgeHeight: document.querySelector("#bootAcknowledge").getBoundingClientRect().height,
      };
    });
    await page.screenshot({ path: path.join(outputDir, "product_boot_1024x600.png") });

    requireCondition(initiallyDisabled, "부팅 ACK가 최초 로드부터 열려 있음");
    requireCondition(lockedVoiceState.ui?.night === false, "부팅 잠금 중 N 키가 야간 모드를 변경함");
    requireCondition(["bootNotice", "bootAcknowledge"].includes(lockedFocus), "부팅 잠금 중 포커스가 배경으로 이탈함");
    requireCondition(backgroundClickBlocked, "부팅 잠금 중 배경 버튼을 클릭할 수 있음");
    requireCondition(boot.screenInert && boot.screenAriaHidden === "true", "부팅 잠금 중 본 화면이 inert/aria-hidden이 아님");
    requireCondition(boot.document.scrollWidth <= 1024 && boot.document.scrollHeight <= 600, "부팅 화면이 1024×600 문서 영역을 넘침");
    requireCondition(boot.card.top >= 0 && boot.card.bottom <= 600, "부팅 카드가 화면 밖으로 잘림");
    requireCondition(boot.acknowledgeHeight >= 80, "ACK 터치 높이가 80px 미만임");
    requireCondition(boot.details.length === 6 && boot.details.every((item) => item.text && item.display !== "none" && item.height > 0), "진단 상세가 터치 화면에 노출되지 않음");
    requireCondition(boot.states.includes("demo") && boot.states.includes("waiting") && boot.states.includes("pass"), "DEMO·대기·통과 진단 상태가 구분되지 않음");

    await page.locator("#bootAcknowledge").click();
    await page.locator("#bootNotice").waitFor({ state: "hidden" });
    await page.keyboard.press("N");
    await page.waitForFunction(() => document.documentElement.dataset.night === "on", null, { timeout: 3_000 });

    const product = await page.evaluate(() => {
      const targets = [...document.querySelectorAll(".action")].map((item) => {
        const rect = item.getBoundingClientRect();
        return { id: item.id, width: rect.width, height: rect.height };
      });
      return {
        document: {
          scrollWidth: document.documentElement.scrollWidth,
          scrollHeight: document.documentElement.scrollHeight,
        },
        bootHidden: document.querySelector("#bootNotice").hidden,
        screenInert: document.querySelector("#screen").inert,
        night: document.documentElement.dataset.night,
        targets,
      };
    });
    await page.screenshot({ path: path.join(outputDir, "product_night_1024x600.png") });

    requireCondition(product.bootHidden && !product.screenInert, "ACK 이후 제품 화면 잠금이 해제되지 않음");
    requireCondition(product.night === "on", "잠금 해제 뒤 N 키 야간 모드가 동작하지 않음");
    requireCondition(product.document.scrollWidth <= 1024 && product.document.scrollHeight <= 600, "제품 화면이 1024×600 문서 영역을 넘침");
    requireCondition(product.targets.length === 4 && product.targets.every((item) => item.height >= 80), "하단 주요 동작 터치 높이가 80px 미만임");
    requireCondition(browserErrors.length === 0, `브라우저 오류 발생: ${browserErrors.join(" | ")}`);

    await page.keyboard.press("N");
    const result = {
      version: 1,
      passed: true,
      viewport: "1024x600",
      boot_lock: {
        initial_ack_disabled: initiallyDisabled,
        background_keyboard_blocked: lockedVoiceState.ui?.night === false,
        background_pointer_blocked: backgroundClickBlocked,
        focus_trapped: ["bootNotice", "bootAcknowledge"].includes(lockedFocus),
        diagnostics_summary: boot.summary,
        diagnostics_states: boot.states,
        detail_rows_visible: boot.details.length,
        card_height: boot.card.height,
        card_scroll_height: boot.card.scrollHeight,
        card_client_height: boot.card.clientHeight,
        card_scroll_top: boot.card.scrollTop,
        card_internal_scroll: boot.card.scrollHeight > boot.card.clientHeight,
      },
      product: {
        night_voice_control: product.night === "on",
        touch_targets: product.targets,
        document_size: product.document,
      },
      browser_errors: browserErrors,
    };
    fs.writeFileSync(path.join(outputDir, "product_ui_1024x600.json"), `${JSON.stringify(result, null, 2)}\n`, "utf8");
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
