# ha_hwhomebridge — 安装踩坑记录与修复

> **本项目不是原项目的 fork。**
>
> 原项目（`Wangxiaokang666-666/ha_hwhomebridge`）已于 2026-09-15 删除/转私有
> （创建于 2026-08-31，存在约 15 天）。
>
> 本仓库保留**实测得到的安装经验、诊断结论与可用修复**，供后来者参考。

---

## 这是什么

**原项目目标**：把 Home Assistant 里的设备反向桥接到华为鸿蒙智家，
从而可以用**华为智慧生活 App** 或**小艺语音**控制 HA 设备。

```
华为智慧生活 App / 小艺语音
        ↓
    华为云服务
        ↓
   HiLink SDK (libhilink_bridge.so)
        ↓
   hwhomebridge（HA 集成）
        ↓
  Home Assistant
        ↓
   实际设备
```

**本仓库内容**：在真实环境（HAOS + aarch64）上完整走了一遍安装流程，
记录了**每一个卡点、根因、以及解决方案**。

---

## 测试环境

| 项 | 值 |
|---|---|
| 安装方式 | Home Assistant OS (Supervisor) |
| 硬件 | Panther-X2（aarch64 / ARM64）|
| HA Core | 2026.9.1 |
| **容器基础镜像** | **Alpine Linux 3.24.1（musl libc）** |
| Python | 3.14.6 |
| 原集成版本 | 1.0.0 |
| `.so` 架构 | aarch64（`e_machine=0xb7`）|

---

## 结论速览

| 阶段 | 结果 |
|---|---|
| `.so` 加载 | ✅ **解决**（需 `gcompat`）|
| C 库 kv 初始化 | ✅ **解决**（需创建 config 目录）|
| URL 表校验 | ❌ **失败**（需华为下发）|
| PIN 码生成 | ❌ 依赖上一步 |
| **能否使用** | ❌ **不能**（见下文）|

---

## 卡点一：glibc / musl 不兼容 ⭐

### 现象

`.so` 无法加载：

```
Error loading shared library ld-linux-aarch64.so.1: No such file or directory
(needed by /config/custom_components/hwhomebridge/hilink_bridge/libhilink_bridge.so)
```

### 根因

```
libhilink_bridge.so  →  glibc 编译
HA 容器              →  Alpine + musl libc
```

`ld-linux-aarch64.so.1` 是 glibc 的动态链接器，musl 系统没有。

### 解决

```bash
apk add --no-cache gcompat
# gcompat-1.1.0-r4  (GNU C Library compatibility layer for musl)
```

安装后 `.so` 可正常加载，**6 个导出符号全部可解析**：

```
✅ HILINK_GetDevStatus
✅ HILINK_SetAutoAc
✅ RegHomeAssistantPyCB
✅ RegPINQueryCallback
✅ exit_brg
✅ main
```

### 验证方法

```python
import ctypes
lib = ctypes.CDLL(
    '/config/custom_components/hwhomebridge/hilink_bridge/libhilink_bridge.so',
    mode=ctypes.RTLD_GLOBAL)
for sym in ['HILINK_GetDevStatus', 'HILINK_SetAutoAc', 'RegHomeAssistantPyCB',
            'RegPINQueryCallback', 'exit_brg', 'main']:
    getattr(lib, sym)   # 不抛异常即可
print('✅ 全部符号可解析')
```

> ⚠️ `gcompat` 通过 `apk` 安装后**能持久化**（HA 容器重启后仍在），
> 但**升级 HA 或重建容器后可能丢失**，需要重装。

---

## 卡点二：配置目录缺失 ⭐

### 现象

```
LD_ERR  hilink_kv_adapter.c:178, realpath error
LD_WARN hilink_kv_adapter.c:200, set config path error
LD_ERR  hilink_store.c:374, kv init error ret -600
LD_ERR  base_component.c:123, kv store init error, ret[5]
LD_WARN base_component.c:178, Base component init error
```

### 根因

`hwbridge.py` 里设置：

```python
os.environ['HILINK_CONFIG_DIR'] = './custom_components/hwhomebridge/hilink_bridge/config/'
```

但**仓库里没有这个目录**，C 库 `realpath()` 解析失败。

### 解决

```bash
mkdir -p /config/custom_components/hwhomebridge/hilink_bridge/config
chmod 755 /config/custom_components/hwhomebridge/hilink_bridge/config
```

### 验证

日志变为：

```
LD_NOTICE hilink_kv_adapter.c:187, set path /config/custom_components/hwhomebridge/hilink_bridge/config
LD_INFO   hilink_kv_adapter.c:142, kv init .../config.cfg
LD_INFO   hilink_kv_adapter.c:142, kv init .../timer.cfg
LD_INFO   hilink_kv_adapter.c:142, kv init .../bridge.cfg
LD_INFO   hilink_kv_adapter.c:142, kv init .../pidMap.cfg
LD_INFO   hilink_kv_adapter.c:142, kv init .../subDevInfo.cfg
LD_INFO   hilink_kv_adapter.c:142, kv init .../hilink_cert.cfg
LD_INFO   base_component.c:129, kv store init ok        ← 成功
```

C 库会自动生成 12 个 `.cfg` 文件（初始为空）。

---

## 卡点三：URL 表完整性校验失败 ❌ **（未解决）**

### 现象

kv 初始化成功后，进入死循环：

```
LD_ERR    hilink_kv_adapter.c:279, open .../config/hilink.cfg file error, errno: 2
LD_ERR    hilink_store.c:464, ERR_STORE_READ/-599/2/22/1024/0
LD_ERR    hilink_url.c:134, read fail, keyType: 22
LD_NOTICE hilink_url.c:158, not same, now is caeed1592*, need:5ef8d8b8b*
LD_ERR    hilink_url.c:259, check urlFile integrity fail!
LD_ERR    hilink_mngr.c:952, m2m init is not init
```

**频率**：约 1.3 条/秒，**4600 条/小时**。

### 已尝试的修复

从公开仓库 [`ppq-ppq/honyar`](https://github.com/ppq-ppq/honyar)
（鸿雁 HiLink 网关固件）找到 `hilink.cfg` 并放入：

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

### 效果：错误变化，但未解决

```
修复前:  open hilink.cfg file error, errno: 2      ← 文件不存在
修复后:  not same, now is caeed1592*, need:5ef8d8b8b*
         check urlFile integrity fail!              ← 完整性校验失败
```

### 关键分析

**库报告的 `now is caeed1592*` 正是该文件的 SHA256 前缀**：

```bash
$ sha256sum hilink.cfg
caeed1592c71d91a06af704183dad75c38657b8763d56e5daecb88eb9f74822f
```

```
库报告 now:   caeed1592*     ← 与我们文件一致，说明文件被正确读取
库期望 need:  5ef8d8b8b*     ← 是另一个版本
```

**结论**：C 库能读到文件，但要求**特定版本**的 URL 表。
尝试了 18 种域名/格式组合均无法凑出 `5ef8d8b8b` 哈希，
推测该文件含**版本号或时间戳字段**，或需**从华为服务器动态下发**。

### 待解答的问题

1. `5ef8d8b8b` 对应的 `hilink.cfg` 内容是什么？
2. URL 表是否必须从华为云下载？需要什么前置条件（凭证 / productId / SN）？
3. `hilink_bridge.cfg` 是否需要预置？（AGENTS.md 提到它含
   `productId`、`deviceTypeId`、`productSN`、`udpport`，
   但仓库里没有此文件，代码也未创建）

---

## 其他发现

### `.so` 是个人开发机产物

```bash
$ readelf -d libhilink_bridge.so | grep -E 'NEEDED|RUNPATH'
 (NEEDED)  Shared library: [libc.so.6]
 (NEEDED)  Shared library: [ld-linux-aarch64.so.1]
 (RUNPATH) Library runpath: [/home/w30033997/hlink_bridge_new/lib:]
```

- **RUNPATH 指向开发者本机路径**，说明是个人构建
- 只依赖 `libc`，**其他 SDK 已静态链接**（11MB 体积印证）
- `.text` 段约 10.6MB

### 导出符号（仅 10 个）

```bash
$ nm -D libhilink_bridge.so | grep ' T '
GetGatewaySN
HILINK_GetDevStatus
HILINK_SetAutoAc
HilinkSyncBrgDevStatus
RegGetRoomInfoCallback
RegHomeAssistantPyCB
RegPINQueryCallback
UpdateHAStatus
exit_brg
main
```

### 支持的品类（仅 8 种）

| PID | 名称 | 服务 |
|---|---|---|
| 001 | 床头灯 | switch / brightness / cct |
| 002 | 灯泡 | switch / brightness / cct |
| 003 | 小夜灯 | switch / brightness / status / cct |
| 004 | 压力传感器 | alarmBell |
| 005 | 电水壶 | mode / heatingTarget / status / switch / temperature |
| 006 | 灭蚊器 | switch / delay |
| 007 | 电饭煲 | switch / cooker / status / leftTime |
| 008 | 断路器 | switch / electric / voltage / power / current |

> **不支持 `cover`**（晾衣架/窗帘/晾衣杆）。
> 新增品类需改 **C 侧代码并重新编译 SDK**，非配置可解决。

### 代码层支持的 HA domain

```python
# service_action.py
domain == : button, select
handlers  : press, set_brightness, set_color, set_color_temp,
            set_option, set_speed, set_temperature, set_value, turn_on_off
domain literal: button, fan, light, number, select

# service_router.py
domain == : button, light, number, select
domain literal: binary_sensor, button, fan, light, number, select, sensor, switch
```

**无 `cover`。**

### 已知小问题

- 8 个 `9MT*` 适配器文件的 PID 不在 `product_registry.json` 中，
  启动时报 warning 被跳过（`validate_config.py` 报 8 个 ERROR）
- `hwbridge.py` 在事件循环里做阻塞调用（`os.walk` / `open`）
- 使用已弃用的 `device_registry.devices` 映射访问（HA 2027.9 将失效）
- `manifest.json` 里 `documentation` / `issue_tracker` / `codeowners`
  仍是占位符 `https://github.com/XXX/...` 和 `@XXX`

---

## 关键文件位置

```
/config/custom_components/hwhomebridge/
├── hwbridge.py                    # 核心：C 库初始化、回调注册
├── service_router.py              # 控制路由、状态上报、设备注册
├── service_action.py              # 服务操作分发
├── product_registry.py            # 三层配置加载
├── product_matcher.py             # 三级匹配引擎
├── virtual_device.py              # 虚拟设备模型
├── pin_manager.py                 # PIN 码管理
├── config/
│   ├── product_registry.json      # 框架层：华为产品定义
│   └── adapters/
│       ├── default/               # 默认适配器
│       ├── xiaomi/                # 小米适配器
│       └── midea/                 # 美的适配器
└── hilink_bridge/
    ├── libhilink_bridge.so        # 11MB，aarch64 + glibc
    └── config/                    # ⚠️ 需手动创建！
        └── hilink.cfg             # ⚠️ 需手动放入
```

---

## 建议

### 如果你仍想尝试

1. 装 `gcompat`
2. 创建 `hilink_bridge/config/` 目录
3. 放入 `hilink.cfg`（见上文）
4. 若仍卡在 URL 校验 —— **需要找到正确版本的 URL 表**
5. 考虑用 `logger` 配置降低 C 库日志噪音（它会绕过 HA 日志系统直接输出到 stdout）

### 重要提醒

- 原项目作者自己警告：**"可能导致华为账号受限、封禁"**
- 建议使用**备用华为账号**测试
- 项目仅存在 15 天即被删除，稳定性与合规性存疑

### 降低日志噪音

集成的 C 库**直接向 stdout 输出**，不受 HA `logger` 组件控制。
如果持续报错，只能：

```bash
# 禁用集成（推荐）
# 设置 → 设备与服务 → Huawei HA Gateway → 禁用
```

或在 `configuration.yaml` 里屏蔽该组件日志 —— **但 C 库的输出无法屏蔽**。

---

## 相关项目

安装过程中发现的相关公开资源：

| 项目 | 说明 |
|---|---|
| [`ppq-ppq/honyar`](https://github.com/ppq-ppq/honyar) | 鸿雁 HiLink 网关固件，含 `hilink.cfg`、`libhilinkdevicesdk.so`、`libhilinkota.so`、华为官方集成文档 PDF |
| `openharmony/device_soc_hisilicon` | OpenHarmony HiLink 适配层源码 |

---

## 许可

本仓库文档部分采用 CC0 / 公共领域。
原项目代码版权归原作者所有，本仓库**未重新分发**原项目代码。

**免责声明**：本项目按"现状"提供，不提供任何担保。
使用桥接方案接入华为云服务可能带来的账号风险，由使用者自行承担。
