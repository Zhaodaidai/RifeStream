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

播放器内部上一集/下一集完成：顺序上一集-播放/暂停-下一集，首末/单集/空列表按后端可用性隐藏，移除外部三按钮。Chromium实际WebUI/API/Playlist.select+H264/AAC HLS验证切集、停止后重启、本地暂停、失败恢复、键盘/焦点、真全屏与移动触摸横屏；320–1920px无溢出/进度>=35px、1080p/4K比例回归通过，101项Python/两组Node通过。初始98项后收到独立设置更新，合并基线99项（保留Anime4K），修改101，隔离回滚99；四角色原路径保留，--episode-nav-before只回滚本轮六个文件，默认完整历史回滚。

WebUI继续优化完成：确认清空（媒体数/不删源文件/取消/Escape/失败重试/忙碌防重），连接状态提示与单飞重试/恢复焦点，手机列表触控和具名删除标签。浏览器真实临时Playlist/API验证，非用户列表；播放/HLS整集进度、320–1920、1080p/4K及横屏全屏回归通过。基线101项→修改103项→隔离回滚101项，两组Node各状态通过，历史70项默认回滚、补丁重建/重新应用哈希一致。四角色原路径保留，本轮回滚选项--polish-before；10000静态资源哈希匹配，前端刷新生效。

## 2026-10-18 播放器画面占比调节完成
- 仅修改web/player.js、web/styles.css，新增tests/test_web_framing.js；后端/播放列表/转码尺寸不变。
- BASELINE无画面调节；MODIFIED支持50/100/150/200%、contain/cover、重置、全屏、320/390/768/1280/1920布局与Escape焦点恢复；ROLLBACK无调节且源文件哈希恢复一致，三次probe退出0。
- 103项Python、三组Node与JS语法通过；补丁重建所有字节一致，四角色重开，当前工作区保持修改版。
- 四角色位于/mnt/game/rife/var/player-framing/{MODIFIED_FILE,DIFF_FILE.patch,VERIFICATION.txt,ROLLBACK.sh}；截图framing-mobile.png、framing-preview.png已查看。原记录中临时四角色实体未找到，本轮按项目var持久保存。
- 修复测试暴露的设置按钮嵌套insertBefore错误及组件硬编码颜色；像素探针PIL缺失改浏览器PNG解码，无新增依赖。

## 2026-10-18 电脑端只保留静音按钮
- 仅在 web/styles.css 增加 min-width:861px 的音量容器收缩与 input[data-plyr="volume"] 隐藏；player.js原字节不变。
- Chromium同probe：BASELINE1440/1920及全屏有音量条；MODIFIED无音量条；ROLLBACK恢复原显示，三者点击均可静音/取消静音，退出码0。900/390原行为不变，无pageerror。
- 103项Python、三组Node、累计补丁重建通过，恢复styles哈希等于本轮前快照。原四角色更新并重开；ROLLBACK.sh新增 TARGET_COPY --volume-before，仅恢复本轮前styles。

## 2026-10-18 --olink弹幕与DOCTYPE修复
- 新增MpvRequest.olink/PlaylistItem.olink，/api/danmaku按影片读取XML/JSON，大小/条数/超时约束，加载错误不污染播放状态。独立canvas、开关、透明度、字号、区域、本地XML/JSON导入及本机持久化。整集时间驱动、跳转/切集清理、旧请求隔离；桌面全屏和320–1920布局验证。
- 用户报DOCTYPE错误后，修复parse_danmaku/DanmakuOverlay.parse对普通i声明的误拦：丢弃普通/SYSTEM/PUBLIC声明，不读取外部DTD；内部实体继续拒绝。HTML doctype明确提示是网页，未取得真实用户地址，不声称已适配对应站点。
- BASELINE普通声明报旧DTD错误；MODIFIED前后端均解析1条，外部DTD请求0、自定义实体拒绝；ROLLBACK恢复旧错误且两个源文件哈希一致。全量116项Python、四组Node、完整生产app+API弹幕E2E、画面像素/全屏/移动布局及音量回归均通过。
- 前次最终回归的通用.framing-reset探针撞上弹幕重载按钮，exit1保留账本；改#videoFraming .framing-reset后exit0，无生产改动。
- 原四角色更新且重开，累计补丁字节重建一致；ROLLBACK.sh新增--danmaku-before与--doctype-before，旧默认恢复也已验证。当前工作区保留修改版。

## lirose_tv 弹幕解析接口适配
- 已按用户指定接口修改rife/danmaku.py load_danmaku，使用完整URL编码将olink作为url单参数发送；保留已完整解析链接不二次包装。
- 真实示例JSON含code/name/danum/danmuku/from/author；不把code=23误判失败，按danmuku行[time,direction,hexcolor,unused,text,...]解析，空行/空文本跳过。
- 用户腾讯示例真实HTTP200、151726字节、1260条有效弹幕，两次load_danmaku真实请求成功。未发送用户本地账号/cookie，未改用户播放列表。
- 同fixture BASELINE直接请求olink并报缺comments数组；MODIFIED正确封装参数并解析1260条；ROLLBACK恢复原错误且哈希一致。117项Python、四组Node、独立overlay浏览器回归通过；累计补丁重建字节一致，同四角色更新重开。新增ROLLBACK.sh --resolver-before。

## 弹幕img源码外露修复
- 原因是第三方弹幕文本中含HTML表情标签，Canvas fillText按字面绘制，不是HTML被执行。现rife/danmaku.py normalize及web/danmaku.js normalize过滤img，识别引号内的>，混合文字保留，纯图片记录跳过；不使用innerHTML，不请求图片地址。
- 同四条输入：BASELINE暴露img/src；MODIFIED仅剩“二刷”“正常中文 1 < 2”“好看”；ROLLBACK恢复原输出，四个文件哈希等于img-before。118项Python、四组Node、生产app+Canvas/API端到端、实时解析接口通过，补丁重建字节一致。
- 原四角色更新且重开；ROLLBACK.sh新增--img-before。当前源码保持修复版。刷新前端并重启后端后重载本集弹幕。

## 弹幕设置界面滑条完成
- web/danmaku.js defaults.opacity=100，旧保存值保留；fontSize/area由select改range、实时input更新绘制、数值和aria-valuetext；web/styles.css面板三列、蓝色进度条、开关、折叠来源工具。
- 同probe：BASELINE75%/字号区域下拉；MODIFIED100%/三滑条，字号27→键盘28、65%与3/4屏刷新保持；ROLLBACK75%/下拉且三文件哈希恢复。修改版工作区保留。
- 118项Python/四组Node通过，独立设置浏览器320/390/1440、生产弹幕API/渲染/全屏/320–1920回归通过，无pageerror。累计补丁重建一致、原四角色重开，新增ROLLBACK.sh --settings-before。

## 移除本地导入与重新加载本集弹幕
- web/danmaku.js移除来源details、file input、reload按钮及处理函数/setItem文件清理；删除styles中对应样式，前后端不再提示导入。超时提示改为关闭后开启弹幕重试。
- 同probe BASELINE存在file/reload/source各1；MODIFIED各0且自动加载/滑条通过；ROLLBACK恢复各1、四文件哈希与before一致。118项Python、四组Node和真实生产app/API/Canvas/切集/全屏回归通过，无pageerror，累计patch字节重建一致。
- 同四角色重开，ROLLBACK.sh新增--remove-import-before；当前源码保持移除版。

## 图片表情真正显示（纠正之前过滤方案）
- rife/danmaku.py normalize保留原img及纯图片记录，传输上限4096字符避免长URL被截断。web/danmaku.js normalize不再过滤；parts只识别src/alt并校验HTTP(S)，不插入HTML，不应用style/onerror/srcset。
- Canvas图文runs统一测宽、保留位置/颜色/字号/区域/透明度/跳转行为，图片高为字号1.2倍且宽高比受限；缓存最多256，10s超时占位，切集清理请求回调和缓存。
- 同输入BASELINE不发图片请求且纯图丢失；MODIFIED实际PNG1次请求/两次绘制/2451红色像素、纯图和混排显示、脚本对话框0；ROLLBACK恢复无图且4文件哈希一致。118项Python/四组Node及生产app/API/Canvas/全屏/小屏/旧请求回归通过，累计补丁重建一致。
- 真实接口中腾讯puui表情地址在Chromium成功加载和drawImage，emoji-live.png已人工查看，非占位。emoji-verified.png为可控红色PNG混排像素验证。未声称所有远程站点图片都可访问。
- 原四角色更新重开；ROLLBACK.sh新增--emoji-before；当前保留正确图片渲染，不恢复已删除本地导入和重新加载按钮。需要重启WebUI+强制刷新，已加载旧弹幕需关闭再开启弹幕以重新取得保留标记的数据。

## 切换 dmku.byteamone.cn
- rife/danmaku.py DANMAKU_RESOLVER与already_resolved改用户指定接口，parse_danmaku对顶层数组行按[秒,方向,颜色,占位,文本]解析，原danmuku对象兼容保留。完整URL编码不变，图片标记保留。
- 实际请求腾讯示例HTTP成功，3572004字节；load_danmaku解析30228条，其中1462条图片标记。119项Python/四组Node/浏览器回归通过。
- BASELINE旧解析地址+新响应0条；MODIFIED新地址30228/1462；ROLLBACK相同输入恢复旧地址0条，两个文件原始哈希一致；累计补丁重建字节一致，原四角色更新重开。新增--byteam-before回滚模式。当前源码保持新接口。

## 2026-10-18 成熟弹幕引擎升级完成
- 用户授权引擎替换后，安装本地vendor Danmaku2.0.10 Canvas版，无运行时CDN依赖。npm tarball SHA512 verified；保留MIT，附自定义canvas HiDPI补丁与NOTICE。
- web/danmaku.js不再自行逐帧遍历/布局全片，改成熟引擎调度碰撞和活动精灵，项目保留安全图片提取、olink加载/设置、整集时钟适配。图文离屏精灵/图片缓存有界；后台暂停；RAF合并/快速状态跳过；图像解码不重排整集；密度过高丢弃部分展示但不删source。
- 同输入压力基线/修改/回滚均exit0：3万ready131.6→27.3→134.4ms；5万101.8→24.8→79.1ms；120帧stroke10054→25、10228→5；最终缓存3.08MiB，预算16MiB。源输入有3万/5万条，合成高密度场景仅准入9000，必须连同此差异解释，不把改进完全归因引擎。
- 功能：119项Python、五组Node、JS语法；生产app真实API/视频暂停缓冲/倍速/跳转/切集/旧响应拒绝、320–1920布局/全屏、设置持久化、画面像素、静音音量回归通过；DPR1/2图片PNG像素1102/4446、真实腾讯表情渲染、脚本事件0、隐藏页停绘与缓存切集清理通过。
- 参考读取遇到GitHub API403，raw猜测路径404，zsh循环变量path遮蔽PATH导致curl127，分别改用npm元数据+包、修正变量rel；finalizer脚本引号语法exit1修正后完整重跑。旧fillText探针不适配离屏缓存，改验证引擎running canvas+主画布像素；首次paused120秒恰好触发引擎严格小于时间边界，适配时钟加1微秒，恢复暂停预览；不把这些失败算功能通过。
- 原四角色更新重开，累计patch重建/隔离--perf-before恢复原始哈希/旧默认rollback恢复BASELINE均通过。工作区保留成熟引擎版本，未动已有用户源码/字节码改动。PERFORMANCE.json保存完整literal结果；线上目标机GPU实际帧率未测试。

## 2026-10-18 四分之一区域弹幕波次修复
- [complete] DanmakuOverlay.rebuildNow 改双令牌连续补充+原窗口硬上限，保留原时间戳、四分之一高度和图片表情。
- [complete] 同输入5万条/100条每秒、540px高/135px区域、24秒模拟媒体时钟：BASELINE/ROLLBACK最大准入间隔5.92秒且20个整秒无新弹幕；MODIFIED0.75秒、空档0。旧36条/新33条准入（前24秒），仍有密度抽样，不声称全量显示。
- [complete] 119项Python、五组Node、生产播放器暂停/缓冲/跳转/切集/全屏，DPR1/2图片像素与设置持久化通过；回滚哈希、累计patch逐字节重建、默认历史回滚与原四角色重开通过。

## 2026-10-18 全显示区域联动修复
- [complete] 同输入复现半屏/3/4/全屏轨道仅到168/210/252px；全屏区域被硬减52px。修复rebuildNow：实际高度按25/50/75/100%，轨道高度含6px精灵padding；最多64条均匀采样宽度估算滚动入口周转，固定弹幕按全时长占轨，保留连续令牌与96活动上限。
- [complete] 540px播放器密集5万条、实际滑条25→50→75→100→25且同一loaded source：修改区域135/270/405/540px，轨道底部126/252/378/504px，四档均无整秒出弹空档；基线和隔离回滚恢复135/270/405/488px、底部84/168/210/252px，哈希一致。
- [complete] 手机/桌面视口、窗口/全屏、12/24/36px字号共48组geometry检查全通过（基线/回滚33/48）；119项Python、五组Node、生产API/视频暂停缓冲跳转切集/全屏、DPR1/2图片、设置持久化均通过。累计patch逐字节重建，新增--areas-before和历史默认回滚验证，原四角色重开。抽样高密度依旧不是全量显示。

## 2026-10-18 全屏弹幕实际铺屏
- [complete] 原实现画布540px但中密度2条/秒弹幕仅y0/42；重现并修复实际位置：laneOrder(top/bottom/逐步填中间)+轮换可用轨道，使用成熟引擎willCollide原谓词判断碰撞，全阻塞时跳过而非重叠，固定顶部/底部模式保留。
- [complete] 同3000条/2条每秒、24秒模拟媒体时钟、25→50→75→100→25：BASELINE/ROLLBACK全屏最高只到84px，MODIFIED轨道底到540px且12行遍布全屏，顶部中部底部实际像素非零；四档分别到135/270/405/540px。源时间不改、不复制弹幕。
- [complete] 独立8秒真实墙钟播放验证：整个播放器上中下和左中右均有真实文字像素、>=10条不同轨道、laneSkipped0；spread-realtime.png人工查看确认。5万密集输入四档出弹持续，48组字号/窗口/全屏几何检查全通过；119项Python+五组Node、生产播放器跳转/切集/暂停、DPR1/2表情、设置持久化通过。
- [complete] 保存原始哈希，--spread-before隔离恢复相同旧行为；默认历史回滚恢复BASELINE，累计patch重建一致；上游bundle依次应用HiDPI和lane patch与当前vendor字节一致。原四角色更新重开。

## 2026-10-18 区域与弹幕量联动
- [complete] 参考已下载的B站开源DanmakuFlameMaster(DanmakuContext同屏数量/最大行数/防重叠)及DPlayer(高度限制可用轨道)，不声称复刻B站网页精确比例。本项目明确按1/4、1/2、3/4、全屏联动数量。
- [complete] rebuildNow生成稳定的全屏限流序列，再以[0,2,1,3]四相嵌套抽样，四档25/50/75/100%，原时间戳和源数据保持；同屏预算从全屏上限按区域缩放，96饱和场景分别24/48/72/96，避免短字号/大播放器各档共用96上限。
- [complete] 同3000条/2条每秒、同一loaded source和真实滑条25→50→75→100→75→50→25：24秒内实际出弹12/24/36/48/36/24/12（基线/回滚每档48）；同播放位置24秒实际同屏3/6/9/12/9/6/3（基线/回滚每档12），保留源3000条、碰撞跳过0。
- [complete] 5万密集输入四档均无整秒空档、48组字号/窗口/全屏区域检查通过；119项Python+五组Node、实际API/视频暂停缓冲/跳转/切集/全屏、DPR1/2表情和设置持久化回归通过。新增--density-before，隔离回滚原哈希/行为和历史默认回滚验证、累计patch重建一致，原四角色更新重开。

## 2026-10-18 使用引擎原生区域，不再自定义抽样/轨道
- [complete] 切换本地vendored danmu.js1.2.1，使用原生area{start:0,end:x}、setArea、channelSize、overlap:false、lazy bulletCreateEl；移除自定义laneLayout/laneOrder、抽样、双令牌、96上限和旧canvas/轨道补丁，源50000条全部交给引擎。
- [complete] 同输入滑条25/50/75/100/75/50/25：原生轨道3/6/9/12/9/6/3，source/candidates/admitted均50000、skipped0、host始终覆盖播放器；基线/回滚恢复旧自定义1/1/2/2准入行为和旧vendor哈希。
- [complete] 原生引擎图片表情DPR1/2、字号/透明度、实际area、暂停缓冲/倍速/跳转/全屏/隐藏页/切集旧响应，119项Python、五组Node、设置/画面/音量回归通过；npm tarball integrity验证，vendor字节等于上游，无本地引擎补丁；累计patch、隔离--native-before和历史默认回滚、原四角色重开通过。

## 2026-10-18 原生引擎缓存及时钟适配修复
- [in progress] 同真实播放器回归可出弹；为新DanmuJs和adapter增加版本化脚本地址，恢复EventTarget媒体时钟/readyState/duration，执行同输入基线/修改/回滚与强制新脚本浏览器验证。

## 2026-10-18 原生引擎缓存及时钟适配修复
- [complete] 用户反馈“没有弹幕”后，定位并修复两处回归：带版本查询串的脚本在探针服务器未剥离查询导致旧脚本404；DanmuJs适配器缺少媒体时钟字段导致调度器无法按播放时间取弹幕。生产页面现使用版本化danmu.js/danmaku.js地址，clock恢复EventTarget、currentTime（秒）、playbackRate、duration、readyState=4。
- [complete] 同一输入的修改版真实Chromium E2E通过：顶部/底部/滚动三种弹幕、图片表情、暂停/缓冲/倍速/跳转/全屏/隐藏页/切集；区域25/50/75/100%对应原生轨道3/6/9/12（540px视口），50000条全部交给引擎，skipped=0。
- [complete] Python、现有Node回归、语法检查、独立回滚浏览器E2E均通过；原始快照哈希保持，累计DIFF_FILE.patch可重建当前文件（供应商bundle无末尾换行，验证时记录并去除GNU patch人为补入的单字节换行），四个角色已重新打开。

## 2026-10-18 原生引擎缓存及时钟适配修复
- [complete] 用户反馈“没有弹幕”后，定位并修复两处回归：带版本查询串的脚本在探针服务器未剥离查询导致旧脚本404；DanmuJs适配器缺少媒体时钟字段导致调度器无法按播放时间取弹幕。生产页面现使用版本化danmu.js/danmaku.js地址，clock恢复EventTarget、currentTime（秒）、playbackRate、duration、readyState=4。
- [complete] 同一输入的修改版真实Chromium E2E通过：顶部/底部/滚动三种弹幕、图片表情、暂停/缓冲/倍速/跳转/全屏/隐藏页/切集；区域25/50/75/100%对应原生轨道3/6/9/12（540px视口），50000条全部交给引擎，skipped=0。
- [complete] Python、现有Node回归、语法检查、独立回滚浏览器E2E均通过；原始快照哈希保持，累计DIFF_FILE.patch可重建当前文件（供应商bundle无末尾换行，验证时记录并规范GNU patch人为生成的EOF标记），四个角色已重新打开。

## 2026-10-18 一行弹幕都没显示（重新复现）
- 当前源码快照已保存。真实视频+真实开关+API异步输入600条的基础路径可见，12次采样均有弹幕；不能把此前clock/cache修复作为本次结论。继续检查实际30228条数据、起播132秒和HLS重载路径。
- 探索命令中的缺失文件/目录（es、e2e-probe.py、production-e2e.py、DIFF_FILE目录）均为错误假设，已改用已存在source map/native-e2e及原DIFF_FILE.patch。

## 2026-10-18 本轮修复完成：弹幕CSS动画被无障碍样式禁用
- 已应用web/styles.css媒体查询选择器最小修复、index样式地址版本和Node回归；没有重做原生引擎或密度逻辑。真实HLS/异步加载、600条同输入、正常与reduce双模式三方对照已执行。
- BASELINE/ROLLBACK reduce模式12次采样均0可见，实际屏幕文字像素0；MODIFIED12次全部可见，三模式齐全，12409屏幕文字像素；UI减少动画保留。人工查看no-lines-MODIFIED_FILE-reduce.png确认文字确实在屏幕。
- 119项Python、五组Node、native-e2e DPR1/2全部exit0。还原四文件SHA等于本轮before；历史默认ROLLBACK保持可用；累计DIFF_FILE.patch重新应用字节一致。
- 错误记录：真实数据图片导致离屏canvas tainted读取失败exit1，改用页面截图解码像素；累计patch首轮marker换行错误exit1，独立resume脚本完成未完成步骤并验证exit0。保留工具输出和VERIFICATION记录。
- 复用并重开 /mnt/game/rife/var/player-framing/{MODIFIED_FILE,DIFF_FILE.patch,VERIFICATION.txt,ROLLBACK.sh}。当前工作区与修改副本一致，before保持原始字节。
