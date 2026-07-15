#!/usr/bin/env node
import { existsSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { launch } from "cloakbrowser";
import {
  AUTH_FILE, confirmationToken, publicSummary, readJson, redact, updateState, writeJson,
} from "./lib.mjs";

const RUN_DIR = process.env.XHS_RUN_DIR;
if (!RUN_DIR) throw new Error("XHS_RUN_DIR is required");
const LOGIN_URL = "https://creator.xiaohongshu.com/login";
const PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function arg(name) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

async function screenshot(page, name) {
  const path = join(RUN_DIR, name);
  await page.screenshot({ path, fullPage: false, animations: "disabled" });
  return path;
}

async function open(page, url) {
  let lastError;
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    try {
      const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 90_000 });
      if (response?.ok()) { await page.waitForTimeout(3000); return; }
      lastError = new Error(`HTTP ${response?.status() ?? "unknown"}`);
    } catch (error) { lastError = error; }
    await sleep(Math.min(attempt * 2000, 8000));
  }
  throw new Error(`页面连续重试后仍无法打开: ${String(lastError)}`);
}

async function bodyText(page) {
  return page.locator("body").innerText().catch(() => "");
}

async function detectRisk(page) {
  return /图形验证码|安全验证|异常操作|风险提示|请完成验证|滑块验证/.test(await bodyText(page));
}

async function isLoggedIn(page) {
  const url = new URL(page.url());
  return url.hostname === "creator.xiaohongshu.com" && /\/new\//.test(url.pathname);
}

async function waitForLogin(page, timeout = 600_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await detectRisk(page)) throw new Error("RISK_VERIFICATION_REQUIRED");
    if (await isLoggedIn(page)) return;
    await sleep(1500);
  }
  throw new Error("等待登录完成超时");
}

async function switchToQr(page) {
  const point = await page.evaluate(() => {
    const title = [...document.querySelectorAll("*")].find((element) => element.children.length === 0 && element.textContent?.trim() === "短信登录");
    if (!title) return null;
    let card = title;
    while (card && card.getBoundingClientRect().width < 250) card = card.parentElement;
    if (!card) return null;
    const box = card.getBoundingClientRect();
    return { x: box.right - 25, y: box.top + 25 };
  });
  if (!point) throw new Error("无法定位扫码登录入口");
  await page.mouse.click(point.x, point.y);
  await page.waitForTimeout(1500);
  let qrVisible = await page.evaluate(() =>
    [...document.querySelectorAll("canvas,img,[class*=qr i],[id*=qr i]")].some((element) => {
      const box = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return box.width >= 120 && box.height >= 120 && style.visibility !== "hidden" && style.display !== "none";
    }),
  );
  if (!qrVisible) {
    // The production login corner has no accessible name; keep the verified fixed-viewport fallback.
    await page.mouse.click(1275, 345);
    await page.waitForTimeout(1500);
    qrVisible = await page.evaluate(() =>
      [...document.querySelectorAll("canvas,img,[class*=qr i],[id*=qr i]")].some((element) => {
        const box = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return box.width >= 120 && box.height >= 120 && style.visibility !== "hidden" && style.display !== "none";
      }),
    );
  }
  if (!qrVisible) {
    await screenshot(page, "qr-switch-failed.png");
    throw new Error("已点击扫码入口，但未检测到二维码");
  }
}

async function runLogin(context, page) {
  const mode = arg("mode") || "qr";
  await open(page, LOGIN_URL);
  if (mode === "qr") {
    await switchToQr(page);
    const qr = await screenshot(page, "qr.png");
    updateState(RUN_DIR, { status: "waiting_for_scan", qrScreenshot: qr });
  } else {
    const phone = arg("phone");
    await page.getByPlaceholder("手机号").fill(phone);
    const checkbox = page.locator('input[type="checkbox"]').first();
    if (await checkbox.count() && !(await checkbox.isChecked())) await checkbox.check({ force: true });
    await page.getByText("发送验证码", { exact: true }).click();
    const consent = page.getByText("同意并继续", { exact: true });
    if (await consent.count() && await consent.first().isVisible()) await consent.first().click();
    updateState(RUN_DIR, { status: "waiting_for_code", codeScreenshot: await screenshot(page, "sms-code.png") });
    const codePath = join(RUN_DIR, "sms-code.txt");
    const deadline = Date.now() + 600_000;
    while (Date.now() < deadline && !existsSync(codePath)) {
      if (await detectRisk(page)) throw new Error("RISK_VERIFICATION_REQUIRED");
      await sleep(1000);
    }
    if (!existsSync(codePath)) throw new Error("等待短信验证码超时");
    const code = readFileSync(codePath, "utf8").trim();
    rmSync(codePath, { force: true });
    await page.getByPlaceholder("验证码").fill(code);
    await page.getByText("登 录", { exact: true }).click();
  }
  await waitForLogin(page);
  await context.storageState({ path: AUTH_FILE });
  await page.waitForLoadState("domcontentloaded").catch(() => {});
  await page.waitForTimeout(5000);
  const account = await page.locator('[class*="user" i], [class*="account" i]').first().innerText()
    .catch(() => page.locator("body").innerText().then((text) => text.split("\n").find((line) => line.trim()) || "unknown"));
  updateState(RUN_DIR, {
    status: "logged_in",
    account,
    currentUrl: page.url(),
    authState: AUTH_FILE,
    successScreenshot: await screenshot(page, "login-success.png"),
  });
}

async function setSwitch(page, label, wanted) {
  const row = page.getByText(label, { exact: true }).first();
  if (!(await row.count())) throw new Error(`未找到设置: ${label}`);
  const container = row.locator("xpath=ancestor::*[.//*[@role='switch'] or .//input[@type='checkbox']][1]");
  const control = container.locator('[role="switch"], input[type="checkbox"]').first();
  if (!(await control.count())) throw new Error(`未找到设置开关: ${label}`);
  const checked = await control.evaluate((element) => element.getAttribute("aria-checked") === "true" || element.checked === true);
  if (checked === wanted) return;
  await control.evaluate((element) => element.click());
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const current = await control.evaluate((element) => element.getAttribute("aria-checked") === "true" || element.checked === true);
    if (current === wanted) return;
    await page.waitForTimeout(100);
  }
  throw new Error(`设置开关状态未生效: ${label}`);
}

async function setOriginalStatement(page, wanted) {
  const row = page.getByText("原创声明", { exact: true }).first();
  if (!(await row.count())) throw new Error("未找到设置: 原创声明");
  const control = row.locator("xpath=../..").locator('input[type="checkbox"]');
  if ((await control.count()) !== 1) throw new Error("未找到原创声明开关");
  const checked = await control.isChecked();
  if (!wanted) {
    if (!checked) return;
    await control.evaluate((element) => element.click());
    await page.waitForFunction((element) => element.checked === false, await control.elementHandle(), { timeout: 5000 });
    return;
  }
  if (checked) return;

  await control.evaluate((element) => element.click());
  const confirmText = page.getByText("声明原创", { exact: true }).last();
  await confirmText.waitFor({ state: "visible", timeout: 10_000 });
  const agreementText = page.getByText(/我已阅读并同意/).last();
  const agreement = agreementText.locator("xpath=../..").locator('input[type="checkbox"]');
  if ((await agreement.count()) !== 1) throw new Error("未找到原创声明须知确认框");
  if (!(await agreement.isChecked())) await agreement.evaluate((element) => element.click());
  const confirmButton = confirmText.locator("xpath=ancestor::button[1]");
  await confirmButton.waitFor({ state: "visible", timeout: 5000 });
  for (let attempt = 0; attempt < 30 && await confirmButton.isDisabled(); attempt += 1) {
    await page.waitForTimeout(100);
  }
  if (await confirmButton.isDisabled()) throw new Error("原创声明确认按钮未启用");
  await confirmButton.click();
  await confirmText.waitFor({ state: "hidden", timeout: 10_000 });
  if (!(await control.isChecked())) throw new Error("原创声明确认后未保持开启");
}

async function clickCreatorTab(page, label) {
  const matches = page.getByText(label, { exact: true });
  const selected = await matches.evaluateAll((nodes) => {
    for (const node of nodes) {
      const target = node.closest(".creator-tab") || node;
      const box = target.getBoundingClientRect();
      const inViewport = box.width > 0 && box.height > 0 && box.right > 0 && box.bottom > 0
        && box.left < window.innerWidth && box.top < window.innerHeight;
      if (inViewport) {
        target.setAttribute("data-xhs-creator-tab-target", "true");
        return true;
      }
    }
    return false;
  });
  if (!selected) throw new Error(`未找到视口内的创作类型 tab: ${label}`);
  const target = page.locator('[data-xhs-creator-tab-target="true"]').first();
  await target.scrollIntoViewIfNeeded();
  await target.click({ force: true });
  await target.evaluate((element) => element.removeAttribute("data-xhs-creator-tab-target"));
}

async function fillTitle(page, title) {
  const inputs = page.getByPlaceholder(/填写标题/);
  const selected = await inputs.evaluateAll((nodes) => {
    for (const node of nodes) {
      const box = node.getBoundingClientRect();
      const style = getComputedStyle(node);
      const visible = box.width > 0 && box.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      if (visible) {
        node.setAttribute("data-xhs-title-input", "true");
        return true;
      }
    }
    return false;
  });
  if (!selected) throw new Error("未找到可见的标题输入框");
  const input = page.locator('[data-xhs-title-input="true"]').first();
  await input.fill(title);
  await input.press("Tab");
  const value = await input.inputValue();
  await input.evaluate((element) => element.removeAttribute("data-xhs-title-input"));
  if (value !== title) throw new Error(`标题填写结果不一致: ${value}`);
}

async function verifyTitlePreview(page, title) {
  try {
    await page.waitForFunction((expected) => [...document.querySelectorAll("body *")].some((element) => {
      if (element.children.length > 0 || element.textContent?.trim() !== expected) return false;
      const box = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return box.width > 0 && box.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    }), title, { timeout: 5000 });
  } catch {
    throw new Error(`标题未同步到笔记预览: ${title}`);
  }
}

function isImageUploadRequest(request) {
  if (request.method() !== "PUT") return false;
  try {
    const hostname = new URL(request.url()).hostname;
    return hostname === "ros-upload.xiaohongshu.com" || hostname.endsWith(".xhscdn.com");
  } catch {
    return false;
  }
}

function createImageUploadTracker(page) {
  const pending = new Set();
  let started = 0;
  let successful = 0;
  let lastFailure = null;
  let lastActivity = Date.now();

  page.on("request", (request) => {
    if (!isImageUploadRequest(request)) return;
    pending.add(request);
    started += 1;
    lastActivity = Date.now();
  });
  page.on("response", (response) => {
    const request = response.request();
    if (!isImageUploadRequest(request)) return;
    lastActivity = Date.now();
    if (response.ok()) successful += 1;
    else lastFailure = `图片上传请求失败: HTTP ${response.status()}`;
  });
  page.on("requestfinished", (request) => {
    if (!isImageUploadRequest(request)) return;
    pending.delete(request);
    lastActivity = Date.now();
  });
  page.on("requestfailed", (request) => {
    if (!isImageUploadRequest(request)) return;
    pending.delete(request);
    lastActivity = Date.now();
    lastFailure = `图片上传请求失败: ${request.failure()?.errorText || "unknown"}`;
  });

  return {
    snapshot: () => ({ started, successful }),
    async waitForNext(previous, timeout = 120_000) {
      const deadline = Date.now() + timeout;
      while (Date.now() < deadline) {
        const quietFor = Date.now() - lastActivity;
        if (started > previous.started && successful > previous.successful && pending.size === 0 && quietFor >= 1000) return;
        if (started > previous.started && successful === previous.successful && pending.size === 0 && quietFor >= 3000) {
          throw new Error(lastFailure || "图片上传请求未成功");
        }
        await sleep(250);
      }
      throw new Error(started > previous.started ? "等待图片上传完成超时" : "未检测到图片上传请求");
    },
  };
}

async function assertImagesUploaded(page) {
  const text = await bodyText(page);
  if (/上传失败|重新上传/.test(text)) throw new Error("图片上传失败");
}

async function uploadImages(page, images) {
  await clickCreatorTab(page, "上传图文");
  updateState(RUN_DIR, { status: "image_tab_selected" });
  const uploads = createImageUploadTracker(page);
  const [first, ...remaining] = images;
  const input = page.locator('input[type="file"]').first();
  const firstUpload = uploads.snapshot();
  if (await input.count()) {
    await input.setInputFiles(first);
  } else {
    const chooser = page.waitForEvent("filechooser");
    await page.getByText("上传图片", { exact: true }).click();
    await (await chooser).setFiles(first);
  }
  await page.getByText("图片编辑", { exact: true }).waitFor({ state: "visible", timeout: 120_000 });
  await uploads.waitForNext(firstUpload);
  await assertImagesUploaded(page);
  if (remaining.length) {
    const titleBox = await page.getByText("图片编辑", { exact: true }).boundingBox();
    if (!titleBox) throw new Error("无法定位图片追加区域");
    const found = await page.evaluate(({ x, y }) => {
      let element = document.elementFromPoint(x, y);
      for (let depth = 0; element && depth < 8; depth += 1, element = element.parentElement) {
        const addInput = element.querySelector('input[type="file"]');
        if (addInput) { addInput.setAttribute("data-xhs-image-add", "true"); return true; }
      }
      return false;
    }, { x: titleBox.x + 40, y: titleBox.y + 80 });
    if (!found) throw new Error("追加图片区域中未找到文件输入框");
    for (const [index, image] of remaining.entries()) {
      const previousUpload = uploads.snapshot();
      await page.locator('input[data-xhs-image-add="true"]').setInputFiles(image);
      const expected = `${index + 2}/18`;
      await page.waitForFunction((count) => document.body.innerText.includes(count), expected, { timeout: 60_000 });
      await uploads.waitForNext(previousUpload);
      await assertImagesUploaded(page);
    }
  }
  await page.getByPlaceholder(/填写标题/).waitFor({ state: "visible", timeout: 60_000 });
  await page.waitForTimeout(1000);
  await assertImagesUploaded(page);
  updateState(RUN_DIR, { status: "images_uploaded", imageCount: images.length });
}

async function chooseVisibility(page, visibility) {
  await page.getByText(/^(公开可见|仅自己可见|仅互关好友可见)$/).first().click();
  await page.getByText(visibility, { exact: true }).last().click();
}

async function setCollection(page, collection) {
  if (!collection) return;
  await page.getByText("选择合集", { exact: true }).click();
  if (collection.create) {
    await page.getByText("创建合集", { exact: true }).click();
    const dialog = page.getByText("创建合集", { exact: true }).last().locator("xpath=ancestor::*[@role='dialog' or contains(@class,'modal')][1]");
    const inputs = dialog.locator("input, textarea");
    await inputs.nth(0).fill(collection.name);
    if (collection.description) await inputs.nth(1).fill(collection.description);
    await page.getByText("创建并加入", { exact: true }).click();
  } else {
    const matches = page.getByText(collection.name, { exact: true });
    if ((await matches.count()) !== 1) throw new Error(`合集名称不存在或不唯一: ${collection.name}`);
    await matches.click();
  }
}

async function setLocation(page, location) {
  if (!location) return;
  await page.getByText("添加地点", { exact: true }).click();
  const input = page.locator('input[placeholder*="地点"], input[placeholder*="搜索"]').last();
  await input.fill(location.name || location);
  await page.waitForTimeout(1500);
  const candidates = await page.locator('[role="option"], [class*="location" i]').evaluateAll((nodes) => nodes.map((node) => node.textContent?.trim()).filter(Boolean));
  const needle = location.name || location;
  const exact = candidates.filter((candidate) => candidate.includes(needle) && (!location.address || candidate.includes(location.address)));
  if (exact.length !== 1) throw new Error(`地点候选不唯一: ${JSON.stringify(candidates.slice(0, 10))}`);
  await page.getByText(exact[0], { exact: true }).click();
}

async function setSchedule(page, scheduledAt) {
  if (!scheduledAt) return;
  await setSwitch(page, "定时发布", true);
  const [date, time] = scheduledAt.split(" ");
  const inputs = page.locator('input[type="text"], input:not([type])');
  const count = await inputs.count();
  let filled = 0;
  for (let index = 0; index < count; index += 1) {
    const input = inputs.nth(index);
    const placeholder = (await input.getAttribute("placeholder")) || "";
    if (/日期|年-月-日/.test(placeholder)) { await input.fill(date); filled += 1; }
    if (/时间|时:分/.test(placeholder)) { await input.fill(time); filled += 1; }
  }
  if (filled < 2) throw new Error("无法定位定时发布的日期和时间输入框");
}

function cdpNodeText(node) {
  if (node.nodeName === "#text") return node.nodeValue || "";
  return (node.children || []).map(cdpNodeText).join("");
}

async function clickClosedShadowButton(page, label) {
  const client = await page.context().newCDPSession(page);
  try {
    const { root } = await client.send("DOM.getDocument", { depth: -1, pierce: true });
    let target;
    const visit = (node, insidePublishButton = false) => {
      const inside = insidePublishButton || node.nodeName === "XHS-PUBLISH-BTN";
      if (inside && node.nodeName === "BUTTON" && cdpNodeText(node).trim() === label) target = node;
      for (const child of [...(node.children || []), ...(node.shadowRoots || [])]) visit(child, inside);
    };
    visit(root);
    if (!target) throw new Error(`未找到真实按钮节点: ${label}`);

    const attributes = Object.fromEntries(Array.from(
      { length: Math.floor((target.attributes || []).length / 2) },
      (_, index) => [target.attributes[index * 2], target.attributes[index * 2 + 1]],
    ));
    if (attributes.disabled !== undefined || attributes["aria-disabled"] === "true") {
      throw new Error(`按钮当前不可用: ${label}`);
    }
    const { object } = await client.send("DOM.resolveNode", { backendNodeId: target.backendNodeId });
    if (!object.objectId) throw new Error(`无法解析真实按钮节点: ${label}`);
    const result = await client.send("Runtime.callFunctionOn", {
      objectId: object.objectId,
      functionDeclaration: "function() { this.click(); return true; }",
      returnByValue: true,
    });
    if (result.exceptionDetails || result.result?.value !== true) throw new Error(`点击真实按钮失败: ${label}`);
  } finally {
    await client.detach().catch(() => {});
  }
}

async function clickFooterButton(page, action, expectedText) {
  const host = page.locator("xhs-publish-btn").first();
  await host.waitFor({ state: "visible", timeout: 30_000 });
  const attributes = await host.evaluate((element) => Object.fromEntries([
    "is-publish", "is-save-draft", "submit-text", "save-text",
    "submit-disabled", "submit-loading", "save-disabled",
  ].map((name) => [name, element.getAttribute(name)])));
  if (action === "publish") {
    if (attributes["is-publish"] !== "true") throw new Error("当前页面不允许发布");
    if (attributes["submit-disabled"] === "true" || attributes["submit-loading"] === "true") {
      throw new Error("发布按钮当前不可用");
    }
    if (expectedText && attributes["submit-text"] !== expectedText) {
      throw new Error(`发布按钮文本不一致: ${attributes["submit-text"] || "empty"}`);
    }
  } else if (attributes["is-save-draft"] !== "true" || attributes["save-disabled"] === "true") {
    return false;
  }
  await clickClosedShadowButton(page, action === "publish" ? expectedText : attributes["save-text"]);
  return true;
}

async function clickDraft(page) {
  const clicked = await clickFooterButton(page, "draft");
  if (clicked) await page.waitForTimeout(1000);
  return clicked;
}

function isPublishResponse(response) {
  if (response.request().method() !== "POST") return false;
  try {
    return /\/note\/post\/?$/.test(new URL(response.url()).pathname);
  } catch {
    return false;
  }
}

async function publishResponseResult(response) {
  if (!response) return { confirmed: false, error: "点击发布后未检测到发布接口响应" };
  let payload;
  let responseText = "";
  try {
    responseText = await response.text();
    payload = JSON.parse(responseText);
  } catch {}
  const confirmed = response.ok() && (
    payload?.success === true
    || payload?.code === 0
    || payload?.code === "0"
    || payload?.result === 0
    || payload?.result === "0"
  );
  if (confirmed) return { confirmed: true };
  const detail = redact(responseText).replace(/\s+/g, " ").slice(0, 500);
  return {
    confirmed: false,
    error: `发布接口返回未确认成功: HTTP ${response.status()}${detail ? ` ${detail}` : ""}`,
  };
}

async function verifyPublishedInNoteManager(context, title) {
  const manager = await context.newPage();
  try {
    await open(manager, "https://creator.xiaohongshu.com/new/note-manager");
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline) {
      if ((await bodyText(manager)).includes(title)) {
        return { confirmed: true, screenshot: await screenshot(manager, "note-manager.png") };
      }
      await manager.waitForTimeout(3000);
      await manager.reload({ waitUntil: "domcontentloaded", timeout: 90_000 }).catch(() => {});
    }
    return { confirmed: false, screenshot: await screenshot(manager, "note-manager.png") };
  } finally {
    await manager.close().catch(() => {});
  }
}

async function prepare(page) {
  const request = readJson(join(RUN_DIR, "request.json"));
  await open(page, PUBLISH_URL);
  if (page.url().includes("/login")) throw new Error("AUTH_EXPIRED");
  if (await detectRisk(page)) throw new Error("RISK_VERIFICATION_REQUIRED");
  await uploadImages(page, request.images);
  await fillTitle(page, request.title);
  const editor = page.locator('[contenteditable="true"]').first();
  if (await editor.count()) await editor.fill(request.content);
  else await page.getByPlaceholder(/输入正文/).fill(request.content);
  await verifyTitlePreview(page, request.title);
  await setOriginalStatement(page, request.settings.original);
  await setSwitch(page, "允许合拍", request.settings.allowRemix);
  await setSwitch(page, "允许正文复制", request.settings.allowCopy);
  await chooseVisibility(page, request.settings.visibility);
  await setCollection(page, request.settings.collection);
  await setLocation(page, request.settings.location);
  await setSchedule(page, request.settings.scheduledAt);
  await assertImagesUploaded(page);
  const preview = await screenshot(page, "preview.png");
  const account = await page.locator('[class*="user" i], [class*="account" i]').first().innerText().catch(() => "请从预览截图核对账号");
  const token = confirmationToken(readJson(join(RUN_DIR, "state.json")).runId, request);
  writeJson(join(RUN_DIR, "summary.json"), publicSummary(request));
  updateState(RUN_DIR, {
    status: "awaiting_confirmation",
    confirmationToken: token,
    confirmationPhrase: `确认发布 ${token}`,
    preview,
    account: account.trim(),
    expiresAt: new Date(Date.now() + 15 * 60_000).toISOString(),
  });
  const deadline = Date.now() + 15 * 60_000;
  const controlPath = join(RUN_DIR, "control.json");
  while (Date.now() < deadline && !existsSync(controlPath)) {
    await assertImagesUploaded(page);
    await sleep(500);
  }
  if (!existsSync(controlPath)) {
    const saved = await clickDraft(page);
    updateState(RUN_DIR, { status: "confirmation_expired", draftSaved: saved });
    return;
  }
  const control = readJson(controlPath);
  rmSync(controlPath, { force: true });
  if (control.action !== "publish" || control.token !== token) throw new Error("确认令牌无效");
  await assertImagesUploaded(page);
  updateState(RUN_DIR, { status: "publishing", publishClicked: false });
  const responsePromise = page.waitForResponse(isPublishResponse, { timeout: 45_000 }).catch(() => null);
  await clickFooterButton(page, "publish", request.settings.scheduledAt ? "定时发布" : "发布");
  updateState(RUN_DIR, { publishClicked: true });
  const result = await publishResponseResult(await responsePromise);
  const managerResult = result.confirmed
    ? { confirmed: false }
    : await verifyPublishedInNoteManager(page.context(), request.title);
  if (result.confirmed || managerResult.confirmed) {
    await page.waitForTimeout(1500);
    updateState(RUN_DIR, {
      status: "published",
      verification: result.confirmed ? "publish_response" : "note_manager",
      successScreenshot: managerResult.screenshot || await screenshot(page, "published.png"),
    });
  } else {
    updateState(RUN_DIR, {
      status: "publish_unknown",
      error: result.error,
      noteManagerScreenshot: managerResult.screenshot,
      errorScreenshot: await screenshot(page, "publish-unknown.png"),
    });
  }
}

let browser;
let page;
let publishClicked = false;
try {
  browser = await launch({ headless: true, locale: "zh-CN", timezone: "Asia/Shanghai" });
  const context = await browser.newContext({
    ...(process.argv[2] === "prepare" ? { storageState: AUTH_FILE } : {}),
    viewport: process.argv[2] === "login"
      ? { width: 1440, height: 1000 }
      : { width: 1920, height: 1080 },
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
  });
  page = await context.newPage();
  if (process.argv[2] === "login") await runLogin(context, page);
  else {
    await prepare(page);
    publishClicked = readJson(join(RUN_DIR, "state.json")).publishClicked === true;
  }
  await context.close();
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  const risk = message === "RISK_VERIFICATION_REQUIRED";
  let errorScreenshot;
  if (page) {
    errorScreenshot = await screenshot(page, risk ? "risk-verification.png" : "error.png").catch(() => undefined);
    const text = redact(await bodyText(page));
    writeFileSync(join(RUN_DIR, "page-text.txt"), text.slice(0, 100_000), { mode: 0o600 });
  }
  if (process.argv[2] === "prepare") {
    try { publishClicked = readJson(join(RUN_DIR, "state.json")).publishClicked === true; } catch {}
  }
  if (process.argv[2] === "prepare" && page && !risk && !publishClicked) {
    const draftSaved = await clickDraft(page).catch(() => false);
    updateState(RUN_DIR, { draftSaved });
  }
  updateState(RUN_DIR, { status: risk ? "risk_verification_required" : (publishClicked ? "publish_unknown" : "failed"), error: message, errorScreenshot });
  process.exitCode = 1;
} finally {
  await browser?.close();
}
