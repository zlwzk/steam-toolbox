# Steam 工具助手 / Steam Toolbox

一个本地运行的 Steam 辅助工具，把**免费 DLC / 喜加一领取**、**创意工坊批量订阅 / 退订**、**库清理（按时长 / 下架筛选免费游戏）**整合在同一套账号、登录态、限速与日志体系下。**所有数据仅保存在本机，不上传、不收集、不统计。**

> 仅供个人合理使用。批量操作可能触及 Steam 服务条款，默认速率已按保守策略配置，请勿调得过快；使用后果由使用者自行承担。

## 功能一览

### 1. 免费 DLC / 喜加一领取
- 扫描库内本体携带的免费 DLC，以及商店限时免费本体（喜加一）
- 已拥有项自动过滤，不再重复显示
- 清单全选 / 单项勾选，失败项可续跑，逐项进度与截图留档，CSV 导出
- 浏览器渠道可选（默认 Edge，可切 Chrome / 自带 Chromium），登录态持久化在本机 Profile

### 2. 创意工坊批量订阅 / 退订
- 填写游戏 AppID，一键订阅 / 退订当前工坊页全部 Mod，支持自动翻页处理全部页
- 复用 Steam 原生订阅接口，拟人节奏：随机间隔 + 批次冷却 + 429/5xx 指数退避
- 暂停 / 继续 / 取消，失败项精准重试，序号范围限定，进度日志与 CSV 导出
- 登录态复用本机浏览器 Profile，不读取账号密码

### 3. 库清理
- 按时长筛选：从未玩过 / 小于 N / 大于 N / 区间，单位分钟或小时，数值可留空
- 下架 / 绝版策略：不排除 / 排除已下架 / 仅看已下架
- **类型保护**：默认排除付费购入，防止误删；收藏 / 忽略标记永不清理
- 先干跑预览出候选清单，人工勾选 + 二次确认后再登记移除；记录可导出 CSV

### 4. 更新监控
- 关注一个或多个游戏：监控本体商店信息变化（名称 / 价格 / DLC 清单 / 发行日 / 封面等指纹）与工坊最近更新、新上架 Mod
- 单独关注指定 Mod，跟踪更新时间与文件大小变化；所有更新集中在「更新动态」列表，可一键订阅
- 关键字规则：按标题 / 标签匹配（任一 / 全部），命中后可自动订阅，也可仅提醒人工处理
- 支持定时自动巡检（间隔可调）与手动立即检测；未读动态汇总到总览仪表盘
- 说明：Steam 公开接口不暴露可执行文件补丁版本号，本体以商店信息指纹变化为准，不虚构版本号

### 共用底座
- 统一账号绑定与登录态、统一浏览器 Profile、统一拟人限速器与批次冷却
- 队列持久化，中断可续跑；统一软件内日志面板、CSV 导出、定时巡检与 Webhook 通知
- 总览仪表盘汇总各模块待办数量
- **启动即检测账号状态**：未绑定 Key / SteamID 时总览给出分步引导，绑定后全局自动刷新，不重复索要信息
- **自动更新检查**：只读比对 GitHub 最新 Release，有新版本时标题栏提示并跳转下载页；网络失败静默
- **HTTPS 证书校验**：默认开启证书校验；在加速器 / 代理做 HTTPS 中间人（MITM）的环境下，会额外信任已装入 Windows 系统「受信任根」的证书，仍不放弃校验；如确需关闭，可在高级设置显式关闭证书校验
- **保守限速与退避**：盘点 / 监控走全局节奏闸门，默认低并发 + 随机间隔；429 限流与 5xx 网关错误在有限次数内指数退避重试（尊重 Retry-After，加随机抖动），连续受阻即熔断中断，不盲目刷请求
- **外部版号 + 内部构建号**：标题栏与关于卡片可见，便于排查同版号不同构建

> 功能路线图、建议加装方向与彩蛋清单见 [`docs/ROADMAP.md`](docs/ROADMAP.md)。

## 技术栈
- 后端：Python · FastAPI · SQLite（标准库 sqlite3，无 ORM）· Playwright · requests
- 前端：Vue 3 · Vite
- 打包：PyInstaller（one-file 单 EXE），浏览器复用本机 Edge / Chrome，不打包浏览器二进制

## 交付形态

| 形态 | Windows | macOS | 覆盖功能 |
|---|---|---|---|
| 桌面版 | Release 提供 Windows 单文件 exe | 需在 macOS 上从源码构建（见 `docs/BUILD.md`） | DLC/喜加一领取、工坊订阅、库清理、更新监控 |
| 浏览器插件（MV3） | ✅ Chrome / Edge | ✅ Chrome / Edge | 仅工坊批量订阅 / 退订 |

- 插件源码与安装说明：[`extension/`](extension/README.md)
- 三平台构建步骤与隐私复查清单：[`docs/BUILD.md`](docs/BUILD.md)
- macOS 说明：PyInstaller 不支持交叉编译，无法在 Windows 上产出 Mac 二进制；Mac 用户可按 `docs/BUILD.md` 本机构建，或直接使用浏览器插件版。

## 从源码运行
```bash
# 后端
pip install -r requirements.txt
python -m playwright install-deps   # 通常无需；浏览器复用本机已装的 Edge/Chrome
python -m uvicorn backend.main:app --port 8000

# 前端（开发模式，另开终端）
cd frontend
npm install
npm run dev        # Vite 5173，代理 /api 到 8000
```

生产模式：先 `cd frontend && npm run build`，再启动后端，FastAPI 会直接托管 `frontend/dist`。

## 打包（Windows / macOS）

Windows 推荐执行 `powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1`，自动先测试再构建并输出 SHA-256。
```bash
cd frontend && npm install && npm run build
cd ..
python -m PyInstaller SteamToolbox.spec --distpath packaged --workpath build --noconfirm
```
Windows 产物：`packaged/SteamToolbox.exe`；macOS 在 Mac 上执行同一 spec，详见 [`docs/BUILD.md`](docs/BUILD.md)。双击启动本地后端并自动打开页面；无控制台窗口，运行日志在页面底部「运行日志」面板查看。

## 目录与隐私
- `data/`：本机数据库、浏览器登录 Profile、截图，**仅本地保存，已被 .gitignore 排除，不进仓库、不进打包附件**
- 源码不包含任何 API Key、SteamID、Cookie、日志或测试数据
- API Key 不下发到前端页面；所有对外请求只走 Steam 官方域名（与可选的通知 Webhook）

## 免责声明
本工具为个人学习与效率辅助项目，与 Valve / Steam 官方无关。批量订阅、领取与移除授权等操作请遵守 Steam 服务条款，风险自负。
