---
title: "Android 原生渲染：Vulkan/wgpu 每帧不经过 Java"
description: "Android 上 Rust 与 wgpu 直接把 Vulkan 渲染到 ANativeWindow，帧节奏用 NDK AChoreographer，Java 只负责控制面。"
tags: ["android", "vulkan", "wgpu", "rendering"]
updated: "2026-11-28"
---

## 概述

Android 上 Rust 与 wgpu 直接把 Vulkan 渲染到 ANativeWindow，帧节奏用 NDK AChoreographer，Java 只负责控制面。

## 核心机制

- NativeActivity 在 APP_CMD_INIT_WINDOW 时把 ANativeWindow* 交给 native 层；wgpu 用 RawWindowHandle::AndroidNdk 基于该指针创建一次 Vulkan surface，之后每帧只是 get_current_texture/present，操作同一个 BufferQueue。
- 帧节奏由 NDK 的 AChoreographer_getInstance/AChoreographer_postFrameCallback 驱动，并用 ALooper_wake 唤醒渲染线程；这不是 Java 的 android.view.Choreographer，所以 vsync 也不需要 JNI。
- 触摸和按键通过 AInputQueue 进入 native 循环；SurfaceFlinger 负责把应用 Surface 与其它窗口合成，Java 的 SurfaceView 只是容器，不参与像素生产。

## 要点

- Java 只在控制面出现：生命周期、软键盘/IME、权限、深链、媒体会话、文件选择等；绘制热路径没有 JNI 调用。
- 平台 View（WebView、视频 SurfaceView）是独立的 Android View 或窗口，由框架直接合成；native 侧只在创建、改 bounds、显隐时通知 Java，不是每帧。
- Vulkan 同一个 ANativeWindow 只能绑定一个 surface；SurfaceView 重建后可能复用同一指针，重建 surface 前必须先释放旧 surface，否则报 ERROR_NATIVE_WINDOW_IN_USE_KHR。
- Mailbox 这类丢弃旧帧的 present mode 适合低延迟 UI，但 swapchain 不会替上层限帧，仍需按需请求帧并用 vsync 节流。
