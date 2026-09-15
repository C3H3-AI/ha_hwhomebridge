#!/bin/sh
# hwhomebridge 安装脚本
#
# 在 Home Assistant OS (Alpine + musl) 上安装 hwhomebridge 的完整流程。
# 解决两个已知卡点：
#   1. glibc / musl 不兼容  → 装 gcompat
#   2. 配置目录缺失          → mkdir
#
# 用法（在 HA 容器内执行）：
#   docker exec homeassistant sh /path/to/install.sh

set -e

CC="/config/custom_components/hwhomebridge"
BRIDGE="$CC/hilink_bridge"
CFGDIR="$BRIDGE/config"

echo "=== 1. 检查集成目录 ==="
if [ ! -d "$CC" ]; then
    echo "❌ 集成未安装: $CC"
    echo "   请先下载原项目到该目录"
    exit 1
fi
echo "✅ 集成目录存在"

echo
echo "=== 2. 检查 .so 架构 ==="
SO="$BRIDGE/libhilink_bridge.so"
if [ ! -f "$SO" ]; then
    echo "❌ 缺少 $SO"
    exit 1
fi
python3 - <<'PY'
import sys
p = '/config/custom_components/hwhomebridge/hilink_bridge/libhilink_bridge.so'
try:
    d = open(p, 'rb').read(20)
    if d[:4] != b'\x7fELF':
        print('  ❌ 不是 ELF 文件'); sys.exit(1)
    mach = int.from_bytes(d[18:20], 'little')
    names = {0x3e: 'x86_64', 0xb7: 'aarch64'}
    name = names.get(mach, hex(mach))
    print(f'  .so 架构: {name}')
    import platform
    host = platform.machine()
    print(f'  本机架构: {host}')
    if (mach == 0xb7 and host not in ('aarch64', 'arm64')) or \
       (mach == 0x3e and host not in ('x86_64', 'amd64')):
        print('  ⚠️  架构不匹配，可能无法加载')
except Exception as e:
    print('  ❌ 读取失败:', e); sys.exit(1)
PY

echo
echo "=== 3. 安装 gcompat（解决 glibc/musl 不兼容）==="
if apk info -e gcompat >/dev/null 2>&1; then
    echo "✅ gcompat 已安装"
else
    echo "  正在安装 gcompat ..."
    apk add --no-cache gcompat
fi

echo
echo "=== 4. 验证 .so 可加载 ==="
python3 - <<'PY'
import ctypes, sys
p = '/config/custom_components/hwhomebridge/hilink_bridge/libhilink_bridge.so'
SYMS = ['HILINK_GetDevStatus', 'HILINK_SetAutoAc', 'RegHomeAssistantPyCB',
        'RegPINQueryCallback', 'exit_brg', 'main']
try:
    lib = ctypes.CDLL(p, mode=ctypes.RTLD_GLOBAL)
except Exception as e:
    print('  ❌ 加载失败:', e)
    print('  提示：确认已安装 gcompat')
    sys.exit(1)
print('  ✅ .so 加载成功')
missing = []
for s in SYMS:
    try:
        getattr(lib, s)
    except AttributeError:
        missing.append(s)
if missing:
    print('  ⚠️  以下符号缺失:', missing)
    sys.exit(1)
print(f'  ✅ {len(SYMS)} 个符号全部可解析')
PY

echo
echo "=== 5. 创建配置目录 ==="
if [ -d "$CFGDIR" ]; then
    echo "✅ 配置目录已存在"
else
    mkdir -p "$CFGDIR"
    chmod 755 "$CFGDIR"
    echo "✅ 已创建 $CFGDIR"
fi

echo
echo "=== 6. 放置 hilink.cfg（华为云地址表）==="
HCFG="$CFGDIR/hilink.cfg"
if [ -f "$HCFG" ]; then
    echo "✅ hilink.cfg 已存在"
else
    cat > "$HCFG" <<'CFG'
{
	"url": {
		"cloud": "iomplatform.hicloud.com",
		"hota": "update-drcn.platform.hicloud.com",
		"bi": "data.hicloud.com",
		"sntp": "0.cn.pool.ntp.org"
	}
}
CFG
    cp "$HCFG" "$CFGDIR/hilink_bak.cfg"
    echo "✅ 已写入 hilink.cfg"
    echo "   ⚠️  注意：此文件可能因版本校验不通过而无效，见 README"
fi

echo
echo "=== 安装完成 ==="
echo
echo "后续步骤："
echo "  1. 重启 Home Assistant"
echo "  2. 设置 → 设备与服务 → 添加集成 → 搜索 hwhomebridge"
echo "  3. 点击配置获取 8 位 PIN 码（有效期 5 分钟）"
echo "  4. 华为智慧生活 App → '+' → 添加设备 → HA 网关 → 输入 PIN"
echo
echo "如果日志出现以下错误，说明 URL 表校验不通过（需华为下发）："
echo "  not same, now is XXXXXXXX*, need:5ef8d8b8b*"
echo "  check urlFile integrity fail!"
