# Compose Dataset Referenced-Media Mounting Plan

## 1. 背景

当前 `/sure_infer` 的容器执行路径会为本次请求中的每个数据集挂载其自身的 `source_root`，挂载方式是只读 bind mount。数据集 projection 的 JSONL 记录可以引用另一个源数据集中的媒体，但当前挂载逻辑不会沿着这些引用补充挂载被引用的数据集。

这会导致 compose 数据集出现以下情况：

```text
请求的数据集:
  ds_pool/e2e-chain-20261104

JSONL 中的音频:
  ds_pool/MASC-test_clean/raws/sample/audio/example.wav

当前容器挂载:
  ds_pool/e2e-chain-20261104 -> 只读

缺失:
  ds_pool/MASC-test_clean -> 未挂载
```

模型可以正常启动，但在第一次读取外部音频时失败，最终表现为零预测和 smoke 阶段失败。

## 2. 当前实现

相关实现位于：

```text
sure/skills/sure_infer/scripts/container_execution.py
```

当前逻辑遍历 `eval_input["datasets"]` 中的每个数据集，并处理：

- `source_root`：目录直接作为只读挂载源；
- `jsonl_path`：如果不属于已挂载的 projection root，则挂载其所在目录，只读。

因此，选择多个数据集时，当前行为是分别挂载多个数据集：

```text
dataset-A/source_root -> 只读挂载
dataset-B/source_root -> 只读挂载
dataset-C/source_root -> 只读挂载
```

当前实现不会：

- 自动挂载共同父目录；
- 扫描整个 `external_ds`；
- 读取 `selection_manifest.jsonl`；
- 根据 compose 数据集的引用关系补充挂载外部源数据集。

## 3. 目标

在不扩大到整个数据池的情况下，让 compose 数据集能够访问其实际引用的媒体文件。

目标行为：

1. 从请求数据集的 selection manifest 读取外部引用；
2. 按被引用的源数据集去重；
3. 为每个被引用源数据集补充只读挂载；
4. 保留容器内可见路径与数据 JSONL 中的绝对路径一致；
5. 不因为挂载而复制或预读整个数据集；
6. 对所有 manifest 提供的路径做允许根目录校验，失败时拒绝启动。

## 4. Manifest 字段设计

建议在 `selection_manifest.jsonl` 的每条记录中增加 `source_dataset_root`：

```json
{
  "sample_id": "...",
  "source_ds_id": "ds202611031527FBXH",
  "source_dataset_root": "/hpc_stor08/external_ds/aispeech/g001/store002/ds_pool/MASC-test_clean",
  "source_version": "v1.0.1",
  "raw_data_name": "ds202611031527FBXH/ds2026092213577L8Z/sample/audio/example.wav"
}
```

字段语义：

| 字段 | 语义 | 要求 |
| --- | --- | --- |
| `source_ds_id` | 源数据集的逻辑、稳定 ID | 用于审计和交叉校验，不用于猜目录 |
| `source_dataset_root` | 源数据集的规范绝对路径 | 使用数据路径命名空间中的绝对路径，不能是用户主机内部的临时映射路径 |
| `source_version` | 被引用源数据集的版本 | 用于校验引用版本和路径解析结果 |
| `raw_data_name` | 源数据中的逻辑原始文件名 | 用于审计和定位样本，不直接作为挂载路径 |

选择绝对 `source_dataset_root` 比只记录 `source_ds_name` 更可靠，可以避免不同数据池中出现同名数据集时发生错误挂载。但该字段仍然不能被无条件信任，必须经过路径边界校验。

## 5. Manifest 定位规则

对于一个请求源数据集，按请求版本查找：

```text
<source_root>/extras/<version_id>/selection_manifest.jsonl
```

对于当前 compose 数据集，还存在：

```text
<source_root>/extras/TEMP_VERSION/selection_manifest.jsonl
```

后续实现应明确 TEMP_VERSION 的兼容规则，建议：

1. 优先使用请求版本目录下的 manifest；
2. 只有在明确允许临时版本回退时才使用 `TEMP_VERSION`；
3. 回退时校验 manifest 中的 `source_version` 与请求数据的版本关系；
4. manifest 存在但格式非法时直接失败，不静默忽略引用。

不建议无条件递归搜索 `extras/`，避免读取不相关版本或产生不确定的路径来源。

## 6. 路径解析与挂载策略

### 6.1 逻辑路径和宿主机路径分离

manifest 中的 `source_dataset_root` 应记录容器和数据集 JSONL 使用的规范路径，例如：

```text
/hpc_stor08/external_ds/aispeech/g001/store002/ds_pool/MASC-test_clean
```

不要记录宿主机实际存储映射路径，例如：

```text
/mnt/gpfs_dataset_hdd/hpc_stor09/external_ds/...
```

容器启动器应复用现有数据源解析逻辑，把规范路径解析为宿主机实际路径：

```text
规范路径:
  /hpc_stor08/.../MASC-test_clean

宿主机源路径:
  /mnt/gpfs_dataset_hdd/.../MASC-test_clean

容器目标路径:
  /hpc_stor08/.../MASC-test_clean
```

这样同一份 manifest 不会绑定某个节点的底层存储挂载实现。

### 6.2 挂载粒度

第一阶段建议按源数据集根目录挂载：

```text
<host source_dataset_root> -> <container source_dataset_root>,readonly
```

例如：

```text
.../ds_pool/MASC-test_clean ->
/hpc_stor08/.../ds_pool/MASC-test_clean,readonly
```

这样实现简单，并且能覆盖 `raws/`、版本 metadata 和其他数据布局差异。

后续如果需要进一步缩小可见范围，可以基于 manifest 中实际引用文件计算共同父目录，例如：

```text
.../MASC-test_clean/raws/sample/audio
```

但最小目录挂载需要稳定的逻辑路径到物理路径映射，不应仅通过拼接 `raw_data_name` 猜测，因此不作为第一阶段要求。

### 6.3 多个引用源

如果一个 compose 数据集引用多个源数据集：

```text
source-A -> 只读挂载
source-B -> 只读挂载
source-C -> 只读挂载
```

应按规范路径和实际宿主机路径去重。同一源数据集被多条样本引用时只生成一个挂载。

如果多个源数据集位于同一个允许的父目录下，第一阶段仍建议保持逐个源数据集挂载，不自动提升到公共父目录。这样可以保持数据可见范围最小，并避免无关数据集被暴露给容器。

## 7. 安全校验

每个 `source_dataset_root` 在转为 Docker mount 前必须满足：

1. 是绝对路径；
2. `resolve()` 后仍位于配置的 `datasets.allowed_source_roots` 之一；
3. 路径存在且为目录；
4. 不允许通过 `..`、符号链接或路径别名逃逸允许根；
5. 只允许 `readonly` bind mount；
6. 不允许覆盖已经存在的容器 mount target；
7. 同一容器目标对应不同源路径时直接报冲突；
8. manifest 缺失或格式错误时，根据数据集类型决定失败或明确记录为无引用，不能静默猜测。

特别需要避免直接执行以下操作：

```text
manifest 中的任意绝对路径 -> 直接作为 Docker src
```

manifest 是数据输入，不应成为绕过站点允许路径策略的入口。

## 8. 性能影响

挂载一个较大的父目录本身通常不会复制或读取其全部内容。Docker bind mount 主要建立文件系统命名空间映射，启动耗时不会按目录内文件总数线性增加。

实际 I/O 发生在：

- 读取音频内容时；
- 对文件执行 `stat()`、`exists()` 时；
- 递归扫描目录时；
- 数据集预加载或建立索引时。

因此，按引用只读挂载的收益是：

- 不需要挂载整个 `/hpc_stor08/external_ds`；
- 不会因为挂载操作本身读取全部数据；
- 缩小了容器可见范围；
- 减少了应用误扫描其他数据集的机会。

## 9. 实施范围

后续实现建议分为以下步骤：

### 阶段一：数据产物

- 在 selection manifest 中增加 `source_dataset_root`；
- 确认该字段使用规范数据路径，而不是节点本地物理映射路径；
- 为旧 manifest 明确缺字段时的兼容行为；
- 增加 manifest 字段和路径一致性检查。

### 阶段二：输入解析

- 在数据集准备或输入解析阶段确定 manifest 路径；
- 读取并校验所有引用源；
- 将去重后的引用源写入运行时 artifact，供容器执行阶段使用；
- 保留引用来源和校验结果，便于失败诊断。

### 阶段三：容器挂载

- 在 `container_execution.py` 中读取已解析的引用源列表；
- 使用与主数据集相同的规范路径到宿主机路径解析规则；
- 为每个引用源生成只读 bind mount；
- 与现有 mount target 冲突检查复用同一个 `_mount()` 入口。

### 阶段四：验证

至少覆盖以下测试：

- 单个 compose 数据集引用一个外部源数据集；
- 多个 compose 数据集引用同一个源数据集，确保只挂载一次；
- 一个 compose 数据集引用多个源数据集；
- 引用源不在 `allowed_source_roots` 下时拒绝；
- manifest 中的路径不存在时拒绝或产生明确诊断；
- `TEMP_VERSION` 规则符合预期；
- 现有普通数据集不增加额外挂载；
- 生成的 Docker 命令中所有引用源 mount 都是 `readonly`。

## 10. 本次决策

本阶段只形成方案，不修改实现。

> 实施状态（2026-11-23）：方案已落地。`sure/skills/sure_infer/scripts/referenced_datasets.py`
> 读取并校验 manifest，`resolve_eval_input.py` 把结果写进 `datasets[*].selection_manifest`
> 与 `runtime.referenced_datasets`，`container_execution.py` 据此为每个引用源补一个只读挂载，
> 测试见 `scripts/test_referenced_dataset_mounting.py`。以下设计取舍仍然有效。

推荐的第一阶段设计是：

```text
selection_manifest.jsonl
    -> source_dataset_root（规范绝对路径）
    -> 允许根目录校验和宿主机路径解析
    -> 按源数据集去重
    -> 源数据集根目录只读 bind mount
```

不建议：

- 直接挂载整个 `/hpc_stor08/external_ds`；
- 仅依赖 `source_ds_name` 猜目录；
- 直接把 manifest 中的路径作为宿主机 Docker source；
- 仅根据 `raw_data_name` 字符串拼接物理路径；
- 在容器启动时递归扫描整个数据池寻找引用文件。

