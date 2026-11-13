# 构建与发布说明

本项目提供三种交付形态：**Windows 桌面版**、**macOS 桌面版（源码构建）**、**浏览器插件（Chrome / Edge 通用）**。

## 形态与平台对照

| 形态 | Windows | macOS | 说明 |
|---|---|---|---|
| 桌面版（FastAPI + Vue + Playwright） | Windows 单文件 exe | 需在 macOS 上从源码构建 | 含 DLC/喜加一领取、工坊订阅、库清理全部模块 |
| 浏览器插件（MV3） | ✅ | ✅ | 仅工坊批量订阅/退订；Chrome 与 Edge 同一套包 |

> **关于 macOS 预编译包**：PyInstaller 不支持交叉编译——无法在 Windows 上生成 macOS 可执行文件。因此 Release 中不提供伪造的 Mac 二进制；macOS 用户请按下方步骤在本机构建，或直接使用浏览器插件版。

## 一、Windows 桌面版构建

```bash
# 1. 后端依赖
pip install -r requirements.txt

# 2. 前端构建
cd frontend
npm install
npm run build
cd ..

# 3. PyInstaller 打包（one-file）
python -m PyInstaller SteamToolbox.spec --distpath packaged --workpath build --noconfirm --clean
```
产物：`packaged/SteamToolbox.exe`，单文件可直接运行。推荐执行 `scripts/build_windows.ps1` 先测试再打包。

## 二、macOS 桌面版构建

在 macOS 机器上：

```bash
# 一键脚本
bash scripts/build_macos.sh
```

或手动执行：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
( cd frontend && npm install && npm run build )
python -m playwright install chromium   # 复用本机 Chrome/Edge 可跳过
python -m PyInstaller SteamToolbox.spec --distpath packaged --workpath build --noconfirm --clean
```

浏览器渠道：设置页可选 Edge / Chrome / 自带 Chromium。macOS 上 Playwright 同样支持 `msedge`、`chrome` 渠道；若回退到自带 Chromium，需先执行 `playwright install chromium`。

## 三、浏览器插件打包（Chrome / Edge 通用）

插件源码位于 `extension/`，Manifest V3，Chromium 内核通用。

```bash
# 将 extension 目录内容压缩为 zip（zip 内顶层为 manifest.json 所在目录）
cd extension
zip -r ../steam-toolbox-workshop-extension.zip . -x ".*"
```

加载方式见 `extension/README.md`：在 `chrome://extensions` 或 `edge://extensions` 开启开发者模式，加载已解压/解压缩的扩展。

## 四、发布前隐私复查清单

- [ ] 源码无真实 SteamID、API Key、Cookie、token、本机用户名路径
- [ ] `data/`、`*.db`、`browser_profile/`、`screenshots/`、`*.log`、`.env` 不进仓库与安装包
- [ ] 安装包 / 插件 zip 内无数据库、日志、截图、登录 Profile
- [ ] 仓库 `.gitignore` 已排除 `data/`、`node_modules/`、`frontend/dist/`、`build/`、`packaged/`、`releases/`
