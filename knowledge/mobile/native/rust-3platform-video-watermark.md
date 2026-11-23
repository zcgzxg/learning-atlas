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

## 为什么不能用纯 Rust 编解码

- **没有生产级 H.264 编码器**：`rav1e` 是 AV1 且移动端太慢；`openh264`、`x264`、`kvazaar` 都是 C。HEVC 解码同样只有 C 实现（libde265 / FFmpeg）。
- **性能差一个数量级**：手机软编 1080p H.264 约 5–15 fps，4K 不可用；硬编快 10–50 倍，且不占 CPU。
- **包体代价**：FFmpeg 每个 ABI 每端增加 8–15 MB。参考鸿蒙 HAP 已 107 MB，其中 `libavcodec.so.58` 单 ABI 就有 12.5–14.7 MB。
- **专利与许可证**：`openh264` 的免专利只覆盖 Cisco 分发的二进制，自行编译仍要向 H.264 专利池付费，HEVC 更贵；`x264`、`fdk-aac` 是 GPL，会传染整个 App。
- **结论**：编解码走平台 API，Rust 只做「编排 + 像素处理 + 容器处理」。

## 分层架构

```text
RN 层 (TS spec + codegen)
  └─ 三端薄壳：Kotlin TM / ObjC++ TM / ArkTS TM
       └─ 桥：vw-jni (cdylib) / vw-capi (staticlib) / vw-napi (cdylib)
            └─ vw-core（纯 Rust，无平台依赖，可在 Linux 单测）
                 └─ vw-codec：trait VideoCodec + cfg(target_os) 三端实现
```

Rust 代码占比约 60–70%；每个平台 backend 300–600 行，每个桥 100–200 行；UI 完全由 RN 负责，Rust 不碰。

## 功能 → 技术映射

| 功能 | 归属 | 技术 / 关键 API |
|---|---|---|
| MP4 解封装 | core | `mp4 = 0.14`：`Mp4Reader::read_header`、`Mp4Track`、`Mp4Sample`；需手工提取 avcC/hvcC 里的 SPS/PPS/VPS、stss、ctts、tkhd 旋转、edts、colr |
| MP4 封装 | core | `Mp4Writer::write_start(TrackConfig, MediaConfig)` → `write_sample` → `write_end`；faststart（moov 前置）需自己实现；注意 DTS/PTS 单调 |
| 音频直通 | core | 复制 AAC 样本 + `esds`/AudioSpecificConfig，不解码；非 AAC 才用 `symphonia` 解析 + C 编码器 |
| PNG 解码 | core | `image = 0.25`（`ImageReader::open().decode().to_rgba8()`）；处理 16-bit、ICC、预乘 alpha |
| 水印缩放 | core | `fast_image_resize = 5` |
| NV12 合成 | core | `yuvutils-rs = 0.8`（0.8.3，BSD-3-Clause OR Apache-2.0，MSRV 1.82）：`YuvBiPlanarImageMut`、`bgra_to_yuv_nv12`；只混合水印矩形；UV 按 2×2 块；`wide = 0.7` 做 SIMD；色彩矩阵取自 `colr` box |
| 进度 / 取消 | core | `Arc<AtomicBool>` 每帧检查 + `crossbeam-channel`；不用 tokio（编解码回调线程模型不匹配）；取消必须调用 backend 的 stop/flush/destroy |
| 错误码 | core | `thiserror` 枚举 Demux/Decode/Encode/Mux/Io/Cancelled/Unsupported；`tracing` 自定义 layer 输出到 logcat / oslog / hilog |
| Android 编解码 | backend | NDK C API：`AMediaCodec_createDecoderByType` / `createEncoderByType`、`KEY_COLOR_FORMAT = COLOR_FormatYUV420Flexible`、`dequeueInputBuffer` / `queueInputBuffer` / `dequeueOutputBuffer`，读 `KEY_STRIDE`、`KEY_SLICE_HEIGHT`；链接 `-lmediandk -llog -landroid` |
| iOS 编解码 | backend | `objc2-video-toolbox 0.3`：`CMVideoFormatDescriptionCreateFromH264ParameterSets` / `...HEVCParameterSets`、`VTDecompressionSessionCreate` / `DecodeFrame`、`VTCompressionSessionCreate`（`kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange`）、`CVPixelBufferGetBaseAddressOfPlane` |
| 鸿蒙编解码 | backend | `native_avcodec_videodecoder.h` / `native_avcodec_videoencoder.h`：`OH_VideoDecoder_CreateByMime/Configure/SetCallback/Start/PushInputBuffer/QueryOutputBuffer/FreeOutputBuffer`；封装层 `native_avsource.h` / `native_avdemuxer.h` / `native_avmuxer.h` |
| Android 桥 | bridge | `jni = 0.21`：`JNI_OnLoad`、`attach_current_thread`、`GlobalRef`、`throw_new`；Kotlin TurboModule 直接调 JNI |
| iOS 桥 | bridge | ObjC++ `.mm` TurboModule + `cbindgen` 生成的头；C 回调 `dispatch_async(main_queue)`；podspec `vendored_frameworks` |
| 鸿蒙桥 | bridge | `ohos-rs`：`napi-ohos` + `napi-derive-ohos` + `napi-build-ohos`（build-dep）；ArkTS `AnyThreadTurboModule` 薄壳 `import vw from 'libvw_napi.so'` |
| RN 规范 | RN | `NativeVideoWatermark.ts` spec + package.json `codegenConfig` |

## 安装清单

### Rust 工具链

```sh
rustup component add rustfmt clippy llvm-tools   # llvm-tools 提供 llvm-readelf/objcopy
```

9 个 target（host 之外）：

| 端 | target | ABI |
|---|---|---|
| Android | `aarch64-linux-android` | arm64-v8a |
| Android | `armv7-linux-androideabi` | armeabi-v7a |
| Android | `x86_64-linux-android` | 模拟器 |
| iOS | `aarch64-apple-ios` | 真机 |
| iOS | `aarch64-apple-ios-sim` | 模拟器（Apple Silicon） |
| iOS | `x86_64-apple-ios` | 模拟器（Intel） |
| 鸿蒙 | `aarch64-unknown-linux-ohos` | arm64-v8a |
| 鸿蒙 | `armv7-unknown-linux-ohos` | armeabi-v7a |
| 鸿蒙 | `x86_64-unknown-linux-ohos` | 模拟器 |

`aarch64-unknown-linux-ohos` / `armv7-unknown-linux-ohos` / `x86_64-unknown-linux-ohos` 都是 **Tier 2 with host tools**（Rust 官方保证能编译，且提供本机 rustc/cargo）；`loongarch64-unknown-linux-ohos` 是 Tier 3。

### cargo 子命令

```sh
cargo install --locked cargo-ndk ohrs xcframework cbindgen cargo-deny cargo-audit
```

| 工具 | 必需 | 作用 |
|---|---|---|
| `cargo-ndk` | 是 | Android：配置 NDK clang/linker，`-o` 直接输出到 `jniLibs` |
| `ohrs` | 是 | 鸿蒙：配置 OHOS sysroot，产出 `.so` + `index.d.ts`；要求 Rust ≥ 1.88、`OHOS_NDK_HOME` |
| `xcframework` | 是 | iOS：打包 XCFramework（`cargo-lipo` 已废弃且处理不了两个 arm64 冲突） |
| `cbindgen` | 是 | 从 Rust 生成 C 头，供 iOS ObjC++ / Android C++ 桥使用 |
| `cargo-deny` | 建议 | license 与依赖审计（拦截 GPL） |
| `cargo-audit` | 建议 | CVE |
| `bindgen-cli` | 可选 | 命令行版 bindgen（库形态一般作 build-dependency） |
| `cargo-nextest` / `cargo-machete` / `uniffi_bindgen` | 可选 | 测试、清依赖、自动生成 Kotlin/Swift 绑定 |

### 宿主机系统包（Debian）

```sh
sudo apt install -y clang libclang-dev llvm ninja-build build-essential perl
```

`bindgen` 运行期依赖 libclang；找不到时设 `LIBCLANG_PATH=/usr/lib/llvm-<ver>/lib`。不需要 `gcc-aarch64-linux-gnu` 等交叉 GCC——NDK 和 OHOS SDK 自带 clang + sysroot。

### 平台 SDK

| 端 | 需要 | 说明 |
|---|---|---|
| Android | SDK platform 36、build-tools 36、NDK 27.1.12297006、CMake 3.22.1、JDK 17 | 常规组合 |
| 鸿蒙 | command-line-tools 26.0.0（hvigor / hdc / ohpm + API 26 SDK）、Node 20 | Node 24 会崩 |
| iOS | macOS + Xcode（含 `lipo`、`xcodebuild`）+ CocoaPods | Linux 上无法构建 |

### Cargo crates

core（三端共用）：

| crate | 版本 | 用途 |
|---|---|---|
| `mp4` | 0.14 | MP4 读写 |
| `mp4parse` | 0.17 | 可选，只读备用解析器 |
| `symphonia` | 0.5 | 可选，非 AAC 音轨 |
| `image` | 0.25（`png`） | 水印解码 |
| `fast_image_resize` | 5 | 缩放 |
| `yuvutils-rs` | 0.8 | YUV 转换 / NV12 合成 |
| `wide` | 0.7 | SIMD |
| `byteorder` / `bytes` | 1 | box、NAL 读写 / 样本缓冲 |
| `num-rational` | 0.4 | timescale |
| `bytemuck` | 1 | 像素 cast |
| `thiserror` | 2 | 错误 |
| `tracing` + `tracing-subscriber` | 0.1 / 0.3 | 日志 |
| `crossbeam-channel` | 0.5 | 进度、取消 |
| `parking_lot` / `serde` / `serde_json` | 可选 | 锁、配置 |

Android：`ndk = 0.9`（features `media`、`audio`、`bitmap`，MIT OR Apache-2.0，已封装 AMediaCodec/AMediaExtractor，可省掉 bindgen）、`jni = 0.21`、`android_logger = 0.14`、`libc = 0.2`。

iOS：`objc2 = 0.6`、`objc2-foundation`、`objc2-core-foundation`、`objc2-core-media`、`objc2-core-video`、`objc2-video-toolbox = 0.3`、`block2 = 0.6`、`oslog = 0.2`（均在 `cfg(target_os = "ios")` 下）。

鸿蒙：`napi-ohos = 1.2`（MIT）、`napi-derive-ohos`、`hilog-sys`、`libc`；build-dependencies 加 `napi-build-ohos`，`build.rs` 调 `napi_build_ohos::setup()`。

build / dev：`bindgen = 0.72`、`cc = 1`（仅不用 `ndk` crate 时）；`tempfile`、`criterion`、`insta`。

### RN 侧

| 端 | 新增依赖 |
|---|---|
| 共享 | `@react-native/codegen` |
| Android | 无新 Gradle 插件：`cargo ndk -o android/app/src/main/jniLibs` |
| iOS | 无新 pod：podspec `vendored_frameworks = 'ios/VW.xcframework'` |
| 鸿蒙 | 无新 HAR：`libvw_napi.so` 放 `harmony/entry/libs/arm64-v8a/` |

## 构建与产物

```sh
# Android
export ANDROID_NDK_HOME=$ANDROID_HOME/ndk/27.1.12297006
cargo ndk -t arm64-v8a -t armeabi-v7a -t x86_64 \
  -o android/app/src/main/jniLibs build --release -p vw-jni

# 鸿蒙（Node 20 必须在 PATH 最前）
export OHOS_NDK_HOME=$DEVECO_SDK_HOME/default/openharmony
ohrs build --release -p vw-napi      # 默认产出 arm64/arm32/x86_64 + index.d.ts

# iOS（仅 macOS）
cargo build --release --target aarch64-apple-ios     -p vw-capi
cargo build --release --target aarch64-apple-ios-sim -p vw-capi
cargo build --release --target x86_64-apple-ios      -p vw-capi
lipo -create target/aarch64-apple-ios-sim/release/libvw.a \
             target/x86_64-apple-ios/release/libvw.a -output libvw-sim.a
cbindgen --crate vw-capi --lang c -o include/vw.h
xcodebuild -create-xcframework \
  -library target/aarch64-apple-ios/release/libvw.a -headers include \
  -library libvw-sim.a -headers include -output ios/VW.xcframework
```

日常循环只跑 `cargo test -p vw-core` 和 `cargo clippy --all-targets`（host target），不碰三端。

## 关键约束与失败模式

1. **16KB 页对齐**：Android 15 起支持 16KB 内存页，so 的 `LOAD` 段 `align` 必须 ≥ `2**14`。NDK r28 及以上默认对齐；r27 及以下必须显式加 `-Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384`。构建后用 `llvm-readelf -l lib.so | grep LOAD` 验证；APK 用 `zipalign -c -P 16 -v 4 app.apk` 验证。Google Play 从 2027-02-01 起，targetSdk 35+ 的更新不支持 16KB 将无法上架。
2. **`bindgen` 找不到 libclang**：设 `LIBCLANG_PATH`；`apt` 安装的路径通常是 `/usr/lib/llvm-<ver>/lib`。
3. **不要引 `openssl-sys`**：鸿蒙 musl 下需要手编 openssl（官方文档要求 `ohos-openssl`），成本远高于收益；要 TLS 用 `rustls`。
4. **鸿蒙链接参数**：手写 linker 必须带 `--target=<arch>-linux-ohos`、`--sysroot=<sdk>/native/sysroot`、`-D__MUSL__`，`ar` 用 SDK 的 `llvm-ar`；用 `ohrs` 可省掉这些。
5. **RNOH 没有 TurboModule C ABI**（0.82.36 只暴露 C++ 虚类）：不要写 C++ TurboModule 再转发 Rust；鸿蒙侧走 ArkTS TurboModule + `napi-ohos`，Android 走 Kotlin TurboModule + JNI，iOS 才需要 ObjC++。
6. **Node 版本**：`ohrs` / `hvigor` 在 Node 24 上会崩，必须用 Node 20。
7. **许可证**：`x264`、`fdk-aac` 是 GPL，`openh264` 自编译有专利费；core 只允许 MIT/Apache/BSD，用 `cargo-deny` 卡住。
8. **iOS 无法在 Linux 验证**：最多 `cargo check --target aarch64-apple-ios`（能过类型检查，链接与真机行为必须在 macOS 上验）。

## 术语表

### Rust 与交叉编译

- **target triple**：`<arch>-<vendor>-<os>-<abi>` 形式的目标平台标识，如 `aarch64-linux-android`；决定 rustc 用哪个 std、哪个 linker、哪个 sysroot。
- **Tier 2 with host tools**：Rust 官方分级。Tier 2 保证「一定能编译」，CI 会拦住破坏构建的提交，但不保证测试全过；带 host tools 表示该平台还能本机运行 rustc/cargo。
- **`cdylib` / `staticlib`**：crate 产物类型。`cdylib` 产出动态库（Android `.so`、鸿蒙 `.so`）；`staticlib` 产出静态库（iOS `.a`，最终链进 App）。
- **sysroot**：交叉编译时目标平台的头文件与库的根目录，clang 用它找 `libc`、`libmediandk` 等。
- **musl**：轻量 libc。鸿蒙 native 用 musl，交叉编译需定义 `__MUSL__`。
- **libclang**：Clang 编译器的 C API 动态库，`bindgen` 靠它解析 C 头文件。
- **bindgen / cbindgen**：前者 C → Rust（生成 FFI 绑定，在 `build.rs` 里跑）；后者 Rust → C（生成头文件给 ObjC++/C++ 用）。
- **lipo**：把多个架构的 Mach-O 合并成 fat binary。它不能合并「同架构不同平台」（真机 arm64 与模拟器 arm64），所以需要 XCFramework。
- **XCFramework**：Apple 的库分发格式，一个 bundle 内按平台/架构分目录存放 `.a`/`.framework` + 头文件，Xcode 自动挑对应切片。
- **16KB page / LOAD segment**：ELF 的 `LOAD` 段对齐值 `2**14` 表示 16KB；小于它在新设备上无法加载。

### 平台与框架

- **NDK**：Android Native Development Kit，提供 C/C++ 头文件、clang 交叉工具链、sysroot 和 `libmediandk` 等库。
- **JNI**：Java Native Interface。`JNI_OnLoad` 在 `.so` 被 `System.loadLibrary` 加载时调用，用于注册 native 方法；native 线程调 Java 前必须 `AttachCurrentThread`。
- **Node-API（N-API）**：Node.js 的稳定 C ABI，跨 Node 版本不重编；鸿蒙 ArkTS 运行时实现了它的子集。
- **`napi_load_module`**：原生侧动态加载 ArkTS 模块的 Node-API 扩展（API 12+），是 native 反向调 ArkTS 的通道。
- **ohos-rs / ohrs**：napi-rs 的鸿蒙分叉。`napi-ohos` 是运行时绑定，`napi-derive-ohos` 提供 `#[napi]` 宏，`napi-build-ohos` 在 `build.rs` 里配置链接参数，`ohrs` 是 CLI。
- **TurboModule**：RN 新架构的原生模块规范；`codegen` 从 TS spec 生成各端接口，避免手写桥接签名。
- **RNOH**：React Native for OpenHarmony，RN 的鸿蒙实现；其 TurboModule 是 C++ 抽象类，没有 C ABI。
- **ArkTS**：鸿蒙的 TypeScript 方言，限制 `any`、动态属性等；**ArkUI** 是声明式 UI 框架。
- **XComponent**：ArkUI 里承载原生渲染 surface 的组件（OpenGL/Vulkan），是 native 侧往 UI 上画东西的入口。
- **HAR / HAP**：HAR 是鸿蒙静态共享包（类似 aar），HAP 是应用安装包。
- **hvigor / ohpm / hdc**：鸿蒙的构建工具（≈ Gradle）、包管理（≈ npm）、设备桥（≈ adb）。
- **BiSheng（毕昇）**：华为基于 LLVM 的编译器工具链，鸿蒙 native 默认用它链接。

### 媒体格式

- **H.264 / AVC**：MPEG-4 Part 10，兼容性最好的编码；**HEVC / H.265** 压缩率约高 50%，专利更贵。
- **NAL unit**：H.264/HEVC 的码流单元。Annex-B 用 `00 00 01` 起始码；MP4 里用 4 字节长度前缀（AVCC 格式）。
- **SPS / PPS / VPS**：序列参数集、图像参数集、视频参数集，解码器初始化必需；HEVC 多一个 VPS。
- **avcC / hvcC**：MP4 的 `AVCDecoderConfigurationRecord` / `HEVCDecoderConfigurationRecord` box，存放 SPS/PPS/VPS，转封装时必须原样搬运。
- **MP4 box**：`ftyp`（品牌）、`moov`（元数据）、`mdat`（媒体数据）、`trak`（轨道）、`tkhd`（轨道头，含旋转矩阵）、`stss`（关键帧索引）、`ctts`（PTS-DTS 偏移，B 帧必需）、`edts`（edit list）、`colr`（色彩信息）、`esds`（AAC 的 AudioSpecificConfig）。
- **faststart**：把 `moov` 移到 `mdat` 之前，使文件可以边下边播；标准库不自动做，需要自己重排。
- **DTS / PTS / timescale**：解码时间戳、显示时间戳、每秒 tick 数。`时长(秒) = duration / timescale`；有 B 帧时 PTS ≠ DTS。
- **YUV 4:2:0**：每 2×2 像素共用一组 UV，数据量为 RGB 的一半。**I420** 是 Y/U/V 三平面；**NV12** 是 Y 平面 + 交错 UV 两平面，移动端硬解输出几乎都是 NV12。
- **stride / slice height**：一行像素实际占的字节数（可能大于宽度，为对齐）、编码器按 slice 对齐的输出高度。忽略它们会导致画面斜切。
- **`COLOR_FormatYUV420Flexible`**：Android 的通用 YUV 格式，具体平面布局由 stride/slice height 决定，必须动态读取。
- **BT.601 / BT.709 / BT.2020**：标清 / 高清 / 超高清的 YUV↔RGB 系数矩阵，用错会偏色；矩阵信息在 `colr` box 里。
- **10-bit / i010 / HDR**：每通道 10 位的 YUV（P010 半平面），HDR 视频必需；8-bit 路径要单独处理。
- **SIMD**：单指令多数据。x86 的 SSE/AVX、ARM 的 NEON；`wide` crate 提供跨平台抽象。
- **AMediaCodec**：Android NDK 的编解码 C API，支持 ByteBuffer 与 Surface 两种模式。
- **VideoToolbox**：iOS/macOS 的硬编硬解框架，纯 C API，配合 CoreMedia 的 `CMSampleBuffer`。
- **OH_AVCodec**：鸿蒙 AVCodec 的 C API（`OH_VideoDecoder_*` / `OH_VideoEncoder_*`），配合 `OH_AVSource`/`OH_AVDemuxer`/`OH_AVMuxer` 完成转封装。
- **AVTranscoder**：鸿蒙 ArkTS 的转码 API；C API 版本没有水印能力，`addWatermark()` 只在 ArkTS 且 API 26 起可用——这正是需要自研合成的原因。
