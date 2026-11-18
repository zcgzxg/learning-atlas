---
title: "响应预填充：把助手开头写进输入"
description: "在对话历史中预置 assistant 回复的开头，让模型从该前缀继续生成"
tags: ["llm", "inference", "prompt"]
updated: "2026-11-18"
---

## 概述

在对话历史中预置 assistant 回复的开头，让模型从该前缀继续生成

## 要点

- 响应预填充（assistant prefill）是把助手本轮回复的开头若干 token 以 assistant 消息形式放进输入，模型从该前缀之后继续自回归生成；它改变的是采样起点，不是向模型下达指令。
- 机制上 chat template 先把消息渲染成一条 token 序列，预填内容位于 assistant 段末尾，随输入一起完成 prefill 前向并写入 KV Cache，随后从下一个位置采样。
- 典型用途：强迫输出格式（预填 `{`、```json）、跳过“好的，我来帮你”这类客套、锁定语言或角色、续写已有文本。
- 各家 API 行为不一致：预填内容是否回显、max_tokens 是否包含预填 token、是否允许以 assistant 消息结尾，都要按文档处理；部分推理/思考模式不支持预填充。
- 预填使每个请求的前缀不同，会降低 prompt caching 命中率；尾随空格与分词边界会显著改变效果，因为 `修改后：` 与带尾随空格的版本可能是不同的 token 序列。
