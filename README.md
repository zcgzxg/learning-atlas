# 学习图谱 · Learning Atlas

对话里值得留下的知识，按主题长成一棵树。

- 站点：<https://zcgzxg.github.io/learning-atlas/>
- 知识源文件：`knowledge/`（Markdown，唯一的编辑入口）
- 展示层：Astro + Starlight + Pagefind，深色主题、目录树、全文搜索
- 部署：GitHub Actions → GitHub Pages

## 用 `/learn` 自动积累知识

在 OpenCode 中开启学习模式后，AI 会先正常回答，再把本轮值得长期保留的结论整理进知识库：

```text
/learn 了解大模型的 logits 是什么
/learn status
/learn publish
/learn stop
```

模式按会话保存；`/learn status` 查看仓库与待推送状态，`/learn publish` 立即提交并推送尚未入库的笔记。

### 安装

```bash
bash integrations/opencode/install.sh
```

脚本会做三件事：

1. 把 `learn` skill 安装到 `~/.config/opencode/skills/learn`
2. 把 `learn-atlas` 插件安装到 `~/.config/opencode/plugins/learn-atlas.ts`
3. 写入 `~/.config/opencode/learn-atlas.json`，指向当前仓库

安装后在 OpenCode 中执行 `/reload`（或重启 OpenCode）。依赖：Git、Python 3、已登录的 `gh`（仅首次建仓需要）。

工作方式：插件为当前会话注入学习模式提示；每轮回答结束后，AI 调用 skill 里的 `learn.py`，先搜索已有页面，能合并就合并，不能合并才新建目录与页面，然后自动提交并推送。GitHub Actions 随即重建站点。

## 目录结构

```text
knowledge/                  # 知识源：一个主题一个页面
  _labels.json              # 目录中文名
  ai/llm/logits.md
site/                       # Astro + Starlight 站点
scripts/                    # 校验、同步内容、生成侧边栏
integrations/opencode/      # /learn 的 skill、插件、安装脚本
.github/workflows/          # 校验与 Pages 部署
```

`site/src/content/docs/` 和 `site/src/generated/sidebar.json` 由 `scripts/sync-content.mjs` 生成，已加入 `.gitignore`。

## 本地开发

```bash
cd site
npm install
npm run dev        # http://localhost:4321/learning-atlas/
```

其他命令：

```bash
node scripts/validate-knowledge.mjs   # 校验所有笔记
cd site && npm run build              # 生产构建
cd site && npm run preview            # 预览构建结果
```

## 手动添加或修改笔记

在 `knowledge/` 下按主题建目录，新建 Markdown 文件。路径必须是小写 kebab-case，例如 `frontend/ui/design-tokens.md`：

```markdown
---
title: "Design Tokens：设计决策的单一来源"
description: "颜色、间距、字体等基础样式变量的组织方式"
tags: ["ui", "design-system"]
updated: "2026-11-18"
---

## 要点

- 一句话一个结论，3–5 条即可。
- 保留英文术语，解释用中文。
```

目录显示名写在 `knowledge/_labels.json`：

```json
{
  "frontend": "前端",
  "frontend/ui": "UI"
}
```

未配置的目录会使用内置缩写表或目录名。改完后运行校验，再提交推送；Actions 会自动部署。

## 部署

仓库使用 GitHub Actions 发布 Pages，工作流见 `.github/workflows/pages.yml`。首次启用：

```bash
gh api -X POST repos/zcgzxg/learning-atlas/pages -f build_type=workflow
```

之后每次推送到 `main` 且 `knowledge/`、`site/` 或 `scripts/` 有变化，都会自动构建并发布。GitHub Pages 站点是公开的，不要把密钥、内部地址或私人信息写进笔记。

## 设计原则

- **一个主题一个页面**，不是一次对话一个页面；新知识优先合并进已有页面。
- **只写沉淀下来的结论**，不写寒暄、追问、临时排错过程和不确定的猜测。
- **准确优先于数量**，每页 3–5 条高密度要点。
- **知识库是纯文本**，可被 Git 管理、审阅、迁移，不绑定任何模型厂家。
