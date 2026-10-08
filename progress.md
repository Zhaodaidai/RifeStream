# 优化进度

- 已初始化性能优化计划和发现记录。
- 已完成：合并视频与字幕的单次 `ffprobe`，避免网络媒体重复打开。
- 已完成：优化 VapourSynth rawvideo 平面复制，减少每帧切片和地址转换。
- 已完成：让 VapourSynth 直接读取 raw pipe 底层文件对象，减少 Python 缓冲层。
- 已完成：补充回归测试；当前测试总数为 68 个。
- 已完成：更新协议行为文档，明确 `mpv://` 只加入播放列表。
- 暂缓：NVENC、TensorRT 并发和 HLS 缓冲参数，等待可用 NVIDIA 环境进行真实性能基准。
- 已完成：清理 HLS 清单的可选 `EXT-X-INDEPENDENT-SEGMENTS` 写法；保留 `temp_file`、H.264/AAC MPEG-TS、版本和时长等浏览器兼容所需内容；全量测试通过。
- 已完成：清理 HLS 清单的可选 `EXT-X-INDEPENDENT-SEGMENTS` 写法；保留 `temp_file`、H.264/AAC MPEG-TS、版本和时长等浏览器兼容所需内容；全量 70 项测试通过。
