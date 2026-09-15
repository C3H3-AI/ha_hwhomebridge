# 架构分析

本文记录对 hwhomebridge 内部结构的技术分析，基于对 1.0.0 版本源码的阅读。

---

## 整体架构

```
┌──────────────────────────────────────────────────────┐
│                   HA Python Process                   │
│                                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐ │
│  │ Product     │  │ Product     │  │ Virtual      │ │
│  │ Registry    │─▶│ Matcher     │─▶│ Device       │ │
│  │ (框架+适配器)│  │ (三级匹配)   │  │ (聚合单元)    │ │
│  └─────────────┘  └─────────────┘  └──────┬───────┘ │
│                                            │          │
│                 ┌─────────────┐            │          │
│                 │ Service     │            │          │
│                 │ Router      │◀───────────┘          │
│                 │ (控制路由)   │                       │
│                 └──────┬──────┘                       │
│                        │                              │
│  ┌─────────────────────┴───────────────────────┐     │
│  │                hwbridge.py                   │     │
│  └────────────────────┬────────────────────────┘     │
│                       │ ctypes                        │
└───────────────────────┼──────────────────────────────┘
                        │
┌───────────────────────┼──────────────────────────────┐
│                       ▼                               │
│          libhilink_bridge.so (C)                      │
│          HiLink SDK → 华为云                           │
└──────────────────────────────────────────────────────┘
```

**关键设计**：Python 负责业务逻辑，C 负责 HiLink 协议与云端通信，通过 `ctypes` FFI 交互。

---

## 三层配置架构

配置被拆成三层，把**稳定的华为定义**与**易变的 HA 映射**解耦：

```
config/
├── product_registry.json          # 第1层：框架层（华为侧定义）
└── adapters/
    ├── default/                   # 第2层：默认适配器（华为标准 HA 映射）
    │   ├── 001.json  ... 008.json
    │   └── 9MTJ.json ... 9MU7.json
    ├── xiaomi/                    # 第3层：厂家适配器（差异覆盖）
    │   ├── bulb.json  cooker.json  kettle.json
    │   ├── bedside_lamp.json  night_light.json
    │   ├── breaker.json  pressure_sensor.json
    │   └── mosquito_killer.json
    └── midea/
        └── cooker.json
```

**合并规则**：

```
框架(service_type/char_name) + 默认(ha_mapping) + 厂家(差异覆盖) = 最终定义
```

### 第 1 层：框架层

只含华为侧定义，**除非华为注册新 PID，否则不变**：

- `pid`、`name`、`services`
- `services`：`service_type` + `char_name`（镜像华为 profile）
- `auto_match`：可选，标准品类的自动匹配规则

### 第 2 层：默认适配器

从华为 profile 提取的标准 HA 映射，**不含 `match_rules`**（只被继承，不直接匹配）：

- `domain`、`action`、`value_attr`
- `value_mapping`（标准枚举/文本映射）
- `brightness_range`、`colorTemperature_range`、`colorTemperature_min`

### 第 3 层：厂家适配器

只写**差异**，其余从默认适配器继承：

```json
{
    "pid": "002",
    "match_rules": [
        {"type": "model_exact", "model": "yeelink.light.mbulb3"},
        {"type": "name_keyword", "keywords": ["灯泡", "bulb"]}
    ],
    "services": {
        "cct": {
            "colorTemperature_min": 2700
        }
    }
}
```

---

## 三级匹配引擎

设备发现时按优先级依次匹配：

```
1. 厂家适配器 match_rules（按规则类型优先级）：
     model_exact → model_keyword → name_keyword → entity_composition
     命中 → 合并(框架 + 默认 + 厂家) → 返回

2. 框架 auto_match（标准品类零配置接入）：
     required_domains ⊆ 设备 domains + 可选 name_keywords
     命中 → 合并(框架 + 默认) → 返回

3. 都不匹配 → 跳过设备
```

### auto_match 规则（仅 3 个品类）

```json
{"pid": "002", "name": "灯泡",
 "auto_match": {"required_domains": ["light"],
                "name_keywords": ["灯泡", "bulb", "light", "灯"]}}

{"pid": "004", "name": "压力传感器",
 "auto_match": {"required_domains": ["binary_sensor"],
                "name_keywords": ["压力", "pressure", "present"]}}

{"pid": "008", "name": "断路器",
 "auto_match": {"required_domains": ["switch", "sensor"],
                "name_keywords": ["断路器", "空开", "空气开关", "breaker"]}}
```

> **标准品类**（灯、压力传感器、断路器）配了 auto_match，新厂家设备**无需写适配器**即可接入。
> **复杂品类**（电饭煲、电水壶、灭蚊器）**必须**通过厂家适配器匹配。

### match_rules 四种类型

| 类型 | 用途 | 示例 |
|---|---|---|
| `model_exact` | 精确匹配设备 model | `{"type":"model_exact","model":"chunmi.cooker.c301"}` |
| `model_keyword` | 匹配 model 含关键词 | `{"type":"model_keyword","keywords":["MB-FB"]}` |
| `name_keyword` | 匹配设备名称（不分大小写）| `{"type":"name_keyword","keywords":["电水壶","kettle"]}` |
| `entity_composition` | 按实体类型组合匹配 | `{"type":"entity_composition","required_domains":["switch","sensor"]}` |

---

## 值映射（6 种类型）

解决华为 HiLink 协议与 HA 实体状态之间的数值转换。

| 类型 | 用途 | 示例 |
|---|---|---|
| `enum_to_number` | 华为枚举 → HA 数值 | 电水壶模式："7" → 80℃ |
| `text_to_enum` | HA 文本 → 华为枚举 | 工作状态："加热中" → 2 |
| `enum_to_text_multi` | 华为枚举 → 多个可选文本 | 支持多厂商中英文 |
| `number_to_enum_multi` | HA 数值 → 华为枚举 | 状态码 0-5 的文本映射 |
| `seconds_to_minutes` | 时间单位转换 | 秒 → 分钟 |
| `delay_to_select` | 华为倒计时 → HA select | 灭蚊器 3/8/12 小时 |

### 示例：多厂商状态映射

```json
{
    "type": "enum_to_text_multi",
    "mapping": {
        "1": ["快煮饭", "Quick Cook", "quick"],
        "2": ["精煮饭", "Fine Cook", "煮饭"]
    }
}
```

控制时从 HA select 的 options 找匹配项；上报时反向查找枚举值。

---

## 声明式控制（on_command）

复杂行为用 JSON 声明，而非硬编码 if-else：

```json
"on_command": {
    "type": "trigger_service",
    "service": "cooker",
    "use_default_mode": true
}
```

当华为下发 `switch.on=1` 时，自动触发 cooker 服务使用 `default_mode` 启动烹饪。

`service_router.py` 的 `route_action` 使用声明式的 `on_command`，所有设备类型共用同一个 `_execute_on_command()` 方法。

---

## 层次职责

| 文件 | 职责 |
|---|---|
| `hwbridge.py` | 核心：C 库初始化、回调注册、状态监听 |
| `service_router.py` | 编排：设备注册、控制路由、状态上报 |
| `service_action.py` | 服务操作分发（控制命令执行）|
| `product_registry.py` | 三层配置加载与合并 |
| `product_matcher.py` | 三级匹配引擎 |
| `virtual_device.py` | 虚拟设备模型（聚合单元 + SN 管理）|
| `pin_manager.py` | PIN 码管理 |

---

## 虚拟设备与 SN

`virtual_device.py` 里的 `VirtualDevice` 代表一个"聚合单元"——一个华为设备可以聚合多个 HA 实体。

`SNManager.generate_sn(device_id)` 用 **SHA256 哈希**生成 SN，**相同 `device_id` 永远产生相同 SN**（确定性）。

---

## 关键约束

### ctypes 回调生命周期 ⚠️

```python
pActionCB = BRG_ACTION_FUNC(OnPyActionCB)
pTypeCheckCB = CFUNCTYPE(c_int, c_char_p)(OnPyTypeCheckCB)
# ...
```

回调对象存在**模块级全局变量**里，**绝不能被 GC 回收** ——
否则 C 库会调用已释放的函数指针，**导致进程崩溃**。

### 设备持久化

`new_device.txt` 保存已注册的 `device_id`（不是 `entity_id`），跨重启保留。

**当桥接离线时（`devStatus=9`），此文件和 `hilink_bridge/config/` 下所有配置文件会被删除。**

### 网络接口选择

用 `psutil.net_if_addrs()` 找本机 IP，**跳过 `hassio`、`docker*` 和 loopback**。
在多网卡系统上**可能选错接口**。

---

## 代码支持的 HA domain

```python
# service_action.py
domain ==      : button, select
handlers       : press, set_brightness, set_color, set_color_temp,
                 set_option, set_speed, set_temperature, set_value,
                 turn_on_off
domain literal : button, fan, light, number, select

# service_router.py
domain ==      : button, light, number, select
domain literal : binary_sensor, button, fan, light, number, select,
                 sensor, switch
```

**无 `cover`。**

---

## 扩展方式

| 场景 | 需要改代码？ |
|---|---|
| 新厂家，已有品类 | 否 — 厂家适配器 JSON |
| 新型号，同厂家同品类 | 否 — 加 `match_rules` |
| 新的值映射类型 | 是 — `ValueMapping` 类 |
| 新的 HA domain | 是 — `_report_by_type` + `service_action` |
| 新的 `on_command` 类型 | 是 — `_execute_on_command` |
| **新华为品类（新 PID）** | **是 — 框架 JSON + C 侧 SDK 编译** |

**最后一行是本项目最大的限制**：新增品类需要动 C 代码并重新编译 SDK，
而 `.so` 是预编译的闭源二进制（详见 `findings.md`）。
