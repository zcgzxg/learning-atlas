---
title: "Logits：模型的未归一化分数"
description: "大模型输出层为词表候选 token 生成的未归一化分数，经 softmax 变成采样概率"
tags: ["llm", "inference", "softmax"]
updated: "2026-11-19"
---

## 概述

大模型做下一 token 预测时，输出层会为词表中的每个候选 token 生成一个实数分数（logit）；logit 经 softmax 转成概率分布，再用于采样或解码。

## 核心机制

- logits 由最后一层 hidden state 经 LM Head（unembedding 矩阵，d_model × |V|）线性投影得到；许多模型让该矩阵与词嵌入矩阵共享权重。
- softmax 对每个 logit 取指数再除以总和，得到和为 1 的概率分布；logit 越高，对应 token 的概率越大。
- softmax 对整体平移不变（softmax(z+c)=softmax(z)），所以只有 logit 之间的差值有意义，绝对数值无意义。
- 温度采样在 softmax 前把 logits 除以正温度 `T`：`T < 1` 放大差异、分布更尖锐；`T > 1` 压缩差异、分布更平坦。
- 两个候选的 logit 差等于概率对数比：`z_A − z_B = log(p_A/p_B)`；差 2.3 约对应 10 倍概率，4.6 约对应 100 倍。
- 约束解码在 logit 层做掩码：非法 token 置为 `-inf`，工程上常用 `-1e9` 代替以避免 NaN；不能置 0，因为 `e^0 = 1` 仍会保留概率份额。

## 要点

- logit 是未归一化分数，可为负，本身不是概率。
- logits 的排序决定候选顺序，但采样概率由 softmax 后的分布决定；`T → 0` 近似贪心，`T → ∞` 近似均匀采样。
- logits 的差值决定分布集中度：差值越大，概率越集中在少数候选上。
- 常见坑：HuggingFace `output_scores=True` 返回的是经过 logits processor/warper 处理后的分数，而非原始 logits；LM Head 常升到 fp32 计算；生成时只取最后位置 `logits[:, -1, :]`；多数 API 只暴露 logprobs 而不暴露 logits。
