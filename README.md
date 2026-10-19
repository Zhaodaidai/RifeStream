# RIFE HLS Stream

将本地或网络视频补帧并发布到局域网：

```text
Local/HTTP -> FFmpeg NVDEC + scale_cuda -> VapourSynth/RIFE -> FFmpeg NVENC -> HLS
```

项目使用 `runtime` 下的便携 Python、VapourSynth 和 FFmpeg，不依赖系统 Python
或 MPV。

布局：

```text
run.py           唯一 CLI 入口（stream / webui / hls / protocol / check）
rife/            路径、协议、转码、HLS 服务、环境检查
vs/              VapourSynth 脚本
web/             Web UI 静态页
tests/           单元测试
runtime/         便携 Python、VSPipe、FFmpeg、插件
var/             运行时 pid、播放列表、日志（自动生成）
```

## URL 协议

协议接收器支持：

- `ush://MPV?<gzip-base64 MPV command>`
- `mpv://<percent-encoded HTTP/HTTPS URL>`

可接收视频、独立音频、Origin、Referer、Cookie、User-Agent、代理、
yt-dlp 格式、标题和起始位置。未知 MPV 参数会被忽略；协议入口不接受本地文件。

注册当前 Windows 用户的协议处理器：

```bat
cd /d D:\rife
runtime\python.exe run.py protocol install --force
```

卸载并恢复安装前的协议处理器：

```bat
runtime\python.exe run.py protocol uninstall
```

协议请求只会把媒体加入 WebUI 播放列表，不会自动启动转码；请在 WebUI 中点击播放。

## 直接运行

指定本地或网络输入：

```bat
runtime\python.exe run.py stream "D:\video\input.mkv"
runtime\python.exe run.py stream "https://example.com/video.m3u8" ^
  --http-header-field "Referer: https://example.com/watch"
```

常用参数：

```bat
runtime\python.exe run.py stream "D:\video\input.mkv" --duration 10
runtime\python.exe run.py stream "D:\video\input.mkv" --max-height 720 --quality 12
runtime\python.exe run.py stream "D:\video\input.mkv" --audio-codec aac
runtime\python.exe run.py stream "D:\video\input.mkv" --subtitle-stream 1
runtime\python.exe run.py stream "D:\video\input.mkv" --subtitles "D:\video\ep01.ass"
runtime\python.exe run.py stream "D:\video\input.mkv" --no-subtitles
```

本地和网络 MKV/MP4 会在 RIFE 补帧之后、NVENC 之前硬嵌第一条文本字幕（ASS/SRT 等）。
网络内嵌字幕会先抽出 ASS 和字体再烧录。位图字幕（PGS 等）会跳过。

`run.py stream` 会在需要时启动 HLS HTTP 服务。新分辨率首次运行时，
TensorRT 需要构建引擎；后续运行复用 `runtime\vs-plugins\models\rife_v2` 缓存。

默认视频编码为 H.264 NVENC CQ 12，音频为 AAC。使用 p4、HQ、四分之一分辨率双遍，
以及空间和时间 AQ，目标是 1080p HLS 下接近视觉无损。码率不设固定上限，会根据画面复杂度变化；
`--quality` 越小质量和码率越高。这不是数学无损编码。

## Web UI

浏览器打开 `http://<PC-LAN-IP>:10000`：

- 批量粘贴 HTTP/HTTPS 链接
- 列表中点击某一集切换转码；支持上一集 / 下一集
- 页面内置 HLS 播放器，播放、切集后自动加载，不必再手动向外部播放器粘贴地址
- 拖动播放器下方的「整集进度」跳转；已生成的范围内直接定位，其他位置调用后端跳转并自动等待新分片
- 视频自带的进度条仅对应当前转码会话已生成的片段；观看进度按视频实际播放时间计算
- 浏览器禁止有声自动播放时，点击视频中的播放按钮继续；暂停仅暂停观看，「停止转码」会停止后端
- 顶部仍可复制 HLS 地址给外部播放器；hls.js 已随项目本地提供，无需访问 CDN
- **缩放**：高于输出上限的片源通过 CUDA Lanczos 直接缩小；默认最高 1080p。
- **分辨率**：720p 保持 720p，1080p 保持 1080p，4K 默认缩至 1080p。
- **Anime4K**：保留手动开关，默认关闭；动漫可手动开启，真人剧集可关闭。不按分辨率自动开启或强制跳过。开启时 ACNet 2× 放大后缩回管线尺寸，再送入 RIFE，不改变最终输出尺寸；设置从下一次播放或重新转码生效，并会保存。
- CLI 可加 `--anime4k` 启用；不加则关闭。只有开启时才需要 `runtime\vs-plugins\ac_filter_avs_vs.dll`（Anime4KCPP）插件。

```bat
runtime\python.exe run.py webui
```

Web UI 会在需要时启动 HLS 服务。切集时会替换当前转码进程，与协议入口相同。

## 播放地址

将 `<PC-LAN-IP>` 替换为本机局域网地址：

- HLS 清单：`http://<PC-LAN-IP>:8888/rife/index.m3u8`

HLS 是持续增长的 live 清单：从已有分片开头顺序播放，卡顿时等待缓冲，不追实时沿。
WebUI 或 `run.py stream` 启动新的媒体时会替换当前转码进程。若要从指定位置开始，使用 `--start`。
停止播放、切换完成或转码异常退出时，会清理本项目生成的 HLS 清单和分片缓存。
转码自然完成后保留清单和分片，确保客户端可以继续播放尚未追上的内容。
网络输入只在连接错误时自动重连；媒体正常结束时不会把 EOF 无限重连。

## 管理命令

```bat
runtime\python.exe run.py check
runtime\python.exe run.py hls status
runtime\python.exe run.py hls restart
runtime\python.exe -m unittest discover -s tests
```

### 内置播放器界面

播放器采用本地自托管的 Plyr 3.8.4（MIT），仅负责播放控件；HLS 加载继续使用 hls.js。
JS、CSS 和 SVG 图标均放在 `web/vendor/`，运行时不依赖第三方 CDN。Plyr 保留原有控件风格，少量适配浅绿色强调色和深色菜单。
视频内提供播放/暂停、音量、播放速度、画中画（浏览器支持时）和全屏；整集进度直接集成在 Plyr 控制栏内（全屏同样可用），显示 `起播偏移 + video.currentTime / 整集时长`；已缓冲位置本地跳转，其他位置调用服务端重建转码。页面不再提供外部播放器地址或复制入口。
切集、片头和转码控制仍使用原有接口。桌面播放器与播放列表继续在首屏整体居中。

### 主题统一管理

- `web/theme.css`：唯一颜色变量入口，统一背景、文字、边框、主色及组件状态；`--accent` 是 WebUI 与 Plyr 共用主色。
- `web/styles.css`：布局与组件规则，只引用主题变量，不散落颜色值。主色 hover/focus 自动派生。
- Plyr 原版按钮、图标与圆角不覆盖，仅将官方 `--plyr-color-main` 连接到主色。
- 浏览器 favicon 和 theme-color 属于独立浏览器元数据，位于 `web/index.html`；更换品牌配色时同步修改这两项，不通过运行时脚本改图标。


### WebUI 播放链路与会话边界

- 流程：控制请求排队 → 服务端串行选择媒体/替换转码进程 → 探测与生成首片 → 完整切片发布后挂载 HLS → 连续追加播放 → 转码完成后仍可观看已生成内容。界面区分准备视频、转码中、转码完成。
- 整集跳转优先使用已缓冲范围；未生成的位置重新转码。seek 请求携带 playback_id，拒绝旧会话误操作。暂停后跳转/重连保持暂停；加载重试恢复片段内位置，不回到开头。
- 切集/停止立即解绑旧媒体、取消重试；过期 HLS 回调和自动播放 Promise 不得影响新会话。状态轮询单飞，修改操作按顺序请求，旧响应不能覆盖后续操作。请求超时会提示重试，不自动重发可能已执行的操作。
- 每次编码使用唯一切片文件名，避免跨集或跳转后 seg0.ts 串流；播放列表和切片响应禁缓存。FFmpeg 保持 temp_file 原子发布，首片不存在或为空时不会提前判为可播放。
- 启动期尚未写 PID 的子进程同样可以停止；旧 worker 不得删除后继会话的 PID/status/切片。转码完成保留已生成视频，失败才清理所属输出。
- 状态 GET 不再按转码墙钟自动切走内容；启用 skip_outro 时按编码截尾，并由播放器实际 ended 衔接下一集。普通播放不擅自新增自动连播。

回归命令：`python -m unittest discover -s tests`、`node tests/test_web_player.js`、`node tests/test_web_requests.js`。无需新增依赖；GPU/TensorRT 完整转码仍需在目标运行环境验证。

### 并发独立调节与性能对比

旧 `--gpu-threads` 保持兼容：不传新参数时，RIFE `gpu_t` 与 VSPipe 请求数仍使用它，VS 工作线程仍为 `max(2, gpu_threads)`。

- `--vs-requests N`：仅覆盖 VSPipe 并发帧请求数，不改 RIFE `gpu_t`。
- `--vs-threads N`：覆盖 VS 工作线程数；不改 VSPipe 请求数或 RIFE `gpu_t`。
- `--raw-prefetch N`：独立覆盖 raw 帧预取窗口。只传 `--vs-threads` 时，预取窗口固定为旧 `--gpu-threads` 对应的默认值；不传任何新参数时，完全沿用旧映射。
- `--perf-report NEW.json`：默认关闭。打开后，增加 FFmpeg progress 文件与原始帧计时，最终生成独立 JSON；拒绝覆盖已有报告。报告路径不可与输入/播放清单共用。

```bat
runtime\python.exe run.py stream "D:\video.mkv" --start 60 --duration 30 --vs-requests 4 --perf-report var\sample-perf.json
```

报告包含实际生效的并发参数、编码端输出帧计数/整体 FPS、首次完整 HLS 分片可用时间、原始帧读取/借用等待/复制耗时、缓存命中/未命中、帧缓存峰值与缓冲区峰值。时间起点是解码进程启动前，**不包含输入探测**；包含模型初始化、上游等待与清理。首次 HLS 时间以约 250ms 的轮询观测，并非浏览器首画面时间。多回调的累计等待/复制时间可以大于墙钟时间。原始帧读耗时包含等待上游，编码器进度也包含被上游饿住的影响，**均不是独立 GPU 推理或编码耗时**。借用/交付次数包含重复请求。原始缓冲预算不是总 RSS/显存；当前不测 GPU 显存。非正常退出可能只留下非最终快照，缺失指标用 null/`missing_measurements` 明示，不补造数据。报告写入失败警告不会把成功播放改成失败。

固定素材对比工具（先停止播放，每次用新的输出目录）：

```bat
rem 只生成可核查计划，不启动转码
runtime\python.exe tools\benchmark_pipeline.py "D:\video.mkv" --start 60 --duration 30 --runs 3 --label base --output-dir var\bench-base --dry-run
rem 实际基线：去掉 --dry-run，并使用另一个新的输出目录
runtime\python.exe tools\benchmark_pipeline.py "D:\video.mkv" --start 60 --duration 30 --runs 3 --label base --output-dir var\bench-base-real
rem 只改变 VSPipe 请求数，其余条件不变
runtime\python.exe tools\benchmark_pipeline.py "D:\video.mkv" --start 60 --duration 30 --runs 3 --label req4 --vs-requests 4 --output-dir var\bench-req4
```

工具记录输入 SHA256、固定片段与配置、每次命令/退出码/原生 stdout/stderr、独立 HLS 与 JSON、后续重复运行中位数。两组 `comparison_group` 相同才满足工具记录的素材/画质/片段条件（仍需人工保持驱动、机器负载等外部环境一致）。首轮标为 `first-in-batch`，后续为 `repeat`，**不自动宣称冷/热启动**：工具不会删除 TensorRT 引擎或驱动缓存，计算素材哈希还可能预热文件缓存。若需真正冷启动，应在可控环境手动准备后单独运行，不与重复运行混合统计。检测到活动/待启动会话时拒绝执行；测试期间不要从其他客户端发起播放。

只对比 VapourSynth 工作线程时，先用基线记录当时生效的预取值（例：`--gpu-threads 3` 的旧默认是 12 帧），两组都显式传 `--raw-prefetch 12`：

```bat
runtime\python.exe tools\benchmark_pipeline.py "D:\video.mkv" --start 60 --duration 30 --runs 3 --label vs3-prefetch12 --vs-threads 3 --raw-prefetch 12 --output-dir var\bench-vs3
runtime\python.exe tools\benchmark_pipeline.py "D:\video.mkv" --start 60 --duration 30 --runs 3 --label vs5-prefetch12 --vs-threads 5 --raw-prefetch 12 --output-dir var\bench-vs5
```

`comparison_group` 汇总输入哈希、片段、分辨率、倍率、画质、音频/字幕等固定项，不包含正在比较的并发数；相同组可作为“只改并发参数”的校验。仍需操作者确保驱动版本、温度/功耗与无后台负载等外部因素一致。工具对每个独立worker使用原有 session ownership 事务预留，不会调用替换/停止其他播放进程；正在启动/探测/播放时拒绝开跑。 `--raw-prefetch`、`--vs-requests` 和 `--vs-threads` 均为正整数覆盖项，缺省映射保持原状。
