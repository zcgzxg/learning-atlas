// learn-atlas：会话级学习模式。
//
// /learn <主题> 开启后，在每次模型调用的 system 上下文里注入归档指令；
// 模型正常回答，回答结束后调用 learn skill 把结论合并进知识库。
// 模式按 session 保存在 OpenCode storage，重启/恢复会话后仍然有效。
import { execFile } from "node:child_process";
import { existsSync, readFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { Plugin } from "@opencode/plugin";

const HEADER = "【learn-atlas 学习模式】";
const CONFIG_HOME =
  process.env.XDG_CONFIG_HOME?.trim() || join(homedir(), ".config");
const CONFIG_PATH =
  process.env.LEARN_ATLAS_CONFIG?.trim() ||
  join(CONFIG_HOME, "opencode", "learn-atlas.json");
const SCRIPT_PATH = join(
  CONFIG_HOME,
  "opencode",
  "skills",
  "learn",
  "scripts",
  "learn.py",
);
const MODE_PREFIX = "mode/";

let configCache = { mtimeMs: -1, value: {} };

function readConfig() {
  try {
    const info = statSync(CONFIG_PATH);
    if (info.mtimeMs !== configCache.mtimeMs) {
      const parsed = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));
      configCache = {
        mtimeMs: info.mtimeMs,
        value: parsed && typeof parsed === "object" ? parsed : {},
      };
    }
    return configCache.value;
  } catch {
    return {};
  }
}

function repoPath() {
  const fromEnv = process.env.LEARN_ATLAS_REPO?.trim();
  if (fromEnv) return fromEnv;
  const fromConfig = readConfig().repo;
  return typeof fromConfig === "string" && fromConfig.trim()
    ? fromConfig.trim()
    : join(homedir(), "code", "github", "learning-atlas");
}

function modeKey(sessionID) {
  return MODE_PREFIX + sessionID;
}

async function getMode(ctx, sessionID) {
  if (!sessionID) return null;
  try {
    const value = await ctx.storage.get(modeKey(sessionID));
    if (!value || typeof value !== "object") return null;
    if (typeof value.topic !== "string" || !value.topic.trim()) return null;
    return value;
  } catch {
    return null;
  }
}

async function setMode(ctx, sessionID, mode) {
  await ctx.storage.set(modeKey(sessionID), mode);
}

async function clearMode(ctx, sessionID) {
  try {
    await ctx.storage.remove(modeKey(sessionID));
  } catch {
    // 删除失败不阻断退出提示
  }
}

function runLearn(args, timeout = 30_000) {
  return new Promise((resolve) => {
    execFile(
      "python3",
      [SCRIPT_PATH, ...args],
      {
        timeout,
        maxBuffer: 2 * 1024 * 1024,
        env: process.env,
      },
      (error, stdout, stderr) => {
        const out = String(stdout || "").trim();
        const err = String(stderr || "").trim();
        let data = null;
        let message = "";
        for (const candidate of [out, err]) {
          if (!candidate) continue;
          try {
            const parsed = JSON.parse(candidate);
            if (parsed && typeof parsed === "object") {
              data = parsed;
              break;
            }
          } catch {
            message = candidate;
          }
        }
        if (!data && error) {
          message =
            message ||
            (error.code === "ENOENT"
              ? "找不到 python3，请先安装 Python 3"
              : error.message);
        }
        resolve({ data, error: data?.error || message, raw: out || err });
      },
    );
  });
}

async function notify(ctx, sessionID, text) {
  try {
    await ctx.session.synthetic({ sessionID, text });
  } catch (error) {
    console.error(`[learn-atlas] 无法发送提示：${error}`);
  }
}

function helpText() {
  const repo = repoPath();
  const repoReady = existsSync(join(repo, "knowledge"));
  return [
    "**learn-atlas 学习模式**",
    "",
    "```text",
    "/learn            回顾当前会话，补录值得保留的知识",
    "/learn <主题>     开启学习模式并提问",
    "/learn status     查看待发布内容与仓库状态",
    "/learn publish    立即提交并推送笔记",
    "/learn stop       退出学习模式",
    "```",
    "",
    `知识库：\`${repo}\`${repoReady ? "" : "（尚未找到 knowledge/ 目录）"}`,
    "开启后，AI 会正常回答，并在每轮结束时把可复用的结论合并进知识库。",
  ].join("\n");
}

function scanPrompt() {
  return [
    "【learn-atlas 历史归档扫描】",
    "这不是一个新的知识问题，不要重新回答历史问题，也不要输出归档清单。",
    "请回顾当前会话中已经讨论过的内容，找出值得长期保留、且尚未写入知识库的知识。",
    "按主题拆分：先用 learn skill 的 learn.py search 查重，再对每个不同主题分别调用 add 合并或新建页面，最多处理 5 个主题。",
    "只记录准确、可复用、非敏感的内容；寒暄、追问、临时排错和不确定的猜测跳过。",
    "如果没有任何值得新增的内容，只回复一句“当前会话没有需要新增的知识。”",
  ].join("\n");
}

function formatStatus(mode, result) {
  const lines = [];
  if (mode) {
    lines.push(`**学习模式：已开启**`);
    lines.push(`主题：${mode.topic}`);
    if (mode.startedAt) lines.push(`开始：${mode.startedAt}`);
  } else {
    lines.push("**学习模式：未开启**");
  }

  const data = result.data;
  if (data?.ok) {
    lines.push("");
    lines.push(`仓库：\`${data.repo}\``);
    lines.push(`分支：\`${data.branch}\`${data.upstream ? ` → \`${data.upstream}\`` : ""}`);
    lines.push(
      `未推送提交：${data.unpushed === null ? "未知（无 upstream）" : data.unpushed}`,
    );
    lines.push(`未提交改动：${Array.isArray(data.dirty) ? data.dirty.length : 0}`);

    const pending = Array.isArray(data.pending) ? data.pending : [];
    const publishFiles = Array.isArray(data.publishFiles)
      ? data.publishFiles
      : pending;
    const commits = Array.isArray(data.unpushedCommits)
      ? data.unpushedCommits
      : [];
    lines.push("");
    lines.push("**待发布内容**");
    if (!publishFiles.length && !commits.length) {
      lines.push("没有待发布内容。");
    } else {
      if (publishFiles.length) {
        lines.push(`待发布文件（${publishFiles.length}）：`);
        for (const item of publishFiles.slice(0, 8)) {
          const title = item.title ? ` ${item.title}` : "";
          const state = item.uncommitted === false ? "待推送" : "未提交";
          lines.push(
            `- \`${item.path}\`（${item.statusLabel || item.status} · ${state}）${title}`,
          );
          for (const line of (item.added || []).slice(0, 6)) {
            lines.push(`  + ${line}`);
          }
          for (const line of (item.removed || []).slice(0, 6)) {
            lines.push(`  - ${line}`);
          }
          if (item.truncated) lines.push("  …");
        }
        if (publishFiles.length > 8) {
          lines.push(`- …还有 ${publishFiles.length - 8} 个文件`);
        }
      }
      if (commits.length) {
        lines.push(`未推送提交（${commits.length}）：`);
        for (const commit of commits.slice(0, 5)) {
          lines.push(`- \`${commit.hash}\` ${commit.subject}`);
          if (Array.isArray(commit.files) && commit.files.length) {
            const files = commit.files.slice(0, 4).join("、");
            const suffix =
              commit.filesTruncated || commit.files.length > 4 ? " …" : "";
            lines.push(`  ${files}${suffix}`);
          }
        }
        if (commits.length > 5) {
          lines.push(`- …还有 ${commits.length - 5} 个提交`);
        }
      }
      lines.push("");
      lines.push("审核/补充后执行 `/learn publish` 发布。");
    }

    if (Array.isArray(data.recent) && data.recent.length) {
      lines.push("");
      lines.push("最近提交：");
      for (const item of data.recent.slice(0, 3)) lines.push(`- ${item}`);
    }
  } else {
    lines.push("");
    lines.push(`无法读取仓库状态：${result.error || "未知错误"}`);
  }

  if (!mode) {
    lines.push("");
    lines.push("使用 `/learn` 回顾当前会话，或 `/learn <主题>` 开始。");
  }
  return lines.join("\n");
}

function formatPublish(result) {
  if (!result.data?.ok) {
    return `归档失败：${result.error || "未知错误"}`;
  }
  const data = result.data;
  if (data.pushError) {
    return `已提交${data.commit ? ` \`${data.commit}\`` : ""}，但推送失败：${data.pushError}\n稍后可执行 \`/learn publish\` 重试。`;
  }
  if (data.changed) {
    return `已提交${data.commit ? ` \`${data.commit}\`` : ""}并推送到 GitHub。`;
  }
  if (data.pushed) {
    return "已推送待发布的提交，仓库已是最新。";
  }
  return "没有待发布内容，仓库已是最新。";
}

function instructions(mode) {
  return [
    HEADER,
    `当前会话已开启学习模式。主题：${mode.topic}`,
    `知识库：${repoPath()}`,
    "要求：",
    "1. 先正常、完整地回答用户，不要因为要归档而压缩答案。",
    "2. 回答结束后，判断本轮是否产生了值得长期保留的新知识。若有，调用 learn skill，用其中的 learn.py 合并 3–5 条要点；优先复用已有页面，只有确实是新主题才新建目录。",
    "3. 只记录准确、可复用、非敏感的内容；不确定、时效性强、私人或内部信息不记录；寒暄、追问、临时排错不记录。",
    "4. 普通用户回合最多写入一次；如果收到【learn-atlas 历史归档扫描】指令，则按主题分别写入，最多 5 个页面。",
    "5. 历史归档扫描不是新的提问：不要重新回答历史问题，只把已有结论补录进知识库。",
    "6. 默认不要向用户解释归档过程；只有写入失败或用户询问时才说明。",
    "7. 学习模式持续到用户执行 /learn stop。",
  ].join("\n");
}

function inject(system, mode) {
  if (!mode) return;
  if (
    system.some(
      (part) => part.type === "text" && part.text.includes(HEADER),
    )
  ) {
    return;
  }
  system.push({ type: "text", text: instructions(mode) });
}

export default Plugin.define({
  id: "learn-atlas",
  async setup(ctx) {
    await ctx.command.transform((editor) => {
      editor.add({
        name: "learn",
        description:
          "学习模式：/learn 回顾当前会话，/learn <主题> 正常回答并自动沉淀知识",
        execute: async ({ sessionID, prompt, delivery }) => {
          const raw = String(prompt?.text || "").trim();
          const arg = raw.replace(/^\/learn\b/i, "").trim();
          const lower = arg.toLowerCase();

          if (!arg) {
            const existing = await getMode(ctx, sessionID);
            const mode = existing ?? {
              topic: "当前会话",
              startedAt: new Date().toISOString(),
            };
            try {
              if (!existing) await setMode(ctx, sessionID, mode);
              await ctx.session.prompt({
                ...prompt,
                sessionID,
                text: scanPrompt(),
                delivery,
              });
            } catch (error) {
              if (!existing) await clearMode(ctx, sessionID);
              await notify(
                ctx,
                sessionID,
                `无法回顾当前会话：${error instanceof Error ? error.message : error}`,
              );
            }
            return;
          }

          if (["stop", "exit", "quit", "停止", "退出", "结束"].includes(lower)) {
            const mode = await getMode(ctx, sessionID);
            await clearMode(ctx, sessionID);
            await notify(
              ctx,
              sessionID,
              mode
                ? `已退出学习模式（主题：${mode.topic}）。之后不再自动归档。`
                : "当前没有开启学习模式。",
            );
            return;
          }

          if (lower === "status" || arg === "状态") {
            const mode = await getMode(ctx, sessionID);
            const result = await runLearn(["status"], 20_000);
            await notify(ctx, sessionID, formatStatus(mode, result));
            return;
          }

          if (lower === "publish" || arg === "发布") {
            const result = await runLearn(["publish"], 120_000);
            await notify(ctx, sessionID, formatPublish(result));
            return;
          }

          if (lower === "help" || arg === "帮助") {
            await notify(ctx, sessionID, helpText());
            return;
          }

          const mode = {
            topic: arg,
            startedAt: new Date().toISOString(),
          };
          await setMode(ctx, sessionID, mode);
          try {
            await ctx.session.prompt({
              ...prompt,
              sessionID,
              text: arg,
              delivery,
            });
          } catch (error) {
            await clearMode(ctx, sessionID);
            await notify(
              ctx,
              sessionID,
              `无法进入学习模式：${error instanceof Error ? error.message : error}`,
            );
          }
        },
      });
    });

    await ctx.session.hook("context", async (event) => {
      const mode = await getMode(ctx, event.sessionID);
      inject(event.system, mode);
    });

    await ctx.session.hook("compaction", async (event) => {
      const mode = await getMode(ctx, event.sessionID);
      inject(event.system, mode);
    });
  },
});
