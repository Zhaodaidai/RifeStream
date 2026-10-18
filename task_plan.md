# 性能优化计划

目标：在不降低输出画质的前提下，减少 RIFE 视频流水线中的重复计算、内存拷贝、阻塞和不必要 I/O，逐阶段验证。

## 阶段
- [complete] 建立架构基线，识别性能热点和画质约束
- [complete] 优化解码、缩放和 rawvideo 管道
- [complete] 优化 VapourSynth 帧缓存与 RIFE 调度
- [pending] 优化 NVENC/HLS 输出与进程 I/O
- [pending] 优化 WebUI/协议的非播放路径
- [complete] 全量测试、静态检查和回归总结

## 当前结论
- 已完成低风险优化，未改变分辨率、帧率、RIFE 模型、颜色参数或 NVENC 画质参数。
- NVENC/HLS 和 TensorRT 并发参数保留待真实 NVIDIA 环境基准后再调整。

## 画质约束
- 不降低输入分辨率和输出帧率。
- 不提高 NVENC `-cq` 数值，不改变颜色空间和色彩参数。
- 不删除 RIFE、Anime4K、字幕等处理步骤。
- 优先消除重复工作和不必要拷贝，而不是降低算法质量。

## 错误记录
| 错误 | 尝试 | 处理 |
|---|---:|---|


# 2026-10-17 Web 内置播放器
- [complete] 确认现有播放、跳转接口及 70 项测试基线
- [complete] 内置 HLS 播放、整集进度、切集及跳转会话同步
- [complete] 自动化测试、回滚验证及说明

# 2026-10-17 播放器布局调整
- [complete] 删除输入式跳转，将切集/设置移至进度上方，列表改为右侧栏
- [complete] 浏览器布局/功能回归及同一组角色补丁、回滚复验

# 添加链接弹窗
- [complete] 移除底部输入区，在列表清空旁增加添加，弹窗完成后加入列表
- [complete] 实际接口/浏览器测试、更新同一组四角色及回滚验证

## 2026-10-17 整体 UI 优化
- [x] 检查 Python HTTP 服务、原生前端、hls.js、无构建步骤和单页结构。
- [x] 基线 77 项 Python 测试、Node 播放器测试通过；备份 ui-before。
- [x] 完成统一视觉与交互反馈，保留现有 API 和播放器生命周期。
- [x] 浏览器桌面/移动/键盘/错误/真实添加接口验证。
- [x] 更新原有四角色，验证补丁与回滚，交付结果。

## PC 首屏垂直居中完成
- 仅修改 web/styles.css 桌面媒体查询：隐藏介绍/页脚，main flex 垂直居中，workspace 自适应视口高度，video-stage 弹性分配并保持视频比例；移动端保持。
- Chromium 1440×900、1920×1080、1366×768、1280×720、1024×768、861×700 无首屏滚动，播放器与列表整体在头部以下居中。移动端、HLS、切集、跳转、设置、弹窗、错误和键盘回归通过；77 项 Python 与 Node 测试通过。
- 同四角色重新打开；初始 baseline 和 rollback 未有居中机制，modified 有；补丁重建一致，回滚恢复原始哈希。历史验证保存在 VERIFICATION-before-center.txt，本轮 center-browser-output.txt。

## 引入真正的 Plyr + 少量主题适配
- [x] 基线 77 项 Python 和 Node 测试通过；plyr-before 备份和 SHA 已记录。
- [x] 下载固定 3.8.4 官方 npm 包；许可证名大小写错误（exit 1）已修正按实际 archive 名读取。
- [x] 本地 UI 资源和图标、最少主题变量适配，保留 HLS/整集跳转。
- [x] Chromium 实际 HLS 和 Plyr 控件/布局/键盘/切集回归。
- [x] 复用同四角色并验证补丁/回滚。

## 播放器内整集进度与移除外链
- [x] 锁定 web 页面/EmbeddedPlayer；备份 timeline-before；基线79项和JS通过。
- [x] 去除页面外链/复制及失效样式，整集时间轴移入 Plyr 控件内部，保留真实 seek；按追加要求采用 Plyr 原样式单行。
- [x] 实际 HLS、远端/本地 seek、拖动/键盘、全屏和移动验证。
- [x] 更新同四角色，重建补丁、隔离回滚与重开校验。

## 标题和 playerHint 位置调整
- [x] 锁定 viewer-head/nowPlaying/playerHint，基线81项和Node通过，title-before哈希备份。
- [x] 顶部只显示媒体名称，移除下方重复区域；状态放停止转码右侧。
- [x] 检查长标题、待机/切集/播放状态、窄屏和Plyr回归；同四角色重开。
- [x] 按最新要求移除 playback-controls 上下边框，320–1920px 计算样式确认均0px。

## 时间在前 + 原版 Plyr 按钮
- [x] 检查实际官网：当前为Video.js迁移页面；保持已选Plyr不迁移，恢复固定版本原版按钮样式。
- [x] 时间数字移至进度前，移除之前主题覆盖。原始native-before及83项基线已记录。
- [x] 浏览器同排/原版按钮hover/手机/全屏/跳转与同四角色复验完成；84项测试通过。

## WebUI 蓝色统一
- [x] 基线84项及Node通过，blue-before备份；仅改styles/index，Plyr原包不动。
- [x] 强调色#00b2ff、状态、主按钮/hover、开关、列表选中、focus、空态、弹窗、品牌/favicon统一蓝色。
- [x] 浏览器计算颜色、移动/桌面、回归与同四角色验证；84项通过。

## 主题统一管理
- [x] 基线84项和Node通过，备份theme-before/颜色计算快照。
- [x] theme.css集中语义变量，Plyr共享accent，styles仅布局/变量；文档和防回归测试。
- [x] 普通/hover/focus/弹窗颜色计算一致；accent联动、320–1920响应式/实际HLS/接口交互通过；85项Python和Node通过；同四角色重开、补丁重建/隔离回滚哈希一致。

## 播放链路内部衔接优化
- [x] 锁定WebUI/player/HLS；flow-before字节与85项基线及Node已记录。
- [x] 修复会话切换/旧异步回调、轮询与控制请求竞争、stub就绪误判和切片重名。
- [x] 95项Python、两组Node通过；实际多切片连续播放/暂停跳转/ENDLIST切集/快速启停/隔离HTTP回归通过。
- [x] 同四角色更新、补丁重建/隔离回滚、重开校验；历史70项原始基线/回滚哈希一致，当前95项通过。

## PC播放器上下黑边修复（手机保持原样）
- [x] 锁定video-stage/桌面flex撑高；aspect-before字节与95项基线、两组Node已备份。
- [x] 按实际视频比例适配PC区域，保持居中/短屏可用；不改移动规则，不裁切。
- [x] 实际1920x1080/3840x2160 HLS前后尺寸/截图核验；PC额外上下留边消除，390/768移动尺寸完全一致；95项Python/两组Node及实际播放/全屏/拖动/键盘/响应式通过。
- [x] 同四角色更新重开；历史70项基线/回滚哈希一致，修改95项及补丁重建一致；10000实际静态资源SHA匹配已生效。

## 手机横屏全屏
- [x] 检查真实Plyr容器/事件及95项基线，备份landscape-before。
- [x] 原生方向锁定与整套控件横向兼容，退出清理。
- [x] Chromium原生/兼容全屏，缺失/拒绝/延迟方向锁、旋转/退出/控件；1080p/4K与320–1920响应式回归；同四角色补丁重建及历史/本轮隔离回滚哈希一致。

## 2026-10-17 1080p 缩放链路修改（用户授权覆盖旧画质约束）
已完成：CUDA 缩放改 Lanczos；输入高度达到输出上限或不设高度上限时跳过 ACNet，日志与环境变量一致；低清保留手动开关及原输出尺寸。编码/RIFE不变。BASELINE95、MODIFIED96、ROLLBACK95、部署96项通过，回滚哈希一致，字节保真补丁重建一致。混合换行导致的首次补丁失败已保留并修正。四角色沿用 /tmp/rife-player-transaction/{MODIFIED_FILE,DIFF_FILE.patch,VERIFICATION.txt,ROLLBACK.sh}；本轮回滚模式 --scale-before。未实测 Windows NVIDIA GPU 的画质、吞吐及实时播放。

## 2026-10-17 移除手动 Anime4K 与往返超分
用户不要求低清升分辨率。已移除UI开关、设置字段、CLI参数、VS ACNet阶段和插件必需检查；历史设置被忽略，继承环境变量强制置0。不改720p输出尺寸，不改RIFE/NVENC，保留Lanczos缩小。BASELINE96、MODIFIED98、ROLLBACK96，Node两组/JS语法检查通过，字节保真补丁重建和回滚原始哈希一致。沿用原四角色；本轮回滚 --no-anime4k-before。未实测Windows GPU；需重启WebUI并重新开始转码。

## 播放器内上一集/下一集
- [x] 检查Plyr控制栏、现有API及初始/停止后播放入口；保存当前98项基线与源字节。
- [x] 内部上一集/播放/下一集，边界隐藏，移除外部三个按钮，保留启动/暂停/恢复。
- [x] 实际Playlist.select/API与HLS切集，首/中/末/单集/空列表，失败恢复/Enter/焦点，390触摸横屏与320–1920响应式通过；101项Python与两组Node通过；复用四角色与隔离回滚。

## 恢复 Anime4K 手动开关（当前请求）
进行中：复用移除前已确认实现，恢复UI/持久化/CLI/VS；改为纯手动控制、默认关闭，不按分辨率强制跳过；Lanczos及输出尺寸/RIFE/NVENC不变。复用原四角色，新增 manual-anime4k-before 原字节快照；不修改其他未完成任务。

恢复 Anime4K 手动开关已完成：默认关闭；开启/关闭分别控制所有输入分辨率的ACNet，不再受高度条件限制；恢复持久化、CLI和下一次播放/seek传参，720p/1080p/4K输出尺寸及Lanczos/RIFE/NVENC不变。实际本轮 BASELINE100项、MODIFIED99项、ROLLBACK100项通过（移除过时的功能删除测试并恢复/新增开关测试），两组Node与JS语法通过；Chromium以生产HTML/JS和隔离模拟API验证开/关请求及刷新回显，无pageerror。字节保真补丁重建与隔离回滚原始哈希一致。沿用四角色，回滚模式 --manual-anime4k-before。未实测Windows GPU；需重启WebUI并重新开始转码。不改同时进行的播放器导航任务。

## WebUI继续打磨
- [x] 锁定现有Plyr/列表/设置，101项基线与源文件、原有字节码改动已保存。
- [x] 原生清空确认/失败重试/事务防重；连接异常自动与手动恢复、焦点清理；小屏列表40px触控与长标题约束、具名删除标签。
- [x] Chromium真实API弹窗/取消/失败/慢请求、断网恢复、320–1920响应式；真实HLS/1080p/4K/移动横屏与PC全屏回归；101→103→101测试，补丁重建与隔离回滚哈希一致，同四角色重开。

## 2026-10-18 播放器画面缩放与裁剪
- [complete] 锁定 web/player.js EmbeddedPlayer；保留原字节快照于 var/player-framing/BASELINE。
- [complete] 实现画面面板、50–200%缩放、完整/铺满、重置与全屏适配。
- [complete] 同输入基线/修改/回滚浏览器验证，现有回归，生成并重开四角色。

## 2026-10-18 电脑端悬停竖向音量
- [in_progress] 保留volume-before原字节，在同一四角色内新增本轮快照与验证；CSS限定桌面鼠标，保留手机行为。
- [pending] 同输入浏览器基线/修改/回滚，悬停、拖动、键盘与全屏复验，重开四角色。

## 2026-10-18 电脑端音量简化
- [complete] 隐藏桌面音量条、保留静音切换；基线/修改/回滚及103项Python、三组Node通过；复用四角色。

## 2026-10-18 --olink 弹幕接入
- [complete] 保存协议olink→列表→API，安全读取XML/JSON，不把HTML网页误解析为弹幕。
- [complete] 独立canvas弹幕层与开关/透明度/字号/区域，整集同步、暂停/缓冲/跳转/切集/全屏。
- [complete] 同输入基线/修改/回滚、端到端/单元回归与原四角色更新。

## 2026-10-18 弹幕DOCTYPE错误修复
- [complete] 前后端允许普通i文档声明，移除SYSTEM/PUBLIC外部DTD引用且不请求，保留自定义实体拦截；HTML网页单独报错。
- [complete] 同输入BASELINE/MODIFIED/ROLLBACK、116项Python、四组Node、弹幕/画面/音量浏览器回归；原四角色重开。

## 2026-10-18 lirose_tv 解析接口
- [complete] olink经quote(safe="")作为解析接口url参数，不直接请求原网页；识别已有解析链接避免重复包装。
- [complete] 解析实际danmuku数组：秒数/方向/十六进制颜色/文字，跳过空记录。
- [complete] 用户腾讯示例实测1260条；基线/修改/回滚、117项Python、四组Node、隔离浏览器回归及累计补丁重建通过，原四角色重开。

## 2026-10-18 弹幕图片标签文字修复
- [complete] 后端normalize/前端normalize剔除img标签、保留附带文字、跳过纯图片弹幕，不加载图片或执行HTML。
- [complete] 同输入BASELINE/MODIFIED/ROLLBACK与哈希恢复、118项Python/四组Node、真实Canvas浏览器回归、示例接口1260条及补丁重建通过；原四角色重开。

## 2026-10-18 弹幕设置滑动条面板
- [complete] 紧凑深色面板、标签/调节栏/数值三列、顶部开关、折叠来源工具；默认不透明度100%。
- [complete] 字号12–36px连续滑动、区域1/4/半屏/3/4/全屏滑动，input实时更新、键盘调整、持久化。
- [complete] BASELINE75%+下拉→MODIFIED100%+滑条→ROLLBACK原样、哈希一致；118项Python/四组Node及生产弹幕浏览器回归，原四角色重开。

## 2026-10-18 移除弹幕本地导入/手动重载
- [complete] 移除来源折叠区、文件输入、重新加载按钮及事件/CSS/导入提示，保留olink自动加载与三滑条。
- [complete] 同输入基线/修改/回滚、118项Python、四组Node及生产浏览器回归，累计补丁重建/恢复哈希一致，原四角色重开。

## 2026-10-18 真正渲染弹幕图片表情
- [complete] 撤销前后端永久过滤：后端保留标记，前端仅安全提取HTTP(S) src/alt并Canvas图文混排，纯图片记录保留。
- [complete] 字号同步、宽高比/轨道测量、缓存/超时失败占位/切集清理，保留现有滑条与自动加载、不恢复导入/重载。
- [complete] 图片像素/混排/纯图/属性脚本不执行/全屏与真实腾讯表情加载成功；118项Python+四组Node及生产浏览器回归，BASELINE/MODIFIED/ROLLBACK哈希一致、同四角色更新重开。

## 2026-10-18 切换byteam弹幕接口
- [complete] DANMAKU_RESOLVER切换dmku.byteamone.cn，完整编码olink，防止新接口双重包装；支持顶层行数组。
- [complete] 实测30228条/1462图片；119项Python、四组Node、生产弹幕浏览器回归；BASELINE旧地址解析新数组0条→MODIFIED新地址30228→ROLLBACK恢复旧行为，哈希和累计补丁一致，原四角色重开。

## 2026-10-18 弹幕性能优化
- [complete] 保存现有实现基线，用户授权改用成熟weizhenye/Danmaku 2.0.10，完成3万/5万条浏览器压力测试。
- [complete] 引擎活动弹幕调度/二分跳转、RAF状态任务合并、有界精灵/图片缓存、图片解码只更新关联精灵、后台停绘；有界显示密度。
- [complete] 同输入基线修改回滚量化，DPR1/2图片/跳转/设置/全屏回归、119项Python+五组Node；累计patch/默认和本轮回滚验证、四角色重开。

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
- [in progress] Danmu.js1.2.1原生area/setArea、overlap:false、lazy DOM，移除原有区域重排、双令牌/96上限/25%抽样及vendor轨道补丁。保留olink/图片/字号/透明度，验证同输入基线修改回滚与native区域实际轨道数。

## 2026-10-18 原生引擎缓存及时钟适配修复
- [in progress] 同真实播放器回归可出弹；为新DanmuJs和adapter增加版本化脚本地址，恢复EventTarget媒体时钟/readyState/duration，执行同输入基线/修改/回滚与强制新脚本浏览器验证。

## 2026-10-18 反馈后修复
- [x] 修复版本化脚本缓存/查询串探针兼容。
- [x] 恢复原生引擎媒体时钟适配并验证弹幕调度。
- [x] 完成修改版、回滚版、累计补丁与四角色重开。

## 2026-10-18 反馈后修复
- [x] 修复版本化脚本缓存/查询串探针兼容。
- [x] 恢复原生引擎媒体时钟适配并验证弹幕调度。
- [x] 完成修改版、回滚版、累计补丁与四角色重开。

## 2026-10-18 再次反馈“播放器一行弹幕都没显示”
- [complete] 绑定当前播放器，真实HLS132秒起播+异步API复现；根因定位到styles.css reduced-motion全局禁用原生弹幕transition。
- [complete] 只排除.danmaku-sprite，保留UI减少动画；同输入三方验证：reduce模式0/12→12/12→0/12可见，回滚原始哈希一致；119项Python、五组Node、DPR1/2原生浏览器回归通过。原四角色重开，累计patch逐字节重建和历史默认回滚通过。

## 2026-10-18 播放器/原生弹幕引擎衔接整理
- [complete] 同输入记录重建/seek/倍速/图像更新现有行为，保留原始快照，锁定当前web/danmaku.js。
- [complete] 把源数据、布局、媒体状态、图片重绘分开；单集只转换一次，引擎原生stop/start负责复位，不在seek/倍速重建全量池。
- [complete] 同尺寸resize保留节点、源转换/全量提交10/27→1/1，倍速5/5节点保留；暂停图片/预览播放竞态/异步加载超时旧响应测试通过；119项Python+五组Node+DPR1/2浏览器+真实HLS可见性通过；三方还原27/10/0节点保留、哈希与累计patch/历史回滚验证通过，原四角色重开。

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
