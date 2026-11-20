---
title: "OpenSpec 的工件分工与 ADR 边界"
description: "OpenSpec 用 proposal、delta spec、design、tasks 描述一次变更，归档后只保留历史；跨变更长期有效的“为什么”需要 ADR 承接。"
tags: ["openspec", "spec-driven", "adr", "workflow"]
updated: "2026-11-20"
---

## 概述

OpenSpec 用 proposal、delta spec、design、tasks 描述一次变更，归档后只保留历史；跨变更长期有效的“为什么”需要 ADR 承接。

## 核心机制

- 一次变更包含 proposal.md（动机与范围）、specs/ delta（可测试需求）、可选的 design.md（技术方案与替代方案）、tasks.md（实施清单）；归档时 delta 合并进 openspec/specs/，整个 change 移入 changes/archive/<date>-<name>/。
- specs 只描述系统当前“必须做什么”，不承载理由；archive 保存每次变更的 design 与决策，属于历史记录，但不提供稳定的“当前有效决策”入口。
- design.md 的 Decisions 段记录本次变更内的技术选择及 alternatives；只有跨变更、难回退的系统级决策才升格为 ADR，并在 design.md 中反向链接。

## 要点

- OpenSpec 官方把 archive 视为 decision history，缺口是决策埋在有日期的变更目录里、检索前需先知道属于哪次变更；未走 change 流程的决策（热修、依赖升级）不会留下记录。
- 升格 ADR 的判定：影响多模块或长期架构、回退成本高、未来会被追问“为什么不用 X”，满足任意两条才写，避免每个 change 都产出 ADR。
- 最小落地：docs/adr/NNNN-slug.md，ADR 不可改并以 Superseded 状态演进；design.md 链接 ADR，ADR 反向链接 change 名；在 openspec/config.yaml 的 context 中加入规则让 Agent 主动提示升格。
- ADR 只写理由、不重复需求，spec 仍是行为的唯一真相；两者冲突时以 spec 为准，并新开 ADR 记录变更原因。
