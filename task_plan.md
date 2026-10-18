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
