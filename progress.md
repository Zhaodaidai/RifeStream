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

## 添加链接弹窗完成
- 底部常驻添加区及添加并播放入口已移除。播放列表标题右侧新增添加，原生 dialog 提供批量链接输入、完成、取消、Escape；完成走 /api/items 且 play=false，防重复提交，错误保留输入。
- 77 项 Python 测试、Node 播放器测试通过；Chromium 配合真实 /api/items 验证空白/无效链接、纠错、批量添加、持久化、取消和焦点恢复，无自动转码；320/390/860/1280 弹窗适配通过。原播放/切集/跳转/设置/长列表回归通过。
- 同一组四角色已更新并重新打开，补丁重建哈希一致，回滚恢复最初基线（70 项测试），新增 dialog_probe 记录本轮修改前/修改后/回滚。

## 整体 UI 优化完成
- 修改 web/index.html、web/styles.css、web/app.js；保留原生前端、Python 服务和 hls.js，未添加项目依赖。
- 统一石墨灰/浅绿色界面、空状态引导、响应式播放器和列表、原生弹窗、焦点与 reduced-motion。
- renderState 列表签名缓存与焦点/滚动保留；performAction 错误/防重复；saveSettings 严格时间格式与保存反馈；状态按钮禁用、剪贴板反馈。
- 修改前/修改后均 77 项 Python 测试通过，Node 播放器和语法检查通过；Chromium 320–1600px、真实添加/设置/删除/清空接口、真实 HLS 解码、切集跳转停止、错误恢复和键盘通过。GPU 真转码未验证。
- 实际 python -m rife.webui --host 127.0.0.1 --port 10000 已运行，浏览器加载真实 API/静态资源 HTTP 200，无未捕获 JS 错误。
- 复用 /tmp/rife-player-transaction 四角色并重新打开；补丁重建一致；ROLLBACK 在隔离副本恢复初始基线，70 项原始测试通过、哈希相同。ui-before 原始三文件及哈希保持。
- ui_check 初始错误是浏览器 dialog 边界 Shift+Tab 假设；已改实际前后焦点遍历并通过。首次 playwright 导入失败已使用既有工具路径修正。
- 截图：ui-live.png / ui-desktop.png / ui-mobile.png / ui-dialog.png；完整命令、stdout、stderr、exit、hash 在 VERIFICATION.txt。

## PC 首屏垂直居中完成
- 仅修改 web/styles.css 桌面媒体查询：隐藏介绍/页脚，main flex 垂直居中，workspace 自适应视口高度，video-stage 弹性分配并保持视频比例；移动端保持。
- Chromium 1440×900、1920×1080、1366×768、1280×720、1024×768、861×700 无首屏滚动，播放器与列表整体在头部以下居中。移动端、HLS、切集、跳转、设置、弹窗、错误和键盘回归通过；77 项 Python 与 Node 测试通过。
- 同四角色重新打开；初始 baseline 和 rollback 未有居中机制，modified 有；补丁重建一致，回滚恢复原始哈希。历史验证保存在 VERIFICATION-before-center.txt，本轮 center-browser-output.txt。

## 真正 Plyr + 少量主题适配完成
- 固定官方 Plyr 3.8.4，JS/CSS/SVG/MIT 许可证放在 web/vendor，字节与 npm 原包一致；本地字体，图标同源，blankVideo 内嵌，无外部资源请求。
- EmbeddedPlayer.ui 创建一次，HLS 销毁/切集/seek/stop 不重建 UI；播放、音量、倍速、画中画（浏览器支持时）、全屏和中文提示；整集进度保持外部。
- 少量 CSS 变量适配浅绿强调色、深色菜单与圆角；排除旧全局按钮样式冲突；保持 PC 首屏居中和移动布局。
- 79 项 Python、Node 和语法检查通过；真实 Chromium HLS 解码 + Plyr 播放/暂停、静音/音量/方向键、倍速菜单、全屏、K 快捷键、切集、整集跳转、停止、列表滚动、添加/校验/错误/键盘回归通过。控制台和第三方资源请求均为零。画中画实际窗口与 GPU 转码未验证。
- 真实 server :10000 加载新 UI 与所有资源 HTTP 200，1440x900 首屏不滚动；截图 plyr-live.png、plyr-desktop.png、plyr-fullscreen.png、plyr-mobile.png。
- 同四角色更新并全部重新打开；补丁加入新资源和无末尾换行标记，重建哈希一致；rollback 恢复历史原始基线并通过70项测试，修改副本79项通过。原始 plyr-before 哈希未变。详细命令/输出/退出/哈希在 VERIFICATION.txt。

## 整集进度单行集成到 Plyr 完成
- 移除外部播放器地址/复制和外置整集进度；内部 HLS URL 仅供播放，接口不变。
- 用户追加要求不独立一行：使用 Plyr 官方 progress 类，插在 play 与 volume 组之间，取消换行；手机隐藏音量滑条/PiP入口，保留静音、速度和全屏。
- 全屏同样显示真实整集 currentTime+start/duration；未生成位置服务端 seek，缓冲内本地 seek；忙碌、拖动、键盘、失败恢复完善。
- 81项Python、Node、语法、diff检查通过；Chromium实际HLS、20min整集/12sec片段区分、seek600/900、全屏、失败、真实鼠标一次提交、键盘、切集、320–1920同一行布局/桌面居中、真实添加/设置/清空/删除接口回归通过。注入错误仅有预期HTTP500日志，无非预期JS异常。
- 实际服务 :10000 页面新UI通过，生产列表未修改；GPU转码未验证。
- 同四角色已更新/重开；补丁重建一致、隔离回滚原始哈希一致（70项通过），新增 timeline-before 原文件备份与79项基线记录，历史完整审计保留。
- 截图 timeline-desktop.png / timeline-mobile.png / timeline-fullscreen.png / timeline-live.png。

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

## 播放链路交付完成
- 前端请求顺序队列、单飞轮询、20秒超时/过期响应隔离；失败先同步服务端真实状态，不用旧currentState复活媒体。player按会话/epoch隔离回调，暂停意图、seek失败/停止竞态和重试位置恢复均覆盖。
- 服务端控制/快照RLock、跟踪启动子进程并等待停止；首片非空才ready；seek验证playback_id并复用已校验duration；唯一切片名和.ts no-store；按worker归属释放状态，保留正常完成的视频。
- 状态轮询只读，skip_outro用实际ENDLIST/ended切集；准备/转码/完成状态分开。技术栈不变，新增依赖0。
- 95项Python、两组Node、Chromium真实HLS跨至少3段、暂停后10:00远端跳转、真正播放ended切一次下一集、快速启停/旧seek拒绝、320–1920布局和真实API隔离回归均通过。预计注入的seek500之外无未预期控制台错误；未验证目标Windows GPU/TensorRT性能。
- 历史BASELINE70/ROLLBACK70及原始哈希一致，MODIFIED95；四角色重开，完整补丁重建哈希一致。flow-before85项快照原字节哈希保留。现有10000旧Python进程及转发8888未强制重启，部署需在目标运行环境重启WebUI/HLS；未修改用户播放列表。

## PC上下黑边修复交付
- 只改web/player.js、styles.css及两个现有测试；手机CSS/业务/API/编码/Plyr vendor保持原字节。PC工作台自然高度，fitFrame以真实videoWidth/videoHeight和可用空间计算，桌面专用--frame-width/height，不使用cover。
- 真实1080p/4K HLS浏览器解码：1440x900原上下额外留边合计93.609375px→0；1920x1080原158.109375px→0；短屏亚像素误差<0.006px。390/768全部已记录尺寸前后一致。截图已人工查看。
- 95项Python和两组Node、原实际HLS跳转/暂停/失败恢复/全屏/拖动/键盘及320–1920布局回归通过，无未预期JS错误。原控制栏探针在隐藏状态测量失败，经实际hover唤出后所有边界断言通过；移动断点瞬态溢出通过桌面作用域变量修复。
- 同四角色重开、完整补丁重建/隔离回滚哈希一致；BASELINE/ROLLBACK历史70项，当前MODIFIED95项。aspect-before原字节保留。10000服务实际player.js/styles.css与工作区SHA一致，前端刷新即可加载，无后端改动。

手机横屏全屏完成：真实Plyr改以video-stage为全屏容器，触屏请求landscape；不支持时旋转内部完整播放器，退出恢复/解锁，异步锁定竞态防护。95项Python和两组Node通过；Chromium5种全屏情形及实际HLS、PC1080p/4K回归通过。修复预览发现vendor max-width限制和fallback定位覆盖。10000静态资源哈希一致。四角色原路径保留，ROLLBACK.sh新增TARGET_COPY --landscape-before恢复本轮前字节，默认仍恢复历史原始版本；真机操作系统方向行为未实测。

## 2026-10-17 1080p 缩放链路修改（用户授权覆盖旧画质约束）
已完成：CUDA 缩放改 Lanczos；输入高度达到输出上限或不设高度上限时跳过 ACNet，日志与环境变量一致；低清保留手动开关及原输出尺寸。编码/RIFE不变。BASELINE95、MODIFIED96、ROLLBACK95、部署96项通过，回滚哈希一致，字节保真补丁重建一致。混合换行导致的首次补丁失败已保留并修正。四角色沿用 /tmp/rife-player-transaction/{MODIFIED_FILE,DIFF_FILE.patch,VERIFICATION.txt,ROLLBACK.sh}；本轮回滚模式 --scale-before。未实测 Windows NVIDIA GPU 的画质、吞吐及实时播放。

## 2026-10-17 移除手动 Anime4K 与往返超分
用户不要求低清升分辨率。已移除UI开关、设置字段、CLI参数、VS ACNet阶段和插件必需检查；历史设置被忽略，继承环境变量强制置0。不改720p输出尺寸，不改RIFE/NVENC，保留Lanczos缩小。BASELINE96、MODIFIED98、ROLLBACK96，Node两组/JS语法检查通过，字节保真补丁重建和回滚原始哈希一致。沿用原四角色；本轮回滚 --no-anime4k-before。未实测Windows GPU；需重启WebUI并重新开始转码。

## 恢复 Anime4K 手动开关（当前请求）
进行中：复用移除前已确认实现，恢复UI/持久化/CLI/VS；改为纯手动控制、默认关闭，不按分辨率强制跳过；Lanczos及输出尺寸/RIFE/NVENC不变。复用原四角色，新增 manual-anime4k-before 原字节快照；不修改其他未完成任务。

恢复 Anime4K 手动开关已完成：默认关闭；开启/关闭分别控制所有输入分辨率的ACNet，不再受高度条件限制；恢复持久化、CLI和下一次播放/seek传参，720p/1080p/4K输出尺寸及Lanczos/RIFE/NVENC不变。实际本轮 BASELINE100项、MODIFIED99项、ROLLBACK100项通过（移除过时的功能删除测试并恢复/新增开关测试），两组Node与JS语法通过；Chromium以生产HTML/JS和隔离模拟API验证开/关请求及刷新回显，无pageerror。字节保真补丁重建与隔离回滚原始哈希一致。沿用四角色，回滚模式 --manual-anime4k-before。未实测Windows GPU；需重启WebUI并重新开始转码。不改同时进行的播放器导航任务。
