# RIFE MediaMTX Stream

将本地或网络视频实时补帧并发布到局域网：

```text
Local file -> BestSource -> VapourSynth/RIFE -> FFmpeg NVENC -> MediaMTX
HTTP/HLS   -> FFmpeg CUDA decode/scale -> VapourSynth/RIFE -> FFmpeg NVENC -> MediaMTX
```

项目使用 `runtime` 下的便携 Python、VapourSynth 和 FFmpeg，不依赖系统 Python
或 MPV。

布局：

```text
stream.py / mpv_protocol.py / mediamtx.py / webui.py / check_setup.py   CLI 入口
rife/        路径、协议、转码、MediaMTX、环境检查
vs/          VapourSynth 脚本
tests/       单元测试
runtime/     便携 Python、VSPipe、FFmpeg、插件
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
runtime\python.exe mpv_protocol.py install --force
```

卸载并恢复安装前的协议处理器：

```bat
runtime\python.exe mpv_protocol.py uninstall
```

首次请求会启动转码并发布到 MediaMTX；后续请求会替换当前媒体，不会保留重复转码进程。

## 直接运行

指定本地或网络输入：

```bat
runtime\python.exe stream.py "D:\video\input.mkv"
runtime\python.exe stream.py "https://example.com/video.m3u8" ^
  --http-header-field "Referer: https://example.com/watch"
```

常用参数：

```bat
runtime\python.exe stream.py "D:\video\input.mkv" --duration 10
runtime\python.exe stream.py "D:\video\input.mkv" --max-height 720 --quality 16
runtime\python.exe stream.py "D:\video\input.mkv" --audio-codec aac
```

`stream.py` 会在 RTSP 和本地控制 API 未监听时自动启动 MediaMTX。新分辨率首次运行时，
TensorRT 需要构建引擎；后续运行复用 `runtime\vs-plugins\models\rife_v2` 缓存。

默认视频编码为 H.264 NVENC CQ 16，使用 p4、HQ、四分之一分辨率双遍和空间 AQ，
目标是实时 1080p HLS 下尽量保持观感。码率不设固定上限，会根据画面复杂度变化；
`--quality` 越小质量和码率越高。这不是数学无损编码。

## Web UI

浏览器打开 `http://<PC-LAN-IP>:10000`：

- 批量粘贴 HTTP/HTTPS 链接
- 列表中点击某一集切换转码；支持上一集 / 下一集
- 页面显示 HLS 清单地址，用外部播放器打开即可

```bat
runtime\python.exe webui.py
```

Web UI 会在需要时启动 MediaMTX。切集时会替换当前转码进程，与协议入口相同。

## 播放地址

将 `<PC-LAN-IP>` 替换为本机局域网地址：

- HLS 清单：`http://<PC-LAN-IP>:8888/rife/index.m3u8`

HLS 按事件清单从已有分片的开头顺序播放，卡顿时等待缓冲，不追服务端实时沿。协议或 `stream.py` 再次启动时会替换当前转码进程。若要从指定位置开始，使用 `--start`。

## 管理命令

```bat
runtime\python.exe check_setup.py
runtime\python.exe mediamtx.py status
runtime\python.exe mediamtx.py restart --replace
runtime\python.exe -m unittest discover -s tests
```
