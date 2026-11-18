---
title: "Logits：模型的未归一化分数"
description: "大模型输出层为词表候选 token 给出的原始分数"
tags: ["llm", "inference", "softmax"]
updated: "2026-11-18"
---

## 要点

- 大模型做下一 token 预测时，会为词表中的每个候选 token 输出一个实数分数，即 logit；它不是概率，可以为负。
- 对同一组 logits 应用 softmax，可得到总和为 1 的概率分布；logit 越高，对应 token 的概率越大。
- 温度采样通常在 softmax 前把 logits 除以正温度 `T`：`T < 1` 使分布更尖锐，`T > 1` 使分布更平坦。
- 温度缩放不改变 logits 的排序，但会改变各候选被抽中的概率；`T → 0` 近似贪心，`T → ∞` 近似均匀。
- logits 的差值决定 softmax 后的集中程度：差值越大，概率越集中在少数候选上。
