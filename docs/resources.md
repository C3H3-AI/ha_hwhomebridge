# 相关公开资源

安装调试过程中找到的、与原项目或 HiLink SDK 相关的公开资源。

---

## 一、HiLink 网关固件

### [`ppq-ppq/honyar`](https://github.com/ppq-ppq/honyar)

**鸿雁（HONYAR）HiLink 智能家居网关固件**，包含完整的 HiLink SDK 集成示例。
本仓库的 `hilink.cfg` 即来源于此。

**有价值的文件**：

| 路径 | 内容 |
|---|---|
| `hilink/config/hilink.cfg` | 华为云地址表（159 字节）|
| `hilink2/config/hilink.cfg` | 同上（不同目录）|
| `hilink2/lib/libhilinkdevicesdk.so` | **677 KB** — HiLink 设备 SDK |
| `hilink2/lib/libhilinkdevicesdk.a` | **1.36 MB** — 静态版本 |
| `hilink2/lib/libhilinkota.so` | **38 KB** — OTA 升级库 |
| `hilink2/lib/libhilinkota.a` | **60 KB** |
| `hilink2/include/hilink.h` | SDK 头文件 |
| `hilink2/hilinkprofile/*.json` | 设备 profile（10 个）|
| **`hilink/doc/智能家居HiLink SDK Linux系统集成开发调测指导.pdf`** | **华为官方集成开发文档（850 KB）** |

**注意**：这些都是 **x86_64 / 嵌入式 ARM** 的构建，
与本项目的 aarch64 `.so` **不是同一个**，不能直接替换。

### `dawmlight/vendor_ingenic`

**Ingenic 芯片智能笔的固件**，也含 `hilink.cfg`：

```
smartpen/rootfs-overlay/etc/hilink/hilink.cfg
smartpen/rootfs-overlay/data/mpScan/hilink/hilink.cfg
```

内容是**另一个版本**（字段更少）：

```json
{
	"url": {
		"hota": "query.hicloud.com",
		"bi": "data.hicloud.com"
	}
}
```

---

## 二、OpenHarmony HiLink 适配层

这些项目包含 **HiLink 适配层的 C 源码**，对理解 SDK 内部行为有帮助：

| 项目 | 说明 |
|---|---|
| [`openharmony/device_soc_hisilicon`](https://github.com/openharmony/device_soc_hisilicon) | 海思芯片的 OpenHarmony 适配，含 `hilink_adapt/` |
| [`Hny0305Lin/Hihope_WS63_NearLink_SDK`](https://github.com/Hny0305Lin/Hihope_WS63_NearLink_SDK) | WS63 NearLink SDK，含 HiLink 适配 |
| [`xinzai-x/Hi3863`](https://github.com/xinzai-x/Hi3863) | Hi3863 芯片 SDK |
| [`GeYugong/SHE_07`](https://github.com/GeYugong/SHE_07) | 含 `ohos_connect/hilink_adapt/` |

**有用的文件**（在上述项目中重复出现）：

```
hilink_adapt/adapter/hilink_kv_adapter.c        ← KV 存储适配（对应我们的错误）
hilink_adapt/adapter/include/hilink_kv_adapter.h
hilink_adapt/adapter/network_adapter/hilink_network_adapter.c
hilink_adapt/adapter/profile_adapter/hilink_profile_adapter.c
hilink_adapt/adapter/sdk_adapter/hilink_ota.c
```

**`hilink_kv_adapter.c` 正是我们日志里报错的那个文件**：

```
LD_ERR hilink_kv_adapter.c:178, realpath error
LD_ERR hilink_kv_adapter.c:279, open .../hilink.cfg file error, errno: 2
```

对照源码可以理解这些错误码的含义，但**无法解决 URL 表问题**
（那部分逻辑在闭源的 `libhilink_bridge.so` 里）。

---

## 三、地址表内容参考

各项目里的 `hilink.cfg` 汇总：

### 版本 A（honyar，字段最全）

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

### 版本 B（ingenic，字段较少）

```json
{
	"url": {
		"hota": "query.hicloud.com",
		"bi": "data.hicloud.com"
	}
}
```

### 涉及的所有域名

| 字段 | 域名 | 用途 |
|---|---|---|
| `cloud` | `iomplatform.hicloud.com` | IoT 设备管理平台 |
| `hota` | `update-drcn.platform.hicloud.com` | OTA 升级（中国区）|
| `hota`（旧）| `query.hicloud.com` | 旧版 OTA 查询 |
| `bi` | `data.hicloud.com` | 埋点/数据上报 |
| `sntp` | `0.cn.pool.ntp.org` | 时间同步 |

---

## 四、其他相关项目

安装过程中通过 GitHub 搜索发现的相关仓库：

| 项目 | 说明 |
|---|---|
| `trickest/inventory` | 含 `Huawei/hostnames.txt` — hicloud 域名清单（仅参考）|
| `mtxadmin/ublock` | 含 hicloud 相关 hosts 备份 |
| `rix4uni/BugBountyData` 等 | hicloud 子域名字典（渗透测试用，仅参考）|

> 这些是**域名收集类**项目，与本项目无直接关系，
> 但可用于确认华为云域名是否可达。

---

## 五、原项目

| 项 | 值 |
|---|---|
| 仓库 | `Wangxiaokang666-666/ha_hwhomebridge` |
| 状态 | ❌ **已删除**（2026-09-15，404）|
| 存在时长 | 约 15 天（2026-08-31 → 2026-09-15）|
| 贡献者 | `Wangxiaokang666-666` / `00454243` / `hunt001` / `ChuYu3` |
| 许可 | Apache-2.0 |

本仓库**未重新分发**原项目代码，因此**无法提供源码下载**。
如原项目恢复，请从其官方仓库获取。
