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

### 共用底座
- 统一账号绑定与登录态、统一浏览器 Profile、统一拟人限速器与批次冷却
- 队列持久化，中断可续跑；统一软件内日志面板、CSV 导出、定时巡检与 Webhook 通知
- 总览仪表盘汇总各模块待办数量

## 技术栈
- 后端：Python · FastAPI · SQLite（标准库 sqlite3，无 ORM）· Playwright · requests
- 前端：Vue 3 · Vite
- 打包：PyInstaller（one-folder），浏览器复用本机 Edge / Chrome，不打包浏览器二进制

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

## 打包 exe（Windows）
```bash
cd frontend && npm install && npm run build
cd ..
python -m PyInstaller SteamToolbox.spec --distpath packaged --workpath build --noconfirm
```
产物：`packaged/SteamToolbox/SteamToolbox.exe`，双击启动本地后端并自动打开页面；无控制台窗口，运行日志在页面底部「运行日志」面板查看。

## 目录与隐私
- `data/`：本机数据库、浏览器登录 Profile、截图，**仅本地保存，已被 .gitignore 排除，不进仓库、不进打包附件**
- 源码不包含任何 API Key、SteamID、Cookie、日志或测试数据
- API Key 不下发到前端页面；所有对外请求只走 Steam 官方域名（与可选的通知 Webhook）

## 免责声明
本工具为个人学习与效率辅助项目，与 Valve / Steam 官方无关。批量订阅、领取与移除授权等操作请遵守 Steam 服务条款，风险自负。
