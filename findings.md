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
