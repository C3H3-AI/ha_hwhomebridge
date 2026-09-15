# 技术发现汇总

本文汇总安装调试过程中对集成、二进制与项目本身的观察。

---

## 一、二进制分析

### 1.1 `.so` 是个人开发机产物

```bash
$ readelf -d libhilink_bridge.so | grep -E 'NEEDED|SONAME|RUNPATH'
 (SONAME)  Library soname: [libhilink_bridge.so]
 (NEEDED)  Shared library: [libc.so.6]
 (NEEDED)  Shared library: [ld-linux-aarch64.so.1]
 (RUNPATH) Library runpath: [/home/w30033997/hlink_bridge_new/lib:]
```

**关键点**：

| 观察 | 含义 |
|---|---|
| `RUNPATH` = `/home/w30033997/...` | 构建者的**本机路径**未清理 → 个人构建 |
| 只 `NEEDED` libc | **其他 SDK 已静态链接**进去 |
| 文件 **11,072,048 字节**（10.6 MB）| 静态链接的体积印证 |
| `.text` 段偏移 `0xa2b360` ≈ 10.6 MB | 几乎全是代码 |

### 1.2 导出符号只有 10 个

```bash
$ nm -D libhilink_bridge.so | grep ' T '
00000000000162d8 T GetGatewaySN
0000000000489a14 T HILINK_GetDevStatus
0000000000016658 T HILINK_SetAutoAc
000000000039e5e8 T HilinkSyncBrgDevStatus
0000000000014368 T RegGetRoomInfoCallback
00000000000142d0 T RegHomeAssistantPyCB
0000000000014344 T RegPINQueryCallback
00000000000143c8 T UpdateHAStatus
0000000000015d70 T exit_brg
0000000000015c90 T main
```

**Python 代码只用到其中 6 个**：

```python
lib.HILINK_GetDevStatus()
lib.HILINK_SetAutoAc()
lib.RegHomeAssistantPyCB()
lib.RegPINQueryCallback()
lib.exit_brg()
lib.main()
```

**全部已导出 ✅** —— 说明符号层面没有问题，卡点在运行时初始化。

### 1.3 架构

```
$ readelf -h libhilink_bridge.so
  Class:    ELF64
  Machine:  AArch64          (e_machine = 0xb7)
```

aarch64 原生，**无需 qemu 转译**。

---

## 二、那 8 个 `9MT*` 适配器是什么？

启动时会出现 8 条 warning：

```
WARNING Adapter .../default/9MTJ.json: PID '9MTJ' not found in framework, skipping
WARNING Adapter .../default/9MTL.json: PID '9MTL' not found in framework, skipping
... (共 8 条)
```

`validate_config.py` 也会报 8 个 ERROR。

### 它们**不是**笔误，而是真实的华为 PID

以 `9MT` 为前缀的 PID 与标准的 `001`-`008` **一一对应**：

| 标准 PID | 服务 | 9MT* PID | 服务 | 是否一致 |
|---|---|---|---|---|
| 001 | switch, brightness, cct | **9MTJ** | switch, brightness, **status**, cct | ⚠️ 多 status |
| 002 | switch, brightness, cct | **9MTL** | switch, brightness, cct | ✅ |
| 003 | switch, brightness, status, cct | **9MU7** | switch, brightness, cct | ⚠️ 少 status |
| 004 | alarmBell | **9MTM** | alarmBell | ✅ |
| 005 | mode, heatingTarget, status, switch, temperature | **9MTR** | 同左 | ✅ |
| 006 | switch | **9MTV** | switch | ✅ |
| 007 | switch, cooker, status, leftTime | **9MTW** | 同左 | ✅ |
| 008 | switch, electric, voltage, power, current | **9MTX** | switch, **totalForwardEnergy** | ⚠️ 服务不同 |

### 推断

`9MT*` 很可能是**华为内部的新版 PID 命名**（`9MT` 系列），
作者在 `adapters/default/` 里放了这些适配器，
但**忘了把它们注册进 `product_registry.json` 的 `products` 数组**。

### 影响

**无害但降低可用性** —— 这 8 个适配器**永远不会被加载**。
如果某设备本该匹配 `9MT*` 品类（例如新版断路器 `9MTX`），
它会**匹配失败而被跳过**。

### 修复方法

在 `product_registry.json` 的 `products` 数组里补上这 8 个 PID 的框架层定义。例如：

```json
{
    "pid": "9MTX",
    "name": "断路器(新版)",
    "services": {
        "switch": {"service_type": "switch", "char_name": "on"},
        "totalForwardEnergy": {"service_type": "electric", "char_name": "totalForwardEnergy"}
    }
}
```

（具体 `service_type` / `char_name` 需对照华为 profile，此处仅为示例。）

---

## 三、项目元数据未清理

`manifest.json`：

```json
{
  "domain": "hwhomebridge",
  "name": "HuaweiHome Bridge",
  "version": "1.0.0",
  "config_flow": true,
  "documentation": "https://github.com/XXX/hwhomebridge",
  "issue_tracker": "https://github.com/XXX/hwhomebridge/issues",
  "requirements": ["psutil", "aiofiles"],
  "iot_class": "cloud_polling",
  "codeowners": ["@XXX"]
}
```

**`documentation`、`issue_tracker`、`codeowners` 全是 `XXX` 占位符**
—— 作者没来得及填。

这也意味着 **HA 的"报告问题"链接会指向不存在的仓库**。

---

## 四、代码质量问题

### 4.1 事件循环里的阻塞调用

```
WARNING Detected blocking call to scandir with args
  ('/config/custom_components/hwhomebridge/config/adapters',)
  inside the event loop by custom integration 'hwhomebridge'
  at custom_components/hwhomebridge/product_registry.py, line 454:
    for root, dirs, files in os.walk(adapters_dir):
```

```
WARNING Detected blocking call to open with args ('new_device.txt', 'r')
  inside the event loop by custom integration 'hwhomebridge'
  at custom_components/hwhomebridge/hwbridge.py, line 491:
    with open(saved_device_file, 'r') as f:
```

**启动耗时**：`Setup of hwhomebridge is taking over 10 seconds.`

### 4.2 使用了已弃用的 API

```
WARNING Detected that custom integration 'hwhomebridge' uses
  `device_registry.devices` as a mapping or calls its lookup methods,
  which is deprecated; iterate it to get the device entries, or use
  `async_get`, `async_entries_for_config_entry` and similar helpers
  at custom_components/hwhomebridge/hwbridge.py, line 534:
    for device_id in all_devices.keys():
  This will stop working in Home Assistant 2027.9.0
```

**需要在 HA 2027.9 前修复**，否则集成会失效。

### 4.3 设备映射失败

```
WARNING Device c4cd4a6c3281b98e4b6b7eb42b08dc38: product 005 matched,
  but no service-entity mapping could be established, skip
```

某个设备的实体结构与 `005`（电水壶）的 `ha_mapping` 对不上，**被跳过**。

`005` 电水壶需要 5 类实体：

```
mode / heatingTarget / status / switch / temperature
```

缺少任一就映射失败。用户可调整实体名称或修改适配器的 `name_keywords`。

---

## 五、URL 表校验的深入分析

### 5.1 错误序列的完整时间线

```
[启动]
  ↓
LD_NOTICE hilink_speke_common.c:170, InitSecuritySpeke success     ← 安全模块 OK
  ↓
LD_ERR    hilink_kv_adapter.c:178, realpath error                  ← 配置目录不存在
LD_WARN   hilink_kv_adapter.c:200, set config path error
LD_ERR    hilink_store.c:374, kv init error ret -600
LD_ERR    base_component.c:123, kv store init error, ret[5]
LD_WARN   base_component.c:178, Base component init error
  ↓
[创建 config 目录后]
  ↓
LD_NOTICE hilink_kv_adapter.c:187, set path /config/.../config      ← 路径设置成功
LD_INFO   hilink_kv_adapter.c:142, kv init .../config.cfg
LD_INFO   hilink_kv_adapter.c:142, kv init .../timer.cfg
LD_INFO   hilink_kv_adapter.c:142, kv init .../bridge.cfg
LD_INFO   hilink_kv_adapter.c:142, kv init .../pidMap.cfg
LD_INFO   hilink_kv_adapter.c:142, kv init .../subDevInfo.cfg
LD_INFO   hilink_kv_adapter.c:142, kv init .../hilink_cert.cfg
LD_INFO   base_component.c:129, kv store init ok                   ← kv 初始化成功
  ↓
[进入 URL 表阶段]
  ↓
LD_ERR    hilink_kv_adapter.c:279, open .../hilink.cfg file error, errno: 2
LD_ERR    hilink_store.c:464, ERR_STORE_READ/-599/2/22/1024/0
LD_ERR    hilink_url.c:134, read fail, keyType: 22
LD_NOTICE hilink_url.c:158, not same, now is caeed1592*, need:5ef8d8b8b*
LD_ERR    hilink_url.c:259, check urlFile integrity fail!
  ↓
[放入 hilink.cfg 后]——错误变了但没解决
  ↓
LD_NOTICE hilink_url.c:158, not same, now is caeed1592*, need:5ef8d8b8b*
LD_ERR    hilink_url.c:259, check urlFile integrity fail!
LD_ERR    hilink_mngr.c:952, m2m init is not init                  ← 上游未初始化
  ↓
[死循环] 约 1.3 条/秒 = 4600 条/小时
```

### 5.2 哈希分析

我放入的 `hilink.cfg`（来自 `ppq-ppq/honyar`）：

```json
{
	"url": {
		"cloud": "iomplatform.hicloud.com",
		"hota": "update-drcn.platform.hicloud.com",
		"bi": "data.hicloud.com",
		"sntp": "0.cn.pool.ntp.org"
	}
}
```

实测哈希：

```
$ sha256sum hilink.cfg
caeed1592c71d91a06af704183dad75c38657b8763d56e5daecb88eb9f74822f
$ sha1sum hilink.cfg
5f73222268623be0ea36abdb318706329c562bf5
$ md5sum hilink.cfg
daa8d3b8286ad88304c419d6b6411a54
```

**库报告的 `now is caeed1592*` = 文件的 SHA256 前缀**。

**结论**：校验用的是 **SHA256**，且库**确实读到了我们放的文件**。

```
现在有:  caeed1592...
期望值:  5ef8d8b8b...
```

### 5.3 尝试过的组合（18 种，全部失败）

试了不同的 `cloud` / `hota` 域名组合：

```python
clouds = ['iomplatform.hicloud.com', 'iotplatform.hicloud.com',
          'device.hicloud.com', 'query.hicloud.com',
          'api.hicloud.com', 'hicloud.com']
hotas  = ['update-drcn.platform.hicloud.com', 'query.hicloud.com',
          'update.hicloud.com']
```

**没有一种能凑出 `5ef8d8b8b`。**

### 5.4 推断

`5ef8d8b8b` 对应的文件**不是简单改域名能得到的**，可能：

1. 含**版本号字段**（如 `"version": "1.2.3"`）
2. 含**时间戳/有效期**字段
3. 由华为服务器**动态下发**（本地文件只是缓存）
4. 含有**签名/校验字段**

### 5.5 另一个公开版本（也不匹配）

从 `dawmlight/vendor_ingenic`（Ingenic 芯片的智能笔固件）找到另一个版本：

```json
{
	"url": {
		"hota": "query.hicloud.com",
		"bi": "data.hicloud.com"
	}
}
```

```
sha256: 386875beb40efd46825fe9bd451ae0a1605618d6072d1f48acc31e7463e81fff
匹配目标 5ef8d8b8b: ❌ 否
```

**字段更少（只有 2 个），也不匹配。**

### 5.6 为什么需要在本地有这个文件？

从 C 库行为推断的设计意图：

```
启动
  ↓
读本地 hilink.cfg（缓存上次成功获取的 URL 表）
  ↓
若缓存有效 → 直接使用
若无效/缺失 → 联网向华为服务器请求
  ↓
拿到新表 → 校验 → 写入本地 → 使用
```

**问题**：如果**联网请求这一步就失败**（网络/凭证/证书问题），
缓存又不存在，就会**永远卡在循环里**。

**这也解释了为什么放文件不能解决** —— 文件只是缓存，
真正的数据必须从华为云获取，而这一步没有成功。

---

## 六、日志输出不可控

C 库的 `LD_ERR` / `LD_INFO` / `LD_NOTICE` 是**直接向 stdout 输出**的：

```
LD_ERR|112|hilink_url.c:259, check urlFile integrity fail!
     ↑
     这是 C 库的日志宏，不是 Python logging
```

**HA 的 `logger` 组件无法屏蔽这类输出。**

### 可选的处理方式

| 方式 | 效果 |
|---|---|
| 禁用集成 | ✅ 彻底停止 |
| `logger: logs: custom_components.hwhomebridge: critical` | ❌ 无效（C 库绕过 HA 日志）|
| 重定向容器 stdout | ⚠️ 会影响所有集成，不推荐 |

**最佳实践：如果不能用，就禁用集成**，避免日志刷屏。

---

## 七、项目生命周期的观察

| 时间 | 事件 |
|---|---|
| 2026-08-31 | `Initial commit` |
| 2026-09-11 | `feat: initial commit`（主要功能）|
| 2026-09-11 | README 合并冲突处理 |
| 2026-09-15 上午 | `Create hilink_bridge` |
| 2026-09-15 上午 | `add depended so` ← 补上 `.so` 文件 |
| 2026-09-15 下午 | `change directory` |
| 2026-09-15 下午 | `feat:add ac info config and adapt mA unit` ← **最后一次提交** |
| 2026-09-15 晚 | **仓库消失**（404）|

**从创建到删除：15 天。**
**从最后一次提交到删除：几小时。**

### 可能的原因

作者在 README 里的警告值得注意：

> **账号风险**：使用本桥接方案接入华为云服务，可能导致华为账号受限、封禁
> **SDK 使用**：本项目使用了部分 HiLink SDK 功能，该 SDK 的使用可能受华为相关服务条款约束
> **合规责任**：使用者有责任确保在本地区的法律法规框架下合法使用本项目

结合项目仅存活 15 天，推测可能是**主动撤回**（而非技术原因）。

---

## 八、其他值得注意的点

### 8.1 PIN 码机制

- PIN 码 **8 位**
- **有效期 5 分钟**
- 在集成"配置"页面显示
- 华为智慧生活 App → `+` → 添加设备 → "HA 网关" → 输入 PIN

**删除集成后要重新添加，必须先重启 HA**，否则集成无法正常工作
（README 明确提示）。

### 8.2 依赖

```
psutil    → 网络接口发现
aiofiles  → 异步文件操作
```

两者都是常见包，HA 环境通常**已预装**：

```
psutil: 7.2.2 ✅
aiofiles: 25.1.0 ✅
```

### 8.3 `hilink_bridge.cfg` 的去向

`AGENTS.md` 提到：

> `hilink_bridge/hilink_bridge.cfg` — HiLink bridge config
> (productId, deviceTypeId, workdir, udpport, productSN)

但**仓库里没有这个文件**，代码也**没有创建它**。

推测：它是**运行时由 C 库生成**的（类似那些 `.cfg`），
或者**需要手动配置但作者忘了写文档**。

### 8.4 配置文件清单

C 库在 `hilink_bridge/config/` 下生成 12 个 `.cfg`：

```
bridge.cfg          bridge_bak.cfg
config.cfg          config_bak.cfg
hilink_cert.cfg     hilink_cert_bak.cfg
pidMap.cfg          pidMap_bak.cfg
subDevInfo.cfg      subDevInfo_bak.cfg
timer.cfg           timer_bak.cfg
```

初始全部为 **0 字节**（见 `hilink_kv_adapter.c:142` 的 init 日志）。

此外代码还会引用（但未生成）：

```
hilink.cfg          hilink_bak.cfg        ← URL 表（需手动放置）
```

**注意**：代码里的 `hilink_cfg_files` 元组**不包含** `hilink.cfg`，
只包含上面 12 个中的一个子集 —— 说明 URL 表**由 C 库自己管理**。
