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

## 整集进度移入 Plyr，移除外部地址
- 用户追加要求：不单开一行，按 Plyr 同一控制栏布局。使用官方 plyr__progress / plyr__progress__container 和原控件样式，插入播放按钮与音量组之间；不启用原生片段 seek，整集时长与偏移由 EmbeddedPlayer 驱动。
- 页面 external player/URL/copy、app 事件和旧 CSS 已移除；hls_url 仅供内部 HLS 加载，未破坏播放接口。
- range input 拖动预览与 change 提交；键盘事件阻止误触发 Plyr 片段快进；未知时长禁用；远端 seek 忙碌期间不被轮询覆盖，失败恢复真实位置。
- 窄屏保留同一行，隐藏音量滑条和画中画入口以保留可操作空间（静音/音量按钮、设置、全屏保留）。
- 浏览器初次布局探针在控件隐藏动画中读到过渡位置，改 reduced-motion + 等待布局稳定；注入 seek HTTP500 产生预期控制台错误，断言改为仅允许这条错误。
- 同行插入首次错误：mute 按钮位于 volume 子元素，insertBefore 要求直接子元素（真实 DOMException，启动播放超时exit1）；已改以直接 volume 容器为锚点。

## 标题/状态位置与控制区分割线完成
- 顶部只显示当前媒体名（长名称省略，title保留全文），删除播放器/HLS STREAM和下方重复已选择区。playerHint 在停止转码右侧，手机一起换行；无溢出。
- playback-controls 上下border已删除，保留padding；Chromium 320–1920px边框计算0px、状态/切集/空值/首屏居中检查通过。83项Python与Node通过；Plyr整集进度、全屏、拖动/错误、键盘和UI接口回归通过。
- 四角色更新重开、补丁重建一致、隔离回滚原始70项和哈希一致；title-before 原字节哈希保留，历史账本追加进 VERIFICATION.txt。

## 时间在进度前 + 原版 Plyr 按钮完成
- clock在DOM和视觉均位于slider左侧，同一行；整集进度/全屏/业务未变。
- 撤除原自定义Plyr绿色、6px圆角、深色菜单/tooltip变量，保持官方3.8.4原字节，白图标/4px圆角/蓝色hover；页面外部按钮不改。
- 用户给的plyr.io当前改为Video.js迁移页，未擅自换库。
- Chromium 320–1920时间在左、同排、播放seek/全屏/拖动/错误与UI回归通过，84项Python与Node通过。同四角色重开，补丁重建一致，回滚历史原始70项与哈希一致。

## 全站Plyr蓝色完成
- 仅styles/index变更，原绿色accent和状态底色/边框、hover、开关、选中项、focus、图标和favicon统一#00b2ff蓝色系，深色背景/布局/业务不变。
- Chromium计算颜色验证品牌/主按钮/hover/开关/焦点/弹窗/列表选择通过，320–1920布局、标题和状态回归通过，无未捕获JS错误；84项Python和Node通过。
- 同四角色重开，补丁重建和回滚原始哈希一致；修改前green，修改后blue，历史rollback恢复原始状态70项通过；blue-before备份保留。

## 主题统一管理完成
- web/theme.css 集中颜色/字体/基础圆角，--accent:#00b2ff，--plyr-color-main共享变量，hover/focus派生；styles仅引用变量，index按vendor/theme/styles加载；README与防回归测试补齐。
- 浏览器RGBA规范化比较普通/hover/focus/弹窗颜色与圆角均一致；仅改accent可联动主按钮/品牌/开关/Plyr hover。320–1920无溢出、HLS跳转/全屏/键盘/拖动/失败恢复和隔离真实API通过。
- 85项Python和Node通过，四角色路径保持不变并重开；历史70项基线/回滚哈希一致，补丁可重建修改。当前工作区保留新主题，生产播放列表未改。

## 播放链路发现
- hls_ready仅判mtime，空stub也会被当成可播放；切集/seek复用seg0.ts可能串旧缓存。
- player loadedmetadata自动播放不区分暂停意图；异步play拒绝可能覆盖新会话提示，重载回退到片段开头；seek期间旧流仍可继续播放。
- setInterval轮询可能重叠，多个修改响应缺少全局顺序；服务端ThreadingHTTPServer控制/快照无统一锁，转码进程启动窗口stop遗漏。

- 已修复：首片完整才ready；转码会话切片唯一命名、.ts禁缓存；服务端RLock串行事务并跟踪启动期子进程，旧进程仅可清理自己的PID/status；客户端修改请求排队、轮询单飞/超时、暂停意图/回调epoch、seek失败恢复和重试保留位置。
- 删除GET状态轮询按墙钟自动切片尾的副作用，改为播放器真实ended后按原skip_outro设置衔接下一集，避免转码快于播放时截断当前流。
- 首次回归exit1：旧用例仍假设seg%d.ts和空EXTM3U已ready；Node假seek不回传新会话。补充真实状态协议用例，替换失效预期，不放宽功能断言。

- 浏览器native旧断言两次exit1：seek请求增加playback_id；stop现立即解绑，等待条件需同时确认请求结束/服务端停止，而非只等key=null。已按新协议调整探针。
- diff检查exit2暴露原文件混合CRLF/LF，新行CR被视为尾空格；保留原有未改行字节，新改行LF；重新检查。日志管道读完增加close，消除实际子进程测试的ResourceWarning。

- 四角色首次复验exit1：历史probe仅mock position，优化后seek使用统一playback_snapshot.duration导致KeyError；补全probe模拟的既有duration字段，同一输入分别重测baseline/modified/rollback。

- 最终复核补强：控制请求失败/超时后先立即refresh服务端真实状态，再恢复媒体，避免较早成功响应被队列隔离后却用更旧currentState恢复。新增确定性断言禁止失败动作直接复活旧媒体。

## 播放链路交付完成
- 前端请求顺序队列、单飞轮询、20秒超时/过期响应隔离；失败先同步服务端真实状态，不用旧currentState复活媒体。player按会话/epoch隔离回调，暂停意图、seek失败/停止竞态和重试位置恢复均覆盖。
- 服务端控制/快照RLock、跟踪启动子进程并等待停止；首片非空才ready；seek验证playback_id并复用已校验duration；唯一切片名和.ts no-store；按worker归属释放状态，保留正常完成的视频。
- 状态轮询只读，skip_outro用实际ENDLIST/ended切集；准备/转码/完成状态分开。技术栈不变，新增依赖0。
- 95项Python、两组Node、Chromium真实HLS跨至少3段、暂停后10:00远端跳转、真正播放ended切一次下一集、快速启停/旧seek拒绝、320–1920布局和真实API隔离回归均通过。预计注入的seek500之外无未预期控制台错误；未验证目标Windows GPU/TensorRT性能。
- 历史BASELINE70/ROLLBACK70及原始哈希一致，MODIFIED95；四角色重开，完整补丁重建哈希一致。flow-before85项快照原字节哈希保留。现有10000旧Python进程及转发8888未强制重启，部署需在目标运行环境重启WebUI/HLS；未修改用户播放列表。
