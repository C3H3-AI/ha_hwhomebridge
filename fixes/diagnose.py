#!/usr/bin/env python3
"""hwhomebridge 诊断工具

在 HA 容器内运行，检查安装状态并给出修复建议。

用法：
    docker exec homeassistant python3 /path/to/diagnose.py
"""

import ctypes
import json
import os
import platform
import subprocess
import sys

CC = '/config/custom_components/hwhomebridge'
BRIDGE = f'{CC}/hilink_bridge'
SO = f'{BRIDGE}/libhilink_bridge.so'
CFGDIR = f'{BRIDGE}/config'
HCFG = f'{CFGDIR}/hilink.cfg'

SYMBOLS = ['HILINK_GetDevStatus', 'HILINK_SetAutoAc', 'RegHomeAssistantPyCB',
           'RegPINQueryCallback', 'exit_brg', 'main']

results = []


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f'{type(e).__name__}: {e}'
    results.append((name, ok, detail))
    icon = '✅' if ok else '❌'
    print(f'{icon} {name}')
    if detail:
        for line in str(detail).splitlines():
            print(f'     {line}')
    return ok


def c_arch():
    if not os.path.isfile(SO):
        return False, f'文件不存在: {SO}'
    d = open(SO, 'rb').read(20)
    if d[:4] != b'\x7fELF':
        return False, '不是 ELF 文件'
    mach = int.from_bytes(d[18:20], 'little')
    names = {0x3e: 'x86_64', 0xb7: 'aarch64', 0x28: 'arm'}
    so_arch = names.get(mach, hex(mach))
    host_arch = platform.machine()
    size = os.path.getsize(SO) / 1024 / 1024
    detail = f'.so={so_arch} ({size:.1f}MB)  本机={host_arch}'
    ok = (mach == 0xb7 and host_arch in ('aarch64', 'arm64')) or \
         (mach == 0x3e and host_arch in ('x86_64', 'amd64'))
    if not ok:
        detail += '\n⚠️  架构不匹配'
    return ok, detail


def libc_type():
    musl = os.path.exists('/lib/ld-musl-aarch64.so.1') or \
           os.path.exists('/lib/ld-musl-x86_64.so.1')
    glibc = os.path.exists('/lib/ld-linux-aarch64.so.1') or \
            os.path.exists('/lib64/ld-linux-x86-64.so.2')
    kind = 'Alpine/musl' if musl else ('glibc' if glibc else '未知')
    detail = f'系统: {kind}'
    if musl:
        detail += '\n⚠️  musl 系统需要 gcompat 才能加载 glibc 的 .so'
    return True, detail


def gcompat():
    try:
        r = subprocess.run(['apk', 'info', '-e', 'gcompat'],
                           capture_output=True, timeout=10)
        ok = r.returncode == 0
        detail = '已安装' if ok else '未安装 → 运行: apk add --no-cache gcompat'
        return ok, detail
    except FileNotFoundError:
        return True, '非 Alpine 系统，跳过'
    except Exception as e:
        return False, str(e)


def load_so():
    if not os.path.isfile(SO):
        return False, '文件不存在'
    try:
        lib = ctypes.CDLL(SO, mode=ctypes.RTLD_GLOBAL)
    except Exception as e:
        return False, f'{e}\n提示：musl 系统需安装 gcompat'
    missing = [s for s in SYMBOLS
               if not hasattr(lib, s)]
    if missing:
        return False, f'符号缺失: {missing}'
    return True, f'{len(SYMBOLS)} 个符号全部可解析'


def cfg_dir():
    if os.path.isdir(CFGDIR):
        files = sorted(os.listdir(CFGDIR))
        return True, f'存在，含 {len(files)} 个文件: {", ".join(files[:6])}...'
    return False, f'不存在 → 运行: mkdir -p {CFGDIR}'


def hilink_cfg():
    if not os.path.isfile(HCFG):
        return False, f'不存在 → 需放置华为云地址表 {HCFG}'
    data = open(HCFG, 'rb').read()
    size = len(data)
    try:
        import hashlib
        sha = hashlib.sha256(data).hexdigest()
    except Exception:
        sha = '?'
    detail = f'{size} bytes, sha256={sha[:12]}...'
    needs = '5ef8d8b8b'
    if sha.startswith(needs):
        detail += f'\n✅ 与库期望的 {needs}* 匹配！'
    else:
        detail += (f'\n⚠️  库期望 {needs}*，当前是 {sha[:9]}*')
        detail += '\n    → 版本校验可能失败，需华为下发的正确版本'
    return True, detail


def cfg_files():
    """检查 C 库是否已生成配置文件（说明 kv 初始化成功）"""
    if not os.path.isdir(CFGDIR):
        return False, '配置目录不存在'
    expected = ['bridge.cfg', 'pidMap.cfg', 'hilink_cert.cfg', 'subDevInfo.cfg']
    found = [f for f in expected if os.path.exists(os.path.join(CFGDIR, f))]
    if len(found) == len(expected):
        sizes = {f: os.path.getsize(os.path.join(CFGDIR, f)) for f in found}
        nonzero = [f for f, s in sizes.items() if s > 0]
        detail = f'{len(found)}/{len(expected)} 已生成'
        if nonzero:
            detail += f'\n   非空文件: {nonzero}（说明 C 库已写入数据）'
        else:
            detail += '\n   全部为空（可能是刚创建，或校验失败后未写入）'
        return True, detail
    return False, f'仅 {len(found)}/{len(expected)}: {found}'


def main():
    print('=' * 64)
    print('hwhomebridge 诊断')
    print('=' * 64)
    print()

    check('集成目录', lambda: (os.path.isdir(CC), CC))
    check('系统 / libc 类型', libc_type)
    check('.so 架构', c_arch)
    check('gcompat（glibc 兼容层）', gcompat)
    check('.so 加载与符号', load_so)
    check('配置目录', cfg_dir)
    check('hilink.cfg', hilink_cfg)
    check('C 库生成的配置文件', cfg_files)

    print()
    print('=' * 64)
    failed = [n for n, ok, _ in results if not ok]
    if not failed:
        print('✅ 全部检查通过')
        print()
        print('后续：重启 HA → 添加集成 → 获取 PIN → 华为智慧生活 App 绑定')
    else:
        print(f'❌ {len(failed)} 项需要处理：')
        for n in failed:
            print(f'   - {n}')
        print()
        if 'gcompat（glibc 兼容层）' in failed:
            print('修复: apk add --no-cache gcompat')
        if '配置目录' in failed:
            print(f'修复: mkdir -p {CFGDIR}')
        if 'hilink.cfg' in failed:
            print('修复: 见 README「卡点三」，放入华为云地址表')
    print('=' * 64)
    return 0 if not failed else 1


if __name__ == '__main__':
    sys.exit(main())
