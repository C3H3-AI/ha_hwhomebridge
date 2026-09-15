# 排障指南

按症状查找解决方案。

---

## 快速诊断

先跑诊断脚本，它会一次性检查所有环节：

```bash
docker exec homeassistant python3 /path/to/fixes/diagnose.py
```

输出示例（正常但 URL 表有问题的情况）：

```
✅ 集成目录                 /config/custom_components/hwhomebridge
✅ 系统 / libc 类型          Alpine/musl，提示需 gcompat
✅ .so 架构                 .so=aarch64 (10.6MB)  本机=aarch64
✅ gcompat（glibc 兼容层）   已安装
✅ .so 加载与符号            6 个符号全部可解析
✅ 配置目录                 存在，含 14 个文件
✅ hilink.cfg               159 bytes, sha256=caeed1592c71...
                            ⚠️  库期望 5ef8d8b8b* → 版本校验可能失败
✅ C 库生成的配置文件        4/4 已生成
```

---

## 症状 1：找不到集成

**现象**：设置 → 添加集成，搜索不到 `hwhomebridge`

| 检查 | 命令 |
|---|---|
| 目录是否存在 | `ls /config/custom_components/hwhomebridge/` |
| `manifest.json` 是否有效 | `cat /config/custom_components/hwhomebridge/manifest.json` |
| 是否已重启 HA | 安装自定义集成后**必须重启** |
| HA 日志有无加载错误 | `docker logs homeassistant 2>&1 \| grep -i hwhomebridge` |

**注意**：删除集成后要重新添加，**必须先重启 HA**（原项目 README 提示）。

---

## 症状 2：`.so` 加载失败

**现象**：

```
Error loading shared library ld-linux-aarch64.so.1: No such file or directory
```

**原因**：`.so` 是 glibc 编译的，系统是 musl（Alpine）。

**解决**：

```bash
docker exec homeassistant apk add --no-cache gcompat
```

**验证**：

```bash
docker exec homeassistant python3 -c "
import ctypes
ctypes.CDLL('/config/custom_components/hwhomebridge/hilink_bridge/libhilink_bridge.so',
            mode=ctypes.RTLD_GLOBAL)
print('OK')"
```

**⚠️ 持久性**：`gcompat` 装在容器内，**HA 升级或容器重建后会丢失**，需重装。

---

## 症状 3：kv init error ret -600

**现象**：

```
LD_ERR  hilink_kv_adapter.c:178, realpath error
LD_WARN hilink_kv_adapter.c:200, set config path error
LD_ERR  hilink_store.c:374, kv init error ret -600
LD_ERR  base_component.c:123, kv store init error, ret[5]
```

**原因**：`hilink_bridge/config/` 目录不存在。

**解决**：

```bash
docker exec homeassistant mkdir -p /config/custom_components/hwhomebridge/hilink_bridge/config
docker exec homeassistant chmod 755 /config/custom_components/hwhomebridge/hilink_bridge/config
```

**验证**：日志应出现

```
LD_INFO base_component.c:129, kv store init ok
```

---

## 症状 4：URL 表校验失败（⚠️ 无解）

**现象**：

```
LD_ERR    hilink_url.c:134, read fail, keyType: 22
LD_NOTICE hilink_url.c:158, not same, now is caeed1592*, need:5ef8d8b8b*
LD_ERR    hilink_url.c:259, check urlFile integrity fail!
LD_ERR    hilink_mngr.c:952, m2m init is not init
```

**频率**：约 1.3 条/秒，**4600 条/小时**。

**原因**：C 库需要从华为云获取特定版本的 URL 表，本地缓存的版本不匹配。

**当前状态**：❌ **尚未找到解决方案**

详细分析见 `docs/findings.md` 第五节。

### 可以尝试的

1. 确认网络能访问 `iomplatform.hicloud.com`
2. 检查 DNS 解析
3. 放置 `hilink.cfg`（见下），虽然**大概率仍会失败**

### 放置 hilink.cfg 的方法

```bash
docker exec homeassistant sh -c 'cat > /config/custom_components/hwhomebridge/hilink_bridge/config/hilink.cfg <<EOF
{
	"url": {
		"cloud": "iomplatform.hicloud.com",
		"hota": "update-drcn.platform.hicloud.com",
		"bi": "data.hicloud.com",
		"sntp": "0.cn.pool.ntp.org"
	}
}
EOF'
```

### 为什么放文件不够

C 库报告的 `now is caeed1592*` **正是该文件的 SHA256 前缀**：

```
文件 sha256:  caeed1592c71d91a06af704183dad75c38657b8763d56e5daecb88eb9f74822f
库报告 now:   caeed1592*
库期望 need:  5ef8d8b8b*
```

说明库**读到了文件**，但要求**另一个版本**。

---

## 症状 5：日志刷屏

**现象**：日志每秒出现多条 `LD_ERR`。

**原因**：C 库**直接向 stdout 输出**，绕过 HA 的 `logger` 组件。

**解决**：**禁用集成**

```
设置 → 设备与服务 → Huawei HA Gateway → ⋮ → 禁用
```

或直接改存储：

```bash
# 停止 HA 后
python3 - <<'PY'
import json
p = '/config/.storage/core.config_entries'
d = json.load(open(p, encoding='utf-8'))
for e in d['data']['entries']:
    if e['domain'] == 'hwhomebridge':
        e['disabled_by'] = 'user'
json.dump(d, open(p, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
PY
```

**⚠️ 注意**：禁用后**仍需重启 HA** 才能卸载已加载的 C 库。

**试试 `logger` 能不能屏蔽？** —— **不能**。C 库的输出不经过 Python logging：

```
LD_ERR|112|hilink_url.c:259, check urlFile integrity fail!
     ↑ 这是 C 宏，不是 Python logging
```

---

## 症状 6：设备未被识别

**现象**：日志出现

```
WARNING Device XXX: product 005 matched, but no service-entity mapping
  could be established, skip
```

**原因**：设备的实体结构与适配器的 `ha_mapping` 对不上。

**排查步骤**：

1. 在 HA 里找到该设备：设置 → 设备与服务 → 选集成 → 点设备
2. 记录有**哪些实体**（domain + 名称）
3. 对照适配器需求，例如 `005`（电水壶）需要：

```
mode / heatingTarget / status / switch / temperature
```

4. 缺哪个补哪个，或修改适配器的 `name_keywords`

**调整技巧**：在 HA 里**给设备改个名字加入关键词**，可能就能匹配上。

---

## 症状 7：8 个 9MT* 适配器报错

**现象**：

```
WARNING Adapter .../default/9MTJ.json: PID '9MTJ' not found in framework, skipping
... (共 8 条)
```

**原因**：这 8 个适配器的 PID **没有注册进 `product_registry.json`**。

**影响**：🟡 **无害**（只是被跳过），但降低了可用性 ——
本该匹配 `9MT*` 品类的设备会匹配失败。

**修复**：在 `product_registry.json` 的 `products` 数组里补上它们的框架层定义。

详见 `docs/findings.md` 第二节。

---

## 症状 8：PIN 码不出现

**现象**：集成"配置"页面没有 PIN 码。

**前提条件**：PIN 码在 **C 库完成初始化后**才生成。

**检查顺序**：

```
.so 加载成功？
    ↓ 否 → 装 gcompat
kv 初始化成功？
    ↓ 否 → 创建 config 目录
URL 表校验通过？
    ↓ 否 → ⚠️ 无解（见症状 4）
PIN 码生成
```

**如果卡在 URL 表，PIN 码永远不会出现。**

---

## 完全卸载

```bash
# 1. 禁用集成（如果 HA 在运行）
#    设置 → 设备与服务 → Huawei HA Gateway → 禁用
#    然后重启一次 HA，确保 C 库卸载

# 2. 删除文件
rm -rf /config/custom_components/hwhomebridge

# 3. 删除配置条目
#    设置 → 设备与服务 → Huawei HA Gateway → ⋮ → 删除
#    然后重启 HA
```

**注意**：先禁用并重启，再删除 —— 否则运行中的 C 库可能还在写文件。

---

## 排查用的命令速查

```bash
# 查看所有 hwhomebridge 日志
docker logs homeassistant 2>&1 | grep -iE 'hwhomebridge|LD_' | tail -50

# 只看 C 库错误
docker logs homeassistant 2>&1 | grep 'LD_ERR' | tail -20

# 统计错误频率
docker logs homeassistant --since 1m 2>&1 | grep -c 'LD_ERR'

# 检查集成状态
docker exec homeassistant python3 -c "
import json
d = json.load(open('/config/.storage/core.config_entries'))
for e in d['data']['entries']:
    if e['domain'] == 'hwhomebridge':
        print('disabled_by:', e.get('disabled_by'))
"

# 检查配置文件
docker exec homeassistant ls -la /config/custom_components/hwhomebridge/hilink_bridge/config/

# 检查 C 库生成的 cfg 是否有内容
docker exec homeassistant sh -c 'wc -c /config/custom_components/hwhomebridge/hilink_bridge/config/*.cfg'
```
