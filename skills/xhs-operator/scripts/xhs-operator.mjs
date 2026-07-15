#!/usr/bin/env node
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  AUTH_FILE, HOME_DIR, RUNS_DIR, cleanupRuns, ensureHome, newRunId, readJson,
  updateState, validateRequest, writeJson,
} from "./lib.mjs";

const worker = resolve(fileURLToPath(new URL("./worker.mjs", import.meta.url)));

function value(name) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

function usage() {
  console.log(`xhs-operator commands:
  check
  login --mode qr|sms [--phone 13800138000]
  sms-code --run <run-id> --code <code>
  prepare --request /absolute/request.json
  confirm --run <run-id> --token <token>
  status [--run <run-id>]
  records
  cleanup [--all --confirm]
  logout --confirm
  _worker ...`);
}

function startWorker(args, runDir) {
  const log = join(runDir, "worker.log");
  const output = writeFileSync(log, "", { mode: 0o600 });
  void output;
  const child = spawn(process.execPath, [worker, ...args], {
    detached: true,
    stdio: ["ignore", "ignore", "ignore"],
    env: { ...process.env, XHS_RUN_DIR: runDir },
  });
  child.unref();
  return child.pid;
}

ensureHome();
const removed = cleanupRuns();
const command = process.argv[2];

try {
  if (command === "check") {
    const nodeMajor = Number(process.versions.node.split(".")[0]);
    if (nodeMajor < 20) throw new Error(`需要 Node.js 20 或更高版本，当前为 ${process.version}`);
    try { await import("cloakbrowser"); } catch {
      throw new Error("缺少必需依赖 cloakbrowser，或当前 Node.js 环境无法解析它。请先按照 https://cloakbrowser.dev 的官方说明安装");
    }
    console.log(JSON.stringify({ ok: true, node: process.version, home: HOME_DIR, expiredRunsRemoved: removed.length }, null, 2));
  } else if (command === "login") {
    const mode = value("mode") || "qr";
    if (!['qr', 'sms'].includes(mode)) throw new Error("mode 必须是 qr 或 sms");
    const phone = value("phone");
    if (mode === "sms" && !/^1\d{10}$/.test(phone || "")) throw new Error("短信登录需要 --phone 11位手机号");
    const runId = newRunId("login");
    const runDir = join(RUNS_DIR, runId);
    mkdirSync(runDir, { recursive: true, mode: 0o700 });
    updateState(runDir, { runId, kind: "login", mode, status: "starting", createdAt: new Date().toISOString() });
    const pid = startWorker(["login", "--mode", mode, ...(phone ? ["--phone", phone] : [])], runDir);
    updateState(runDir, { pid });
    console.log(JSON.stringify({ runId, statusFile: join(runDir, "state.json") }, null, 2));
  } else if (command === "sms-code") {
    const runId = value("run");
    const code = value("code");
    if (!runId || !/^\d{4,8}$/.test(code || "")) throw new Error("需要 --run 和 4到8位 --code");
    const runDir = join(RUNS_DIR, runId);
    const state = readJson(join(runDir, "state.json"));
    if (state.status !== "waiting_for_code") throw new Error(`当前状态不能提交验证码: ${state.status}`);
    writeFileSync(join(runDir, "sms-code.txt"), code, { mode: 0o600 });
    console.log(JSON.stringify({ accepted: true, runId }));
  } else if (command === "prepare") {
    const requestPath = value("request");
    if (!requestPath) throw new Error("需要 --request JSON 文件");
    const request = validateRequest(readJson(resolve(requestPath)));
    if (!existsSync(AUTH_FILE)) throw new Error("尚未登录；请先运行 login");
    const runId = newRunId("publish");
    const runDir = join(RUNS_DIR, runId);
    mkdirSync(runDir, { recursive: true, mode: 0o700 });
    writeJson(join(runDir, "request.json"), request);
    updateState(runDir, { runId, kind: "publish", status: "starting", createdAt: new Date().toISOString() });
    const pid = startWorker(["prepare"], runDir);
    updateState(runDir, { pid });
    console.log(JSON.stringify({ runId, statusFile: join(runDir, "state.json") }, null, 2));
  } else if (command === "confirm") {
    const runId = value("run");
    const token = value("token")?.toUpperCase();
    if (!runId || !token) throw new Error("需要 --run 和 --token");
    const runDir = join(RUNS_DIR, runId);
    const state = readJson(join(runDir, "state.json"));
    if (state.status !== "awaiting_confirmation") throw new Error(`当前状态不能发布: ${state.status}`);
    if (state.confirmationToken !== token) throw new Error("确认令牌不匹配或已失效");
    writeJson(join(runDir, "control.json"), { action: "publish", token, createdAt: new Date().toISOString() });
    console.log(JSON.stringify({ accepted: true, runId }));
  } else if (command === "status") {
    const runId = value("run");
    if (runId) console.log(JSON.stringify(readJson(join(RUNS_DIR, runId, "state.json")), null, 2));
    else {
      const entries = readdirSync(RUNS_DIR).sort().reverse();
      console.log(JSON.stringify(entries[0] ? readJson(join(RUNS_DIR, entries[0], "state.json")) : { status: "no_runs" }, null, 2));
    }
  } else if (command === "records") {
    const records = readdirSync(RUNS_DIR).sort().reverse().map((runId) => {
      try { return readJson(join(RUNS_DIR, runId, "state.json")); } catch { return { runId, status: "unreadable" }; }
    });
    console.log(JSON.stringify(records, null, 2));
  } else if (command === "cleanup") {
    if (process.argv.includes("--all")) {
      if (!process.argv.includes("--confirm")) throw new Error("清理全部记录需要 --confirm");
      for (const entry of readdirSync(RUNS_DIR)) rmSync(join(RUNS_DIR, entry), { recursive: true, force: true });
      console.log(JSON.stringify({ allRunsRemoved: true }));
    } else console.log(JSON.stringify({ removed }, null, 2));
  } else if (command === "logout") {
    if (!process.argv.includes("--confirm")) throw new Error("退出登录需要 --confirm");
    rmSync(AUTH_FILE, { force: true });
    console.log(JSON.stringify({ loggedOut: true }));
  } else {
    usage();
    process.exitCode = command ? 1 : 0;
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}
