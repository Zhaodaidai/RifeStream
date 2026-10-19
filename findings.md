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

## PC播放器画面比例
- 原因是桌面workspace固定高度，video-stage flex:1撑满，video object-fit:contain在不匹配的容器里上下留边；手机规则无需变更。
- 仅桌面workspace自然高度，stage按视频固有比例适配可用宽高，测量实际标题/操作栏/页面留白避免魔法高度；metadata/视频尺寸/窗口与操作栏变化合并到rAF更新，移动端移除inline尺寸回到原CSS。不裁切、不改编码、不改播放会话。

- 首轮交互探针exit1发现：PC转手机时，直接inline宽高在rAF前短暂撑宽移动布局；已改为仅桌面CSS读取动态frame变量，手机立即忽略PC尺寸，消除跨断点瞬态溢出。另Plyr控制栏测量落在隐藏位置，正在记录class/transform确认交互状态，不放宽边界断言。

- 控制栏探针debug已确认class=plyr--hide-controls、transform=translateY(77px)，即Plyr自动隐藏而非控件跑出容器。探针改为窗口布局稳定后真实hover唤出控件，再核验同排/边界，保持所有边界断言。移动端瞬态溢出修复后，原真实API多断点探针无等待也通过。

## PC上下黑边修复交付
- 只改web/player.js、styles.css及两个现有测试；手机CSS/业务/API/编码/Plyr vendor保持原字节。PC工作台自然高度，fitFrame以真实videoWidth/videoHeight和可用空间计算，桌面专用--frame-width/height，不使用cover。
- 真实1080p/4K HLS浏览器解码：1440x900原上下额外留边合计93.609375px→0；1920x1080原158.109375px→0；短屏亚像素误差<0.006px。390/768全部已记录尺寸前后一致。截图已人工查看。
- 95项Python和两组Node、原实际HLS跳转/暂停/失败恢复/全屏/拖动/键盘及320–1920布局回归通过，无未预期JS错误。原控制栏探针在隐藏状态测量失败，经实际hover唤出后所有边界断言通过；移动断点瞬态溢出通过桌面作用域变量修复。
- 同四角色重开、完整补丁重建/隔离回滚哈希一致；BASELINE/ROLLBACK历史70项，当前MODIFIED95项。aspect-before原字节保留。10000服务实际player.js/styles.css与工作区SHA一致，前端刷新即可加载，无后端改动。

手机竖屏全屏：Plyr原配置没有方向锁定。改以video-stage为全屏根节点，内部Plyr整体旋转可绕开原生fullscreen根节点的transform限制；保留真实整集进度。

## 2026-10-17 1080p 缩放链路修改（用户授权覆盖旧画质约束）
已完成：CUDA 缩放改 Lanczos；输入高度达到输出上限或不设高度上限时跳过 ACNet，日志与环境变量一致；低清保留手动开关及原输出尺寸。编码/RIFE不变。BASELINE95、MODIFIED96、ROLLBACK95、部署96项通过，回滚哈希一致，字节保真补丁重建一致。混合换行导致的首次补丁失败已保留并修正。四角色沿用 /tmp/rife-player-transaction/{MODIFIED_FILE,DIFF_FILE.patch,VERIFICATION.txt,ROLLBACK.sh}；本轮回滚模式 --scale-before。未实测 Windows NVIDIA GPU 的画质、吞吐及实时播放。

## 2026-10-17 移除手动 Anime4K 与往返超分
用户不要求低清升分辨率。已移除UI开关、设置字段、CLI参数、VS ACNet阶段和插件必需检查；历史设置被忽略，继承环境变量强制置0。不改720p输出尺寸，不改RIFE/NVENC，保留Lanczos缩小。BASELINE96、MODIFIED98、ROLLBACK96，Node两组/JS语法检查通过，字节保真补丁重建和回滚原始哈希一致。沿用原四角色；本轮回滚 --no-anime4k-before。未实测Windows GPU；需重启WebUI并重新开始转码。

## 恢复 Anime4K 手动开关（当前请求）
进行中：复用移除前已确认实现，恢复UI/持久化/CLI/VS；改为纯手动控制、默认关闭，不按分辨率强制跳过；Lanczos及输出尺寸/RIFE/NVENC不变。复用原四角色，新增 manual-anime4k-before 原字节快照；不修改其他未完成任务。

恢复 Anime4K 手动开关已完成：默认关闭；开启/关闭分别控制所有输入分辨率的ACNet，不再受高度条件限制；恢复持久化、CLI和下一次播放/seek传参，720p/1080p/4K输出尺寸及Lanczos/RIFE/NVENC不变。实际本轮 BASELINE100项、MODIFIED99项、ROLLBACK100项通过（移除过时的功能删除测试并恢复/新增开关测试），两组Node与JS语法通过；Chromium以生产HTML/JS和隔离模拟API验证开/关请求及刷新回显，无pageerror。字节保真补丁重建与隔离回滚原始哈希一致。沿用四角色，回滚模式 --manual-anime4k-before。未实测Windows GPU；需重启WebUI并重新开始转码。不改同时进行的播放器导航任务。

播放器导航：在真实Plyr控制栏播放按钮两侧插入同类按钮，has_prev/has_next决定hidden，仍调用现有/api/play offset±1；内部播放拦截仅在空闲时启动转码，已加载时保留Plyr本地暂停/恢复。请求busy覆盖三个入口，首末切换的焦点在完成后恢复。861窄桌面隐藏音量滑杆，手机压缩图标边距，保持进度条一行。独立Anime4K设置更新已保留。

WebUI打磨：清空原先立即POST且停止转码；改为原生dialog默认保留列表，成功后关闭、失败内联重试，pending禁止重复提交/Escape。轮询失败独立连接提示不重置media，单航班刷新与版本屏障保留，恢复自动隐藏并避免隐藏控件残留焦点。仅复用现有主题token，移动列表操作40px触控；不改Plyr/转码业务。

## 2026-10-18 播放器画面缩放
- TARGET 为 web/player.js 的 EmbeddedPlayer，Plyr 实际全屏容器 .video-stage；只缩放 video，不缩放控制栏与字幕层。
- 原有 fitFrame 保持源比例；缩放和 contain/cover 显示在固定 viewport 内，不修改后端、RIFE、编码尺寸。
- 当前临时文件系统未找到先前记录中的四角色实体，使用项目 var/player-framing 保存本轮四角色与原字节快照。

画面调节完成：EmbeddedPlayer.initFraming 控制 video.style.transform/objectFit，不缩放控件/字幕；50–200%，完整显示/铺满裁剪，重置，Escape/外部点击关闭，全屏保留。320px面板可越过视频框向上展开，视频wrapper独立裁剪。实际像素验证蓝色侧部→200%红色中心。生产HTML+真实Plyr、合成视频流验证，无pageerror；未声称手机真机验证。

电脑端音量条隐藏已完成：Plyr保留mute/volume配置以不触碰行为，仅桌面CSS隐藏音量range并收缩容器；全屏同样生效。1440/1920实际Plyr静音→恢复声音验证通过。

## --olink 弹幕
- 用户传参为 --olink=window.location.href，当前parse_mpv_command忽略该字段；新增存储后按集获取弹幕。网页地址未必返回XML/JSON，明确报错并提供本地文件导入，不虚构站点抓取适配。
- 使用现有EmbeddedPlayer.position()整集时间；canvas独立于video transform但跟随Plyr横屏容器；避免后端转码改动。

DOCTYPE兼容：普通<!DOCTYPE i>及带SYSTEM/PUBLIC的元数据可安全丢弃，不访问外部DTD；拒绝带内部子集或自定义实体。<!DOCTYPE html>通常是原网页，不能凭此推导弹幕接口，现报具体错误。未提供用户实际olink，真实站点尚未验证。

解析接口实测返回danmuku（不是danmaku/comments）；数组第0项为秒数、第1项right/top/bottom、第2项#RRGGBB、第4项文本。提供的腾讯示例danum=1271，过滤空文本/空行得到1260有效条。请求必须对整个olink编码，包括&、?、#和中文。默认后端将影片页URL发送用户指定第三方弹幕解析服务，前端仍只请求本地/api/danmaku。

图片弹幕暂按纯文本展示：过滤<img ...>标签而不渲染远程表情图片；保留其余文字，不改变普通小于号表达式。用户可见问题来自Canvas按文本绘制接口HTML片段，而非DOM注入执行。

弹幕设置改为B站风格紧凑深色浮层，三列标签/滑条/即时数值，蓝色进度与小圆柄、顶部显示开关、导入/重载收在折叠区域。新默认opacity100，保留本机用户设置；fontSize12–36 step1、area25–100 step25。320/390/1440截图已查看，设置/键盘/刷新记忆/全屏通过。

按要求删除本地导入和手动重载入口与实现，设置面板仅保留开关/不透明度/字号/区域与状态；网络加载失败可通过关闭再开启弹幕触发原有重试，不新增重载按钮。

用户要求是显示真实图片表情，不是过滤。前端Canvas支持安全图文runs，后端不得删img；只提取HTTP(S)图片URL，忽略其他属性。真实腾讯图片表情已在浏览器绘制并查看截图。跨域图片绘到canvas可能使其不可读取像素，但不影响播放显示；可控同源PNG用于像素自动断言。

新接口返回顶层数组而非{danmuku:[...]}；仅换URL会静默丢掉所有行，已同时补齐行数组解析。新接口腾讯示例30228条且1462条含图片，完整图片标记继续交给安全Canvas混排。

## 弹幕性能热点
- 自写Canvas当前每帧strokeText+fillText，image.onload触发全片rebuild；ResizeObserver、timeupdate与player.paint重复sync导致清屏/取消重建RAF。
- 参考主项目weizhenye/Danmaku src/engine/canvas.js：setup创建每条离屏画布、render仅drawImage、remove释放画布。采用独立实现的有界LRU缓存，保留自有整集时钟/安全表情/设置；不整库替换以免破坏HLS起点。
- 参考来源：https://github.com/weizhenye/Danmaku / https://raw.githubusercontent.com/weizhenye/Danmaku/master/src/engine/canvas.js（未复制源码）。

## 成熟引擎落地
- 已引入npm danmaku@2.0.10 Canvas专用包，SHA512核对npm元数据，MIT许可和NOTICE随源码；仅对自定义canvas添加CSS尺寸metadata兼容补丁（danmaku-hidpi.patch），使DPR2碰撞尺寸正确且文字不降清晰度。
- Danmaku引擎负责调度/活动队列/碰撞/RAF/二分seek；项目用EventTarget整集时钟适配HLS state.start，暂停/缓冲/倍速/跳转/页面隐藏同步，不绑定HLS局部currentTime。
- 只有进入显示窗口才栅格化图文精灵；192个/16MiB精灵LRU，128张/24MiB解码图片LRU，图像.onload只重画关联精灵，不整集rebuild；框架轮询/事件无变化不新增RAF，尺寸/滑条布局单帧合并。
- 显示密度上限随区域/字号变化（每个持续时间窗口最多96条），极端密集跳过部分展示，comments原始数据保留。不能以“全量都显示”的口径宣传压力结果。
- 最终同机器Chromium1440x900/120帧：3万条ready131.6→27.3ms，5万条101.8→24.8ms；文字描边10054→25/10228→5。callback p95未普遍下降，3万样本0.2→0.4ms，5万0.2→0.2ms；不声称所有设备帧率提升或绝不卡顿。

## 2026-10-18 四分之一区域成批出弹
根因：rebuildNow滚动窗口准入先耗完maximum，再等约6秒窗口释放；区域缩小时尤其明显。修复：容量2的令牌桶按(maximum-1)/duration连续补充，同时保留原硬窗口上限；不重排或延迟源时间，不改碰撞/渲染引擎。两条稀疏同刻图文可保留；密集源依旧会抽样。回归同时覆盖25/50/75/100区域、5万同刻突发、稀疏双条、时间戳不变与懒精灵。浏览器用每RAF媒体时钟前进0.1秒采样24秒，非目标机器真实FPS测量。CONTINUOUS_FLOW.json含前后回滚实测。

## 2026-10-18 跨区域轨道不足与全屏高度
- [complete] 同输入复现半屏/3/4/全屏轨道仅到168/210/252px；全屏区域被硬减52px。修复rebuildNow：实际高度按25/50/75/100%，轨道高度含6px精灵padding；最多64条均匀采样宽度估算滚动入口周转，固定弹幕按全时长占轨，保留连续令牌与96活动上限。
- [complete] 540px播放器密集5万条、实际滑条25→50→75→100→25且同一loaded source：修改区域135/270/405/540px，轨道底部126/252/378/504px，四档均无整秒出弹空档；基线和隔离回滚恢复135/270/405/488px、底部84/168/210/252px，哈希一致。
- [complete] 手机/桌面视口、窗口/全屏、12/24/36px字号共48组geometry检查全通过（基线/回滚33/48）；119项Python、五组Node、生产API/视频暂停缓冲跳转切集/全屏、DPR1/2图片、设置持久化均通过。累计patch逐字节重建，新增--areas-before和历史默认回滚验证，原四角色重开。抽样高密度依旧不是全量显示。
固定三条/轨/6秒没有考虑短弹幕入口早已可复用，令牌平滑后较早复用上方轨道，导致下半区域长期空置。改用有界宽度采样估算入口周转后，密集场景四档轨道占用均约93.3%（余量不足一完整42px轨道），不为强行填满而改变源时间或另写碰撞引擎。尺寸/准入单位测试覆盖短播放器和各字号，宽度样本≤64，按源样本的固定/滚动占轨比例计算预算。

## 2026-10-18 实际全屏铺满而非画布100%
- [complete] 原实现画布540px但中密度2条/秒弹幕仅y0/42；重现并修复实际位置：laneOrder(top/bottom/逐步填中间)+轮换可用轨道，使用成熟引擎willCollide原谓词判断碰撞，全阻塞时跳过而非重叠，固定顶部/底部模式保留。
- [complete] 同3000条/2条每秒、24秒模拟媒体时钟、25→50→75→100→25：BASELINE/ROLLBACK全屏最高只到84px，MODIFIED轨道底到540px且12行遍布全屏，顶部中部底部实际像素非零；四档分别到135/270/405/540px。源时间不改、不复制弹幕。
- [complete] 独立8秒真实墙钟播放验证：整个播放器上中下和左中右均有真实文字像素、>=10条不同轨道、laneSkipped0；spread-realtime.png人工查看确认。5万密集输入四档出弹持续，48组字号/窗口/全屏几何检查全通过；119项Python+五组Node、生产播放器跳转/切集/暂停、DPR1/2表情、设置持久化通过。
- [complete] 保存原始哈希，--spread-before隔离恢复相同旧行为；默认历史回滚恢复BASELINE，累计patch重建一致；上游bundle依次应用HiDPI和lane patch与当前vendor字节一致。原四角色更新重开。
仅将逻辑轨道静态映射到全高度仍不足：中密度时上游反复复用前两条逻辑轨道，中部仍空。最终改为按上游碰撞谓词从轮换轨道找可用位置，遍及所有轨道；没有改写动画时钟和图片渲染。vendor新增可选laneLayout(channel,comment,height,willCollide)钩子以及null跳过分支；补丁与NOTICE明确标记本地改动，不声称完全原版引擎。

## 2026-10-18 区域必须影响数量
- [complete] 参考已下载的B站开源DanmakuFlameMaster(DanmakuContext同屏数量/最大行数/防重叠)及DPlayer(高度限制可用轨道)，不声称复刻B站网页精确比例。本项目明确按1/4、1/2、3/4、全屏联动数量。
- [complete] rebuildNow生成稳定的全屏限流序列，再以[0,2,1,3]四相嵌套抽样，四档25/50/75/100%，原时间戳和源数据保持；同屏预算从全屏上限按区域缩放，96饱和场景分别24/48/72/96，避免短字号/大播放器各档共用96上限。
- [complete] 同3000条/2条每秒、同一loaded source和真实滑条25→50→75→100→75→50→25：24秒内实际出弹12/24/36/48/36/24/12（基线/回滚每档48）；同播放位置24秒实际同屏3/6/9/12/9/6/3（基线/回滚每档12），保留源3000条、碰撞跳过0。
- [complete] 5万密集输入四档均无整秒空档、48组字号/窗口/全屏区域检查通过；119项Python+五组Node、实际API/视频暂停缓冲/跳转/切集/全屏、DPR1/2表情和设置持久化回归通过。新增--density-before，隔离回滚原哈希/行为和历史默认回滚验证、累计patch重建一致，原四角色更新重开。
单纯按区域计算轨道容量仅在源足够密时改变数量；普通源2条/秒所有档位都能塞下，所以原先每档48条、同屏12条。改为稳定全屏准入序列的嵌套子集，扩大区域只增加可见候选，不会换一批无关弹幕；半屏隔条选取避免成对集中。保留稀疏输入的自然间隔，不凭空补弹幕。

## 2026-10-18 采用引擎自带显示区域
用户指出自定义数量过稀。下载并校验npm danmu.js1.2.1（registry integrity SHA512），其原生配置area:{start,end,lines}在channel._initChannels按容器高度计算轨道，Main.readData逐250ms取未attached弹幕，Channel.addBullet按轨道碰撞拒绝/回池；setArea触发原生resizeSync。当前adapter只把后端normalize记录转换为原生start/duration/mode/lazy element，所有50000源条目交给引擎，不再先抽样或按面积删除。容器100%高度，area仅由引擎内部限制轨道。原生浏览器实测540px、字号24、25/50/75/100有3/6/9/12轨道，active同轨道数，图片像素和安全属性通过。旧Danmaku2.0.10 Canvas和本地HiDPI/lane补丁移除。
## 2026-10-18 用户反馈“没有弹幕”
- 根因一：为避免浏览器缓存而加的 `?v=...` 查询串未被本地探针服务器剥离，导致两个脚本404；生产页面已保留版本化地址，探针已正确处理查询串。
- 根因二：原生danmu.js调度依赖媒体时钟的秒值和readyState；适配器曾只提供空对象。现补齐EventTarget、currentTime、playbackRate、duration、readyState=4，并用同输入浏览器回归确认可出弹。
- 证据：`var/player-framing/visible-finalize.stdout` 中 MODIFIED NATIVE E2E 与 ROLLBACK NATIVE E2E 均 exit 0，三种mode均有bullet，图片像素red=1102，区域轨道为3/6/9/12。

## 2026-10-18 用户反馈“没有弹幕”
- 根因一：为避免浏览器缓存而加的版本查询串未被本地探针服务器剥离，导致两个脚本404；生产页面已保留版本化地址，探针已正确处理查询串。
- 根因二：原生danmu.js调度依赖媒体时钟的秒值和readyState；适配器曾只提供空对象。现补齐EventTarget、currentTime、playbackRate、duration、readyState=4，并用同输入浏览器回归确认可出弹。
- 证据：`var/player-framing/visible-finalize.stdout` 中 MODIFIED NATIVE E2E 与 ROLLBACK NATIVE E2E 均 exit 0，三种mode均有bullet，图片像素red=1102，区域轨道为3/6/9/12。

## 无弹幕再次排查
- 当前已包含EventTarget时钟和版本化脚本；不重复声称此前修复已解决本次问题。现有native-probe在accept前直接设置enabled，未覆盖API异步加载和hidden容器启动顺序。保存当前源快照var/player-framing/no-lines-before。

## 确定复现：reduced-motion使原生弹幕瞬间出屏
- web/styles.css全局prefers-reduced-motion下所有元素transition:none!important覆盖原生danmu.js内联transform/visibility动画。HLS132秒起播、600条相同输入、Chromium reduced_motion=reduce，BASELINE 12次visible全部0（DOM3到31），没有JS错误；正常模式可见。
- 最小修复为*:not(.danmaku-sprite)，保留UI减少动画、显式弹幕开关、引擎原生区域/碰撞逻辑；styles.css脚本缓存版本更新，添加Node静态回归。

## 无弹幕修复验收
- 同600条+真实HLS132秒起播，正常模式三版均12/12采样可见；reduce模式BASELINE0/12/0白色屏幕像素，MODIFIED12/12/12409像素（scroll/top/bottom均见），ROLLBACK0/12/0像素。UI临时元素transitionDuration仍0s；未探测用户设备设置，不断言这一定是用户设备触发原因。
- CSS改为*:not(.danmaku-sprite)，没有更改原生引擎、区域、密度、时钟、数据源或弹幕开关。styles.css添加?v=20261018-danmaku-motion。
- 完成119项Python、五组Node以及DPR1/2图片、暂停、倍速、缓冲、跳转、全屏、可见性、旧响应隔离回归。
- 累计patch首次因原vendor无末尾换行，marker前漏换行而重建失败；保留exit1和哈希证据，修正生成器后逐字节一致，vendor未修改。

## 播放器衔接整理：已确认的重复逻辑
- 当前rebuildNow每次区域/字号/resize都对整集map并updateComments；随后sync又clear、map克隆、updateComments。seek及ratechange也重建全量池。
- 已读本地原生源码：stop/start通过Channel.reset复位原池attached_；clear会删除main.data。应保留原池，使用原生stop/start复位，不为seek调用clear/updateComments。
- ratechange只需要原生setPlayRate，不是seek；相同geometry的ResizeObserver无需清屏；图片完成只重绘canvas，不该启动暂停的引擎。预览RAF在恢复播放前应取消，避免旧回调暂停新播放。

## 衔接整理首轮验收
- 同5万条/3次相同geometry rebuild/5次区域/4次seek/3次rate：BASELINE updateComments27，source.map10，rate后原5节点保留0；MODIFIED updateComments1，source.map1，原5节点保留5，相同geometry保留layout/节点，seek原池元素===layout元素。
- 拆分replaceComments/rebuildNow/playbackState/flush/paintDirtyImages/cancelLoad/releaseImages；源数据不携带attached_，原生池只初始化一次，区域字号设置不改时间。
- 首轮native-e2e与减少动画双模式真实HLS/像素可见性均通过。扩充Node真实原型fake-RAF测试覆盖50k池、geometry缓存、字体/宽度/DPR失效、暂停图片、预览恢复播放、hidden空闲、换集、异步旧响应/JSON/超时/重试清理。

## 播放器衔接整理最终结果
- 三方相同输入（50000条/3次同尺寸通知/5次区域/4次seek/3次rate）：BASELINE全量提交27、源转换10、倍速原节点0/5；MODIFIED1、1、5/5；ROLLBACK27、10、0/5。原生池和源条目三版均50000，非删弹幕换指标，不声称FPS提升。
- 所有13条回归命令exit0：119项Python、五组Node（新增source/cache/clock/loading断言）、JS语法、native E2E DPR1/2、原生5万条四档区域、真实HLS正常/reduce像素可见性、衔接计数、diff check。正常/reduce均12/12可见，三模式齐全。
- 本轮原始三文件快照哈希未动；隔离回滚还原同哈希及旧计数。累计DIFF_FILE.patch逐字节重建、历史默认回滚验证通过；本地原生vendor与upstream字节相同。原四角色均重开，工作区保持优化版。

## 2026-10-18 本地第一集绑定 Bilibili ep733316（完成）
- 当前本地文件 source 保持不变，仅 olink 绑定指定链接；分集 API 确认为凡人风起天南1重制版，cid=1022370693。
- 第三方解析返回0条；新增 Bilibili bangumi ep 精确分集解析及有界 deflate/gzip 解压，真实 XML 返回3600条（不保证全量历史）。
- 同输入 fixture BASELINE 0 → MODIFIED 1 → ROLLBACK 0，exit0，回滚哈希一致；真实网络3600条。Python和Node回归与新增压缩/超限/错误分集测试通过。
- 复用 var/player-framing 四角色，累计补丁本轮文件重建一致，ROLLBACK.sh --bilibili-before 可恢复本轮代码和playlist；localhost:10000不可达，未验证正在播放的浏览器显示。

## 2026-10-18 无自带弹幕时自动匹配 Bilibili（进行中）
- [pending] 解析本地标题/文件名中的片名、集数、季数；通过 Bilibili 综合搜索匹配官方番剧/影视分集，拒绝歧义和不相干结果。
- [pending] 后端仅在缺少 olink 时自动寻找，缓存结果；前端无 olink 也触发加载，切集隔离和来源状态保留。
- [pending] 同输入基线/修改/回滚、标题/集数/季数/网络异常/已有来源测试、真实第1/2集验证，复用四角色。
- 接口探测：search/type 对部分分类返回 HTTP 412；search/all/v2 成功返回凡人修仙传官方番剧及 ep733316/733317。不尝试绕过平台拒绝。

## 2026-10-18 无自带弹幕时自动匹配 Bilibili（完成）
- [complete] 新增 rife/danmaku_match.py：清洗文件名/标题，识别中文集数/季数、SxxExx/EPxx/发布式编号；仅精确匹配官方番剧/影视标题及唯一分集，拒绝剪辑、特别篇、不同配音、跨季和多版本歧义。仅发送片名与季数，不发送本地目录或 URL token。
- [complete] /api/danmaku 仅对已存在的播放条目工作；olink 优先，缺少时自动寻找。前端 setItem/load/enabled 不再以 olink 为前置条件，显示自动匹配来源/失败/无匹配，切集取消旧响应，关闭弹幕时不主动搜索。
- [complete] 有界24MiB/32项缓存、同请求并发合并、成功10分钟/无匹配2分钟/网络错误1分钟缓存；不修改用户播放列表或本地视频。
- [complete] 同请求 BASELINE 缺少olink报错 → MODIFIED 自动ep733317 → ROLLBACK 原报错，exit0且回滚哈希一致；独立恢复后工作区保持修改版。保留上一轮B站直连获取逻辑不变。
- [complete] 真实无olink输入凡人1/2、芙莉莲2分别命中ep733316/733317/779776，各3600条；当前播放列表已由用户切到本地第2集、olink为空，临时实际HTTP路由返回200/3600条，无需绑定链接。
- [complete] 136项Python、五组Node、浏览器第一集→第二集→无匹配可见流、原生DPR1/2均通过；累计补丁重建精确一致，四角色已重开。
- [complete] 记录并修正SP01识别测试失败、diff生成的历史CRLF规范化错误、新增CRLF行的whitespace检查、zsh只读status包装器错误。最终全部检查exit0；未重启用户正在播放的进程，需一次性重启WebUI并刷新页面加载新逻辑。
- 四角色：/mnt/game/rife/var/player-framing/{MODIFIED_FILE,DIFF_FILE.patch,VERIFICATION.txt,ROLLBACK.sh}；本轮回滚模式 --auto-bilibili-before，检查记录 auto-bilibili/。

## 2026-10-19 弹幕设置手动指定 Bilibili 分集（进行中）
- [pending] 为当前播放条目增加独立 danmaku_url 覆盖字段与严格分集链接验证；保存只影响弹幕，不改播放源/会话/自带olink，清空恢复原优先级。
- [pending] 弹幕面板增加URL输入、使用链接/恢复默认，保存后加载，保留切集/异步隔离与键盘行为。
- [pending] 同输入三方验证、真实示例ep3854813、持久化/非法URL/无串集/恢复默认测试，复用四角色并重开。

## 2026-10-19 弹幕设置手动指定 Bilibili 分集（完成）
- [complete] 新增 PlaylistItem.danmaku_url 持久化字段、Playlist.set_danmaku_source 与 POST /api/danmaku/source；严格只接受 Bilibili bangumi/play/ep 正整数链接，分享参数清理，手动优先于自带olink，再自动匹配。清空只移除该集覆盖，不改原olink/视频路径/播放会话。
- [complete] 弹幕设置新增“手动指定本集弹幕”输入、“使用链接”“恢复默认”，Enter可提交，使用链接自动开启弹幕，重复同链接可重试，切集/旧响应隔离；保存加入宿主API的有序mutation队列，防旧轮询回写。
- [complete] 同输入 BASELINE保存404/无持久化/自动弹幕 → MODIFIED保存200/持久化ep3854813/手动弹幕 → ROLLBACK完全恢复基线；各exit0，所有原始文件哈希一致，新测试文件移除。原工作区保持修改版，累计补丁重建精确一致。
- [complete] 146项Python、五组Node、真实浏览器表单/重新打开/恢复自带与自动/非法域名/移动布局/生产app轮询、自动匹配回归和原生DPR1/2全部通过。
- [complete] 真实例子ep3854813返回3600条；API标注为第189集“慕兰之战13”。未替用户把这个例子绑定到当前视频，测试保存均在临时playlist。
- [complete] 修正同mtime挂载文件系统的刷新测试失败（保存前锁内读取最新列表并保留全局错误）；隔离来源设置的400/500错误，避免generic send_json污染播放器全局错误；浏览器纯宿主测试中的空播放器遮罩由测试CSS隐藏后通过。失败来源、字面输出与exit均保留在VERIFICATION。
- [complete] 复用并重开四角色 /mnt/game/rife/var/player-framing/{MODIFIED_FILE,DIFF_FILE.patch,VERIFICATION.txt,ROLLBACK.sh}；本轮恢复参数 --manual-bilibili-before；补充记录 manual-bilibili/。一次性重启WebUI并强制刷新以加载后端与新UI，未主动打断用户播放。

## 2026-10-19 弹幕速度调节栏（进行中）
- [pending] 新增0.5～2.0倍、步进0.1、默认1.0的弹幕速度slider；旧设置兼容、持久化和可访问数值提示。
- [pending] 复用原生setPlayRate，弹幕速度与视频倍速相乘，仅改变原生运动，不改视频倍速/源时间戳/布局/弹幕池。
- [pending] 同输入三方验证、真实浏览器运动速度/暂停/倍速/刷新/恢复/已有弹幕来源回归，复用四角色。

## 2026-10-19 弹幕速度调节栏（完成）
- [complete] web/danmaku.js 新增 settings.speed/defaults.speed/normalizeSpeed、0.5～2.0倍步进0.1滑杆、1.0默认值、实时倍速输出/aria提示、localStorage持久化和旧配置兼容；index缓存版本更新。
- [complete] playbackState.rate 使用视频倍速×弹幕速度，复用原生setPlayRate；不改视频倍速/时间戳/弹幕池/布局/活动节点，暂停时仍暂停，倍速生效后无需重载源。
- [complete] 同输入视频1.5x、滑杆0.5/1/2：BASELINE无滑杆且原生只1.5；MODIFIED有滑杆且原生0.75/1.5/3；ROLLBACK恢复无滑杆/1.5，stdout一致、原始哈希一致；修改版保留，累计补丁精确重建通过。
- [complete] 真实浏览器原生scroll速度约73.09/146.18/292.36像素每秒，对应0.5/1/2，活动节点/源池/layout保持；2x弹幕与1.5x视频合成3x；暂停调速不恢复播放；键盘0.8x刷新后保留；320/390宽度无横向溢出，截图已检查。
- [complete] 146项Python、五组Node、独立速度/自动匹配/手动链接浏览器、原生DPR1/2全部exit0。探针缺失cancelAnimationFrame与Playwright对output误用input_value两项工具错误已记录并修正，不改产品绕过。
- [complete] 四角色复用且已重开 /mnt/game/rife/var/player-framing/{MODIFIED_FILE,DIFF_FILE.patch,VERIFICATION.txt,ROLLBACK.sh}；回滚参数 --danmaku-speed-before，补充记录 danmaku-speed/。纯前端变更，刷新页面即可，无需重启后端；未打断用户播放或修改播放列表。

## 2026-10-19 补帧时间轴重构
- [in_progress] 集中 FPS/start/duration/帧数/GOP/音频字幕偏移；保留末帧余量与未知时长策略。
- 基线 python3 -m unittest discover -s tests -q：146项通过；复用 var/player-framing 四角色，补充记录 timeline/。

### 补帧时间轴重构完成
- [complete] 新增冻结 Timeline/build_timeline；main 解析一次并传给 run_pipeline、decoder、RIFE env、encoder，统一音频/字幕/GOP/帧数的时基。
- [complete] 保留原浮点帧预算/减一帧/未知时长20亿帧/网络和本地seek位置；新增拒绝负值和非有限时间。
- [complete] BASELINE146/MODIFIED155/ROLLBACK146/DEPLOYED155项通过；1152组相同输入命令及RIFE环境逐字相同，摘要93d81a5a95d6dbc4fa11ae469cb55bbb8addeac0d93f7bcf2bc63c4f4407e92e；原字节哈希恢复及patch重建通过。
- [complete] 延续 var/player-framing 四角色；补充 timeline/refactor.patch/checks.txt/probe.py；回滚 ROLLBACK.sh TARGET_COPY --timeline-before。
- 工具错误：隔离副本首次缺web/run.py导致失败，补齐后通过；从项目根运行新增测试误导入旧模块，切换正确cwd后通过。未做Windows NVIDIA实播/吞吐测试，无性能提升声明。

## 2026-10-19 三进程生命周期重构
- [in_progress] 锁定 rife/stream.py::run_pipeline / stop_process；统一监测、退出记录、逆序清理、超时kill。保留时间轴、WebUI接口、HLS路径和编码配置。
- 基线155项Python测试通过；复用var/player-framing四角色，新增pipeline-lifecycle补充记录。

### 三进程生命周期重构完成
- [complete] PipelineRunner统一启动、每50ms监测三个直接子进程、逆序回收、关闭父进程管道；PipelineResult记录退出原因/各阶段退出码/主动停止/清理错误；run_pipeline保持int接口。
- [complete] 观察到的非零退出不再被encoder0掩盖；主动停止产生的负退出码单独记录；自然VSPipe预算结束和encoder提前成功均覆盖。Ctrl-C返回130；POSIX SIGTERM返回143并恢复handler；Windows维持现有WebUI taskkill路径，未实测Windows停止。
- [complete] BASELINE155/MODIFIED173/ROLLBACK155/DEPLOYED173项通过；相同输入decoder7+vspipe0+encoder0由误报0改为7，回滚恢复0及原始哈希。真实子进程启动/故障/中断/强杀/资源回收测试通过；清理失败不覆盖既有阶段故障。
- [complete] 上轮1152组命令/环境保持逐字相同；单轮补丁与时间轴+本轮补丁组合均逐字节重建。复用var/player-framing四角色并重开；补充pipeline-lifecycle/，回滚模式 --pipeline-before。
- 工具错误：首次在隔离cwd使用重复相对前缀写测试导致no such file，shell继续执行原155项；改为正确相对路径并set -e，新增测试实际运行通过。未变更WebUI/HLS路径、模型、画质、编码参数，未重启服务或中断实际播放；未做Windows NVIDIA实播。

### 三进程重构最终边界修正与验收
- [complete] 初版173项通过后，连续写入producer复现正常VSPipe EOF引发decoder Broken pipe被误报1；补充有界16KiB解码诊断tee，仅在明确Broken pipe且VSPipe成功结束时标记decoder_pipe_end，不吞没真实decoder1/7失败。
- [complete] 最终BASELINE155/MODIFIED176/ROLLBACK155/DEPLOYED176均通过；追加真实断管、诊断跨chunk/内存上限/日志保真测试。176项取代中间173项作为最终验收。
- [complete] 原1152组命令与RIFE环境仍逐字相同；时间轴补丁+本轮初版补丁+boundary-fix.patch组合精确重建；最终副本经原ROLLBACK.sh --pipeline-before恢复基线哈希和155项测试。
- [complete] 四角色仍位于var/player-framing并已重开；完整字面结果追加VERIFICATION.txt，新增边界证据和最终复验保留pipeline-lifecycle/。

## 播放会话隔离 session_id
- [in_progress] 锁定 stream/webui/paths；新会话ID、跨进程归属锁、原子状态、旧worker清理/状态/日志隔离；保留HLS地址/API既有字段/编码配置。
- 复用var/player-framing四角色；补充session-isolation/。已有stream.cpython-312.pyc为用户预存变动，不覆盖。

### 播放会话隔离完成
- [complete] 新增rife/sessions.py：UUID所有权、OS进程锁和原子JSON；starting/probing/running/finished/failed/stopped；状态含session_id/item_id/pid。锁外等待进程，保留HLS路径。
- [complete] WebUI播放/切集/后端seek分配新ID，worker只附着指定ID；旧状态/日志/退出通知/清理不能影响后继；异常退出兜底；已结束PID不再被误杀；旧进程退出超时拒绝复用共享HLS。
- [complete] 保留API原playback_id数值与路由；追加session_id，前端seek携带两种令牌，播放器与清单缓存使用UUID并兼容旧后端；相同时间戳重播也可隔离，缓冲内本地seek仍不启动新会话。
- [complete] BASELINE176/MODIFIED207/ROLLBACK176/DEPLOYED207项Python，三方及部署5组Node均通过；相同旧会话输入由污染状态/清除后继资源/旧错误改为拒绝且保留后继字节；原哈希恢复/补丁精确重建通过。新增31项覆盖真实子进程连续播放seek、延迟清理、进程锁、原子JSON、PID复用、退出/启动/探测边界与退休超时。
- [complete] 原1152组命令和RIFE环境逐字相同；沿用var/player-framing四角色并重开，补充session-isolation/；回滚ROLLBACK.sh TARGET_COPY --session-before。预存stream.cpython-312.pyc变动保持不动。
- 工具/测试错误及修正：首次脚本相对路径重复、混合换行定位失败、缺失状态路径误建锁、JS抽取越界、PID探活mock不完整均已改命令/实现/测试并重跑，证据留checks与VERIFICATION。
- 未重启WebUI或中断实际播放；需用户方便时重启WebUI并刷新页面生效。未实测本轮Windows进程锁与NVIDIA实播。

## RawFramePipe 本轮（2026-10-19）
- [complete] 保存原字节/基线，独立单读线程+借用保护+帧数与字节预算，接入VSPipe，覆盖乱序、短读、异常、取消；原参数不变。
- [complete] 原生patch、完整回归、同输入三方验证、回滚哈希、部署、重开四角色。
- 已确认原脚本持锁readinto、裸memoryview出锁、预取异常吞掉；当前git工作树干净。

- RawFramePipe：隔离副本首批31测试通过；生产回调借用区间覆盖整个Y/U/V拷贝。默认双限为ahead+keep帧与256MiB，预算不足1帧明确报错。有限frame_count后不再额外读取。生产stdin用POSIX readiness/Windows PeekNamedPipe适配避免阻塞读无法取消；不关闭外部句柄，通用不可取消source的close明确返回未join。Windows分支仍需真机验证。

- 评审修正：Windows PeekNamedPipe+定时等待可能给高吞吐小块写入增加延迟，因此最终取消热路径Peek轮询，采用原raw.readinto + CancelIoEx，并在close有界join期间重试，覆盖cancel与read启动竞态；错误1168视为本轮无挂起IO，其他OS错误不吞。Microsoft官方同步IO取消说明已核对；实际Windows仍未执行。POSIX真实OS管道取消通过。

### RawFramePipe 完成（2026-10-19）
- [complete] 仅修改vs/rife_stream.vpy、新增rife/frame_pipe.py和tests/test_frame_pipe.py。单读线程、IO不占状态锁、borrow贯穿三平面复制、pending与pin保护、缓存/借用/读入/池共享帧数+字节双限，默认256MiB；可RIFE_PIPE_CACHE_MIB覆盖。不等于总RSS/GPU预算。
- [complete] EOF/半帧/读取异常/启动失败/取消显式区分，后台失败唤醒全部等待者，已淘汰旧帧明确报错；frame_count到达停止额外读取。POSIX readiness与Windows rawread+CancelIoEx取消，close有界join且重试竞态；通用不可取消源超时返回false，不虚报线程结束。
- [complete] 相同12帧4byte输入借用0后读8：原版0变6，新版保持0；BASELINE207/MODIFIED248/ROLLBACK207/DEPLOYED248 Python，全部5组Node通过；补丁精确重建、回滚原字节及哈希一致，新文件移除。41新增测试+最终10x41压力回归，1152组旧命令/RIFE环境摘要保持93d81a5a95d6dbc4fa11ae469cb55bbb8addeac0d93f7bcf2bc63c4f4407e92e。
- [complete] 沿用var/player-framing四角色并重开；补充raw-frame-pipe/。独立副本回滚命令ROLLBACK.sh TARGET_COPY --raw-pipe-before。最终重新应用已验证修改到工作区，未改其他源码或字节码。
- 未运行Windows真机/VSPipe/NVIDIA，Windows政策仅mock；真实OS pipe及完整vpy mock插件图已测。未声称提高多少FPS或降低延迟；未知时长尾帧策略未改，未重启或中断真实播放。新worker下次加载脚本生效。

- 最终审计：原env_value/copy_plane/fill_yuv420 AST相同，engine_dir起至Anime4K/RIFE/set_output脚本尾部逐字相同；3个源码/测试路径与改后副本/patch重建/四角色一致。协议CLI子进程生成的原本干净paths.cpython-313.pyc已从HEAD复原，未动其他字节码。所有阶段完成。

## 并发解耦与性能统计（2026-10-19）
- [in_progress] 保留当前RawFramePipe改动为本轮基线；新增--vs-requests/--vs-threads覆盖，默认关闭的--perf-report；采集帧等待/读取/复制/缓存预算、整体FPS与首次完整HLS可用时间，输出不混淆推理耗时。
- [pending] 固定片段基准入口与说明；默认命令/1152矩阵不变；三方测试+原生patch+回滚+部署+重开原四角色。
- 状态：本轮前已有三个文档/vpy改动和frame_pipe.py/test_frame_pipe.py新文件，全部保留，不以HEAD替代本轮基线。

- 并发覆盖/opt-in统计已在副本落地，既有248项Python通过；无新参数不增加VS环境键或FFmpeg progress参数。性能报告独立run_id/scratch且拒绝覆盖；原始帧累计墙钟不冒充GPU推理，原始缓冲预算不冒充RSS/显存。基准工具先检测活动会话，首轮/重复标签不保证冷缓存。检查tools不存在的ls退出2，已创建副本tools目录，未影响产品。
