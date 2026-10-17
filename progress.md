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

## 2026-10-17 内置播放器
- 基线：python -m unittest discover -s tests，70 项通过。原文件备份在 /tmp/rife-player-transaction/baseline。

- 复制项目进行回滚验证时，首次漏拷 vs/*.vpy 导致隔离副本测试失败（exit 1）；已将 VS 脚本加入副本后重新验证。实际工作区 73 项测试此前已通过。
- 完成：73 项 Python 测试、Node 播放器状态测试、真实 Chromium 解码无 ENDLIST 的 live HLS（确认从首片播放）、切集、整集跳转、停止、390px 宽度检查。浏览器控制接口使用测试桩，未运行 NVIDIA/RIFE 真实转码。
- 回滚副本恢复原始哈希、70 项原始测试通过；补丁重建后哈希与修改副本一致。四角色在 /tmp/rife-player-transaction；已重新打开校验。
- 重复补丁验证首次复用了已打补丁的临时目录（exit 1）；修正为每次从干净基线重新创建验证副本。
- 最终确认工作区源码和静态资源与已验证副本一致（排除测试生成的 var 日志）；补丁和回滚复验成功，四角色已重新打开。

## 播放器布局调整完成
- 删除 jumpTo/jumpBtn/jumpLabel 及事件；保留 seekSeconds 供整集进度使用。
- 切集、播放、停止、片头、跳过片头、Anime4K 集中到进度条上方；列表右侧栏独立滚动，窄屏下移。
- Python 75 项通过，Node 播放器测试通过；Chromium 861/1024/1280/1600 桌面和 320/390/860 窄屏布局、120 项列表滚动、设置保存、切集、跳转、停止通过。
- 复用 /tmp/rife-player-transaction 四角色。修改副本及补丁已更新，回滚脚本继续恢复最初基线（70 项测试），恢复哈希一致；追加布局基线、修改、回滚探针。
