# 性能排查发现

- 流水线位于 `rife/stream.py`、`vs/rife_stream.vpy`：FFmpeg NVDEC/rawvideo → VSPipe/Y4M → VapourSynth/RIFE → FFmpeg NVENC/HLS。
- 当前工作区只有 `var/hls_server.log`、`var/webui.log` 运行日志变更，属于环境产物，不作为功能变更。
- 当前已有测试：`tests/test_stream.py`、`tests/test_pipe_frames.py`、`tests/test_webui.py`、`tests/test_protocol.py`。
- 已确认无画质变化的优化点：合并视频/字幕 `ffprobe`、减少每帧 YUV 地址计算、保持 VapourSynth 平面复制的 stride 处理。
- NVIDIA 驱动在当前 Linux 环境不可用，无法进行真实 GPU 吞吐基准；GPU 参数不做未经验证的激进调整。
- 不能仅按分辨率跳过 `scale_cuda`：输入可能是 10-bit，仍需要可靠的像素格式转换；该猜测性优化已撤回。
- `sys.stdin.buffer.raw` 可直接配合 `readinto()` 使用，避免 Python BufferedReader 的额外缓冲层。

- Web 页面目前仅管理转码，没有 video。HLS 地址固定，切集和 seek 必须以会话标识重建播放器，不能只比较 URL。
- position 是转码墙钟估算，不是观看进度；网页进度应使用 start + video.currentTime。
- 最终实现：playback_id + hls_ready 避免固定 URL 的旧会话混用；全局进度使用 start + currentTime；去除按转码墙钟忽略显式 seek 的旧分支。本地 hls.js 1.6.13 携带许可证。
- 布局调整范围锁定 web/index.html、web/app.js、web/styles.css；整集进度继续复用 seekSeconds，保留片头时间解析，仅删除跳转时间输入及其事件绑定。
- 本轮仍锁定 web/index.html、web/app.js、web/styles.css，复用 /api/items，play=false；使用原生 dialog 保留焦点和 Escape 关闭，错误留在弹窗中。

## 整体 UI 优化
- 入口 web/index.html；Python ThreadingHTTPServer 静态资源 + JSON API，无客户端路由/打包器；app.js 状态和操作、player.js HLS 会话分离，保留现有技术栈。
- 使用石墨灰与浅绿色统一主题、无远程字体/图标依赖；CSS/SVG 原生组件。
- 改善 renderState 列表签名缓存，轮询不再销毁相同 DOM，保留滚动及键盘焦点。添加/播放/删除/清空/停止错误捕获，设置内联验证和保存反馈。
- 浏览器首次因 Python 模块搜索路径缺少 playwright 失败（exit 1），改用已存在 /tmp/rife-player-tools，不引入项目依赖。

## PC 首屏垂直居中完成
- 仅修改 web/styles.css 桌面媒体查询：隐藏介绍/页脚，main flex 垂直居中，workspace 自适应视口高度，video-stage 弹性分配并保持视频比例；移动端保持。
- Chromium 1440×900、1920×1080、1366×768、1280×720、1024×768、861×700 无首屏滚动，播放器与列表整体在头部以下居中。移动端、HLS、切集、跳转、设置、弹窗、错误和键盘回归通过；77 项 Python 与 Node 测试通过。
- 同四角色重新打开；初始 baseline 和 rollback 未有居中机制，modified 有；补丁重建一致，回滚恢复原始哈希。历史验证保存在 VERIFICATION-before-center.txt，本轮 center-browser-output.txt。

## Plyr 接入
- 使用官方 npm plyr-3.8.4.tgz，SHA256 9ec5b3ec3573adbbc173b00c55f3791b983722823f11784a7433b35acd51d2d6；JS/CSS/SVG/MIT 许可证本地自托管，未添加打包器。
- EmbeddedPlayer 构造时创建一次 this.ui；destroy 仍只重置 HLS，会话切换不反复销毁 UI。外部整集进度不被 Plyr 片段时间替代。
- controls 仅播放、音量、速度、画中画和全屏，无无效字幕/清晰度/片段进度菜单；focused keyboard，不占用全局快捷键。
- 使用官方 CSS variables 微调浅绿色/深色菜单/圆角；全局按钮样式排除 Plyr 控件，Plyr wrapper 接入既有自适应/居中布局。
- 本地 iconUrl，blankVideo 用内嵌微型黑色视频，防止默认第三方 blank.mp4 请求。
- 下载许可证初次用错 LICENSE 文件名（exit 1），实际 LICENSE.md 已复制；浏览器探针初次假设 SVG 插入 DOM，实际使用外部同源 use；settings 控件和子菜单共用 data-plyr，测试选择器已限定 aria-controls。
