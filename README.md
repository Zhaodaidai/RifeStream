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
- **Anime4K**：开后先 2× 升到约 4K，再缩回输出分辨率，然后 RIFE；下次播放生效

```bat
runtime\python.exe run.py webui
```

也可在 CLI 直接启用：

```bat
runtime\python.exe run.py stream "D:\video\input.mkv" --anime4k
```

需要 `runtime\vs-plugins\ac_filter_avs_vs.dll`（Anime4KCPP v3.2 VS 插件）。

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
视频内提供播放/暂停、音量、播放速度、画中画（浏览器支持时）和全屏；整集进度继续使用视频下方的进度条，避免把当前 HLS 片段时间误认为整集时间。
切集、片头、Anime4K 和转码控制仍使用原有接口。桌面播放器与播放列表继续在首屏整体居中。
