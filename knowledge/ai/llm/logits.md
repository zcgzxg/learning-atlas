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
- logits 由最后一层 hidden state 经 LM Head（unembedding 矩阵，d_model × |V|）线性投影得到，该矩阵常与词嵌入矩阵共享。
- softmax 对 logits 整体平移不变（softmax(z+c)=softmax(z)），所以只有 logit 之间的差值有意义，绝对数值无意义。
- 两个候选的 logit 差等于其概率的对数比：z_A − z_B = log(p_A/p_B)，差 2.3 约对应 10 倍概率、4.6 约对应 100 倍。
- 约束解码的掩码在 logit 层实现：非法 token 置为 -inf 而非 0（logit 为 0 意味着概率份额 e^0=1），工程上常用 -1e9 代替 -inf 以避免 NaN。
- 常见坑：HuggingFace 的 output_scores=True 返回的是经过 logits processor/warper 处理后的分数而非原始 logits；LM Head 常升到 fp32 计算；生成时只取最后位置 logits[:, -1, :]；多数 API 只暴露 logprobs 而不暴露 logits。
