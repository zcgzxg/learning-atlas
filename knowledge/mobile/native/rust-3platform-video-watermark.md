---
title: "Rust 三端视频水印模块：架构、工具链与依赖清单"
description: "用 Rust 统一 Android/iOS/鸿蒙的视频水印能力：Rust 持有解封装、YUV 合成、封装与进度流水线，编解码按其 trait 分派到三端硬件实现，三端各留一层薄桥。"
tags: ["rust", "harmonyos", "android", "ios", "cross-compile"]
updated: "2026-11-23"
---

## 概述

用 Rust 统一 Android/iOS/鸿蒙的视频水印能力：Rust 持有解封装、YUV 合成、封装与进度流水线，编解码按其 trait 分派到三端硬件实现，三端各留一层薄桥。

## 核心机制

- 整体数据流是 mp4 → demux 出 H.264 与 AAC → 平台硬解得到 NV12 → 只在水印矩形内做 YUV 混合 → 平台硬编 → 重新 mux 成 mp4；音频样本直通复制，只有非 AAC 音轨才需要解码重编。
- Rust 独占的是无平台依赖的流水线：mp4 解封装/封装、PNG 解码与缩放、NV12 合成、进度与取消、错误码；编解码抽象成 trait VideoCodec，按 cfg(target_os) 分派到 AMediaCodec / VideoToolbox / OH_AVCodec 三个实现。
- 三端只留薄桥：Android 用 jni crate + Kotlin TurboModule，iOS 用 ObjC++ TurboModule 直调 C ABI（cbindgen 生成头文件），鸿蒙用 napi-ohos + ArkTS TurboModule；RNOH 没有 TurboModule C ABI，所以鸿蒙不走 C++ 桥。
- 进度用 Arc<AtomicBool> 每帧检查取消标志、crossbeam-channel 上报进度；取消必须调用 backend 的 stop/flush/destroy，否则编解码器回调线程会泄漏。

## 要点

- 纯 Rust 编解码不成立：没有生产级 H.264 编码器（rav1e 是 AV1 且移动端过慢，openh264/x264/kvazaar 都是 C），手机软编 1080p 只有 5–15 fps，硬编快 10–50 倍；FFmpeg 每 ABI 每端再加 8–15 MB。
- 许可证与专利是硬约束：x264、fdk-aac 是 GPL 会传染，openh264 的免专利只覆盖 Cisco 分发的二进制，自编译仍需付 H.264 专利费；core 只能用 MIT/Apache/BSD，用 cargo-deny 卡住。
- 鸿蒙 target 是 Rust Tier 2 with host tools（aarch64/armv7/x86_64-unknown-linux-ohos），loongarch64 是 Tier 3；手写链接器需 --target=<arch>-linux-ohos、--sysroot=<sdk>/native/sysroot、-D__MUSL__，用 ohrs 可省掉。
- Android 16KB 页对齐由链接器参数决定：NDK r28+ 默认 2**14，r27 及以下必须显式加 -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384；Google Play 从 2027-02-01 起要求 targetSdk 35+ 的更新支持 16KB。
- ohos-rs 要求 Rust ≥1.88、OHOS_NDK_HOME、Node 20（Node 24 会崩）；crate 为 napi-ohos + napi-derive-ohos，build.rs 调 napi_build_ohos::setup()，产物是 .so + index.d.ts。
