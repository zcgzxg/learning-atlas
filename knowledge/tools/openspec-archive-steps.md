---
title: "OpenSpec archive 之后要做什么"
description: "openspec archive 只合并 delta 并移动 change 目录，不碰 Git 与部署；归档后仍需提交、校验、审查合并结果并同步引用。"
tags: ["openspec", "archive", "workflow", "git"]
updated: "2026-11-20"
---

## 概述

openspec archive 只合并 delta 并移动 change 目录，不碰 Git 与部署；归档后仍需提交、校验、审查合并结果并同步引用。

## 核心机制

- archive 做两件事：把 change 的 delta spec 按 ADDED/MODIFIED/REMOVED/RENAMED 合并进 openspec/specs/，并把整个 change 移入 changes/archive/<date>-<name>/；不会自动提交 Git。
- 归档前会校验 delta，非法 change 被拒绝；tasks 未完成只警告不阻塞，加 -y 会直接继续。
- 归档后用 openspec validate --specs 校验合并结果，openspec list 确认活动 change 清空，openspec validate --archived 只检查归档 change 的任务完成情况。

## 要点

- 必须提交：specs 合并结果与 archive 目录要和代码一起进版本库，否则下一次 change 的 diff 会混入上次未提交的 spec 变更。
- 要 review 合并 totals（+ ~ - →），确认 MODIFIED 覆盖位置正确、场景没丢；文档、ADR 和 CI 中引用 changes/<name> 的路径需改为 archive/<date>-<name>。
- archive 不等于发布：合并、部署、线上验证、feature flag 与临时脚本清理仍是独立步骤。
- 可选瘦身：先提交 archive，再删除 archive/<change>/specs/；不要先删后提交，否则 Git 里没有快照。
