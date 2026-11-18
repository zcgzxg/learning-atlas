---
title: "约束解码：采样前屏蔽非法 token"
description: "按文法状态逐步屏蔽非法 token 的 logits，使输出在语法层面必然合法"
tags: ["llm", "inference", "structured-output"]
updated: "2026-11-18"
---

## 概述

按文法状态逐步屏蔽非法 token 的 logits，使输出在语法层面必然合法

## 要点

- 约束解码在每个解码步把会让输出违反目标文法（正则、CFG、JSON Schema）的 token 的 logit 置为 -inf，只在合法集合内采样；数学上是对模型分布做条件投影并重新归一化，提供的是硬保证而非概率性约束。
- 正则可编译为 DFA；JSON Schema 这类嵌套结构需要下推自动机（带栈），以跟踪嵌套深度、必填字段与是否允许收尾。
- 核心难点是 token 与字符不对齐：一个 token 可能跨多个语法步，必须校验 token 的完整字符串，因而会迫使模型改用非惯用分词，产生“语法税”，表现为重复或语法正确的废话。性能依赖状态→掩码缓存与静态/动态掩码拆分（如 XGrammar）来避免每步遍历整个词表。
- 它只保证语法合法，不保证语义正确，文法过窄时会逼出“格式完美、内容瞎编”；必须叠加业务校验，并设置 max_tokens 防止合法死循环。EOS 只能在解析器接受态才放开，约束应只包住最终答案块、让思考块豁免。
- 代表实现：llama.cpp 的 GBNF、Outlines、Guidance、XGrammar（vLLM/SGLang 常用）、OpenAI Structured Outputs 的 strict 模式；注意 JSON mode 只保证可解析，不保证符合给定 schema。
