"""CA 证书信任链装配。

requests 默认只使用 certifi 自带的根证书包；在使用加速器 / 代理做 HTTPS 中间人
（MITM）的环境里，其自签根证书通常已被导入 Windows 系统「受信任的根证书颁发机构」，
但不在 certifi 包内，于是会报 ``unable to get local issuer certificate``。

这里在保持证书校验开启的前提下，把 Windows 系统 Root 存储中的根证书合并进
certifi 基础包，生成一个本机 CA bundle 供 requests 使用；既认可系统已信任的根，
也不像 ``verify=False`` 那样放弃校验。非 Windows 或读取系统根失败时，回退
certifi 自带包，行为与此前一致。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import certifi

from . import config

_PS_SCRIPT = (
    "Add-Type -AssemblyName System.Security;"
    "$o=New-Object System.Collections.Generic.List[string];"
    "$stores=@("
    "[Security.Cryptography.X509Certificates.X509Store]::new('Root','LocalMachine'),"
    "[Security.Cryptography.X509Certificates.X509Store]::new('Root','CurrentUser')"
    ");"
    "foreach($s in $stores){"
    "$s.Open('ReadOnly');"
    "foreach($c in $s.Certificates){"
    "$b=[Convert]::ToBase64String($c.RawData);"
    "$o.Add('-----BEGIN CERTIFICATE-----');"
    "for($i=0;$i -lt $b.Length;$i+=64){$o.Add($b.Substring($i,[Math]::Min(64,$b.Length-$i)))};"
    "$o.Add('-----END CERTIFICATE-----')"
    "};"
    "$s.Close()"
    "};"
    "[Console]::Out.Write(($o -join \"`n\"));"
)


def _powershell_exe() -> str | None:
    """定位 Windows PowerShell 可执行文件；非 Windows 或找不到返回 None。"""
    if os.name != "nt":
        return None
    candidates = [
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        shutil.which("powershell"),
        shutil.which("pwsh"),
    ]
    for cand in candidates:
        if cand and Path(cand).exists():
            return cand
    return None


def _system_root_pem() -> str:
    """导出 Windows 系统 Root 存储（本机 + 当前用户）证书为 PEM 文本。

    任何异常（无权限、PowerShell 缺失、超时）都返回空串，由调用方回退 certifi。
    """
    ps = _powershell_exe()
    if not ps:
        return ""
    try:
        proc = subprocess.run(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _PS_SCRIPT],
            capture_output=True,
            timeout=15,
        )
        text = proc.stdout.decode("utf-8", errors="ignore")
    except (OSError, subprocess.SubprocessError):
        return ""
    return _extract_pem_blocks(text)


def _extract_pem_blocks(text: str) -> str:
    """从导出文本中抽取完整的 PEM 证书块，丢弃命令行杂项输出。"""
    blocks: list[str] = []
    current: list[str] = []
    in_block = False
    for line in text.splitlines():
        if "BEGIN CERTIFICATE" in line:
            in_block = True
            current = [line.strip()]
        elif in_block:
            current.append(line.strip())
            if "END CERTIFICATE" in line:
                blocks.append("\n".join(current))
                in_block = False
                current = []
    return "\n".join(blocks)


@lru_cache(maxsize=1)
def bundle_path() -> str:
    """返回用于 requests ``verify`` 的 CA bundle 路径。

    非 Windows / 系统根读取失败时回退 certifi 自带包；合并结果缓存到本机数据目录。
    """
    base = Path(certifi.where())
    if os.name != "nt":
        return str(base)

    sys_pem = _system_root_pem()
    if not sys_pem:
        return str(base)

    bundle = config.DATA_DIR / "ca-bundle.pem"
    try:
        base_text = base.read_text(encoding="utf-8", errors="ignore")
        bundle.write_text(base_text + "\n" + sys_pem + "\n", encoding="utf-8")
        return str(bundle)
    except OSError:
        return str(base)


def verify_argument(verify_ssl: bool) -> bool | str:
    """换算为 requests 的 ``verify`` 参数。

    显式关闭校验时返回 ``False``；开启时返回合并了系统根的 CA bundle 路径。
    """
    if not verify_ssl:
        return False
    return bundle_path()
