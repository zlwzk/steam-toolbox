#!/usr/bin/env bash
# macOS 构建脚本：在一台装有 macOS 的机器上从源码构建桌面版。
# 注意：PyInstaller 不支持交叉编译，Windows 上无法产出 macOS 可执行文件；
# 请在 macOS（建议 12 及以上）上运行本脚本。
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 1/5 创建虚拟环境并安装后端依赖"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "==> 2/5 构建前端"
( cd frontend && npm install && npm run build )

echo "==> 3/5 安装 Playwright Chromium（复用本机 Chrome/Edge 时可跳过此步）"
python -m playwright install chromium || true

echo "==> 4/5 PyInstaller 打包"
python -m PyInstaller SteamToolbox.spec --distpath packaged --workpath build --noconfirm --clean

echo "==> 5/5 完成"
echo "产物目录：packaged/SteamToolbox/"
echo "双击其中的可执行文件（或 .app）启动；浏览器首次登录建议保持有头模式。"
