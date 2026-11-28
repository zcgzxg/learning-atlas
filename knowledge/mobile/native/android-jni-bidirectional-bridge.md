---
title: "Android JNI 双向桥：Java 调 Rust 与 Rust 调 Java"
description: "Android 上 Rust 与 Java 互调的 JNI 机制：符号名解析、ClassLoader 查找、UI 线程与阻塞调用约束。"
tags: ["android", "jni", "rust", "threading"]
updated: "2026-11-28"
---

## 概述

Android 上 Rust 与 Java 互调的 JNI 机制：符号名解析、ClassLoader 查找、UI 线程与阻塞调用约束。

## 核心机制

- Java 调 Rust：Java 声明 static native 方法，Rust 侧导出 Java_<包>_<类>_<方法> 符号（包名点换下划线，类/方法名中的 _ 转义为 _1）。JVM 按名字解析，无需 JNI_OnLoad 或 RegisterNatives；静态方法的第二个参数是 jclass。
- NativeActivity 通过 dlopen 加载 .so 时不会把库关联到应用 ClassLoader，Java 侧仍须在 onCreate 里 System.loadLibrary(name)，native 方法才可解析；库名可从 manifest 的 android.app.lib_name 读取。
- Rust 调 Java：从 JavaVM attach 当前线程，先取 Activity 的 Context.getClassLoader().loadClass(name)，再用 call_static_method/call_method 加 JNI 签名调用。native 线程直接 FindClass 只能看到 boot classloader，找不到应用类。
- 线程契约：JNI 回调运行在 Java UI 线程，不能直接改渲染线程状态，应把事件入队并用原子量/唤醒机制交给渲染线程；必须跑在 UI 线程的 Android API 由 Java helper 内部 runOnUiThread/Handler 切换。

## 要点

- 会阻塞等待用户操作的 helper（文件选择、权限等）在 Java 侧用 CountDownLatch 阻塞调用线程；Rust 必须从后台线程调用，否则会卡住 UI 或渲染线程。
- JNI 方法名和签名是运行时字符串匹配，写错只会在调用时报 NoSuchMethodError；每次调用失败后要清除挂起异常，避免影响后续 JNI 调用。
- Activity 重建后旧 jobject 会失效；Rust 侧应持有全局引用并在每次 onCreate 更新，不能跨重建缓存。
