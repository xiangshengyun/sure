# Referenced Dataset Mounting — Review

审查对象：`docs/spec/referenced-dataset-mounting-plan.md` 的落地改动（工作区未提交）
审查范围：

- `sure/skills/sure_infer/scripts/referenced_datasets.py`（新增）
- `sure/skills/sure_infer/scripts/test_referenced_dataset_mounting.py`（新增）
- `sure/skills/sure_infer/scripts/resolve_eval_input.py`
- `sure/skills/sure_infer/scripts/container_execution.py`
- `sure/skills/sure_infer/SKILL.md`
- `sure/skills/sure_infer/references/dataset_formats.md`
- `sure/skills/sure_infer/schemas/eval_input_resolved.schema.json`

## 1. 结论

**要改**。主体设计正确：解析期读 manifest 并做允许根校验 → 去重后写 `runtime.referenced_datasets` → 启动期用同一个 `_mount()` 入口按规范路径只读挂载。分层干净，新增 17 个测试全绿。

但有两点必须先处理：

1. **功能性前提未验证**：只读 `extras/<version_id>/`，若真实 compose 数据的 manifest 不在该 `version_id` 目录下（例如只有 `extras/TEMP_VERSION/`），修复完全不生效且静默失败。
2. **文档结构被改坏**：`dataset_formats.md` 新章节插错位置，把原 `Source pool` 章节劈成两半。

## 2. 逐条问题

### 2.1 [必改] `extras/<version_id>/` 与真实数据的版本目录可能对不上

- 位置：`sure/skills/sure_infer/scripts/referenced_datasets.py:29-35`、`sure_eval/datasets/source_resolver.py:256-282`
- 现象：manifest 路径固定为 `<source_root>/extras/<version_id>/selection_manifest.jsonl`；`version_id` 由 `resolve_site_source_entry` 决定（`sample_files/<目录名>`、显式 `@version`、或 flat 布局的 `"unversioned"`）。
- 为什么是问题：方案第 5 节写「对于当前 compose 数据集，还存在 `extras/TEMP_VERSION/selection_manifest.jsonl`」。如果真实 compose 数据集解析出的 `version_id` 是正式版本、而 manifest 只存在于 `extras/TEMP_VERSION/`，则 `manifest.is_file()` 为 False → `status="absent"` → 不挂载、**也不报错**，原始「零预测」故障原样复现，且没有任何失败信号。
- 附带：两份文档都断言「a temporary version is not selectable」（`dataset_formats.md:55-56`、`SKILL.md` 同义），但按 `source_resolver.py:256-282`，`TEMP_VERSION` 只要是 `sample_files/` 下的目录名就能被正常选中。这句论断不成立。

### 2.2 [必改] `dataset_formats.md` 新章节插错位置

- 位置：`sure/skills/sure_infer/references/dataset_formats.md:49`（新章节 `## Referenced source datasets`）
- 现象：原本属于 `## Source pool (ds_pool)` 的内容被新章节隔断，现在挂到了新章节下：
  - `dataset_formats.md:60-65`：`There is no README.md … ds.jsonl is the only metadata carrier` + ds.jsonl 示例
  - `dataset_formats.md:67`：`### sample.jsonl record`
  - `dataset_formats.md:101`：`### ds.jsonl metadata`
- 为什么是问题：这三块描述的是 source pool 布局，与 `extras/` 引用源无关，现在层级和语义都错了，读者会以为是「引用源数据集」的字段说明。

### 2.3 [小] manifest 读失败抛裸 traceback，不是干净退出

- 位置：`sure/skills/sure_infer/scripts/referenced_datasets.py:46`（`manifest.open()`）
- 现象：只捕获 `json.JSONDecodeError`，未捕获 `OSError`（权限不足 / 文件损坏）。
- 为什么是问题：`resolve_eval_input.py:1066` 的 `main()` 只 catch `ReferencedDatasetError`，不可读 manifest 会以 exit 1 + traceback 结束，不符合方案「格式非法时直接失败」的干净退出（exit 2）。

### 2.4 [小] 启动器对 `runtime.referenced_datasets` 只校验形状，不重校允许根

- 位置：`sure/skills/sure_infer/scripts/container_execution.py:131-162`
- 现象：只检查 `host_root` / `source_dataset_root` 是绝对路径，不重跑 `allowed_source_roots`。
- 为什么是问题：正常流程中该数据由 `resolve_eval_input` 写出，没问题；docstring 也承认可被 stored eval_input 调用。与现有数据集挂载对 `source_root` 的信任级别一致，属可接受，但若 `eval_input_resolved.json` 来自不可信存储，可挂载任意只读宿主目录。

### 2.5 [小] 复用了 `sure_eval` 私有函数

- 位置：`sure/skills/sure_infer/scripts/referenced_datasets.py:18`（`_match_source_root`）
- 为什么是问题：复用匹配逻辑本身正确，但绑定了下划线私有符号，上游重构会静默破坏。

### 2.6 [小] 缺解析层集成测试

- 现象：`collect_referenced_datasets` 与 `build_local_container_command` 各有单测，但没有测试真正跑 `build_payload`，验证 `datasets[*].selection_manifest` + `runtime.referenced_datasets` 被写出、坏引用让进程 exit 2。

### 2.7 [小] 方案 §6.1 的「规范路径 → 宿主路径」未实现

- 位置：`sure/skills/sure_infer/scripts/referenced_datasets.py:67`（`Path(value).resolve()` 直接当宿主路径）
- 为什么是问题：实现把 manifest 里的规范路径直接当宿主 Docker source。与现有数据集 `source_root` 挂载方式一致，本部署大概率没问题；但若规范命名空间与宿主挂载点不同（方案举例 `/hpc_stor08/...` vs `/mnt/gpfs_dataset_hdd/...`），会因宿主路径不存在而挂载失败。

### 2.8 [流程] 无 openspec change 文档

- 现象：仓库内其他特性走 `openspec/changes/<name>/`，本次只有 `docs/spec/`。按项目习惯确认是否需要补，或明确本类改动不走 openspec。

### 2.9 [无关但工作区有] 子模块指针漂移

- 位置：`sure/external/sure-evaluation` 工作区在 `b3ba182`，父仓 HEAD 记录 `cb9f6bb`，且 `cb9f6bb` 不是 `b3ba182` 的祖先（分叉）。
- 建议：不要和本次改动一起提交，先确认状态来源。

## 3. 建议改法

1. **2.1**：先用一个真实 compose 数据集确认 `version_id` 解析值与 manifest 实际目录。二选一：
   - 若 manifest 本就在 `extras/<version_id>/` → 删除文档里「temporary version is not selectable」的错误论断，只保留「只读请求版本目录」这一事实。
   - 若只在 `extras/TEMP_VERSION/` → 按方案补显式回退：优先请求版本目录，允许时再回退 `TEMP_VERSION`，并校验 `source_version` 与请求版本关系；同时把回退写成可观测（`status` 记录用了哪个目录）。
2. **2.2**：把 `dataset_formats.md:49-58` 整段移到 `### ds.jsonl metadata` 之后（现第 106 行后、`## OpenBench` 之前）。
3. **2.3**：`_read_manifest` 把 `open/read` 的 `OSError` 包成 `ReferencedDatasetError`，并加一条不可读 manifest 的测试。
4. **2.4**：可在 `referenced_dataset_mounts_from_eval_input` 里顺带重跑 `_match_source_root`（成本很低），或至少把「信任 eval_input」写进 docstring 的风险说明。
5. **2.5**：在 `source_resolver` 暴露公开包装后改用；或保留并在注释里写明耦合。
6. **2.6**：补一条 `build_payload` 级测试：构造带 manifest 的数据集 → 断言两个字段落盘；构造越界引用 → 断言 `ReferencedDatasetError`/exit 2。
7. **2.7**：与 2.1 一并到真实节点确认；若确需映射，复用现有数据源解析逻辑补一层 canonical→host 解析。

## 4. 未验证 / 没把握

- **未验证**：真实 compose 数据集的 `version_id` 与 manifest 实际目录（决定 2.1 是否真 bug）。本地无 HPC 数据 (`/hpc_stor08` 不存在)，无法实证。
- **未验证**：规范路径是否等于宿主路径（2.7）。仅从现有数据集挂载逻辑推断一致，未在真实节点跑过。
- **未验证**：`extras/<version_id>/` 命名已有先例（`dataset_manager.py:1843` 的 `trial_manifest.json` 同样用 `ref.version_id` 且无 TEMP 回退），这可作为「不实现回退也符合现有约定」的支持证据，但两处业务语义不同，不能直接等同。
- **已核实**：`runtime` 在 schema 中 `additionalProperties: true`，新增 `referenced_datasets` 不会被 schema 拒绝；`datasets[]` 是 `additionalProperties: false`，已补 `selection_manifest`，问题排除。

## 5. 验证证据

```
python -m pytest test_referenced_dataset_mounting.py -q
→ 17 passed

python -m pytest test_deployment_binding.py test_eval_input_policy.py test_dataset_identity.py \
  test_dataset_alias.py test_container_harness_regression.py test_parallel_predictions.py \
  test_gpu_partition_launch.py test_harness_runtime_contract.py test_payload_artifact_paths.py -q
→ 176 passed, 7 failed

py_compile(referenced_datasets.py, container_execution.py, resolve_eval_input.py) → ok
schema JSON 解析 → ok
git diff --check → ok
```

7 个失败均为本机 Windows 8.3 短文件名（`SHENGY~1.XIA` vs `shengyun.xiang`）导致：`_mount` 内 `.resolve()` 会展开长名，而断言里保留了短名。失败断言全在对比短/长临时路径，diff 未触碰这些路径，**判定为改动前已存在的环境问题**，非本次引入。

## 6. 处置（2026-11-23）

| 条目 | 处置 | 落点 |
| --- | --- | --- |
| 2.1（措辞） | 已改。删掉「a temporary version is not selectable」这一错误论断，改为「只读 resolved `version_id` 目录，无 `extras/TEMP_VERSION` 回退」 | `references/dataset_formats.md` 的 `### Referenced source datasets (extras/)`、`referenced_datasets.py:29-33` docstring |
| 2.1（回退行为） | **不实现回退**，按需求方 2026-11-23 的决定：`TEMP_VERSION` 是临时版本，用户选不到，能选到的都是真正带版本的 | 行为不变；`selection_manifest_path()` 仍只拼一个路径 |
| 2.1（数据前提） | **已由需求方确认，关闭**：真实数据的 `selection_manifest.jsonl` 就在真实版本号目录下；`extras/TEMP_VERSION/` 只对应尚未发布、正在编辑的版本，不在选版范围内 | 无需改代码，`selection_manifest_path()` 只认 resolved 版本目录即正确 |
| 2.2 | 已修。章节移到 `### ds.jsonl metadata` 之后、`## OpenBench` 之前，并降为 `###`，`There is no README.md…`、`### sample.jsonl record`、`### ds.jsonl metadata` 回到 `## Source pool (ds_pool)` 之下 | `references/dataset_formats.md` |
| 2.3 | 已修。`_read_manifest` 先单独 `open()` 并 catch `OSError`，报 `ReferencedDatasetError("<path>: cannot be read (…)")`；新增用例 `test_an_unreadable_manifest_is_reported_as_a_resolution_error` | `referenced_datasets.py:43-50`、测试文件 |
| 2.4 | 已在 docstring 明确「信任边界」：allowed-root 校验发生在输入解析，本函数只复核形状，因此传入的 eval_input 必须来自 `resolve_eval_input` 或等价校验过的来源 | `container_execution.py:132-137` |
| 2.5 | 保留跨模块私有名 `_match_source_root`，并在 import 处写明耦合：改名/删除会立刻 import 失败，而不是静默放过越界路径 | `referenced_datasets.py:18-21` |
| 2.6 | 已补 `EvalInputIntegrationTests`（3 例）：`build_payload` 同时落 `datasets[*].selection_manifest` 与 `runtime.referenced_datasets` 并驱动 `build_local_container_command` 生成 readonly 挂载；`main()` 写出文件后两字段仍在；越界引用走 `main()` 返回 2 且 stderr 含 `allowed_source_roots` | 测试文件 |
| 2.7 | **已由需求方确认，关闭**：推理节点上清单里的规范路径就是宿主路径，不需要 canonical→host 映射。当前把清单路径直接当宿主路径用的做法成立 | 无需改代码 |
| 2.8 | **已由需求方决定：不补** openspec change（`openspec/config.yaml` 是空模板，`sure/AGENTS.md` 也未要求）。本次只保留 `docs/spec/` 下的方案与 review | — |
| 2.9 | 已确认预存在且与本次无关，**不与本次改动一起提交**：`git -C sure/external/sure-evaluation merge-base --is-ancestor cb9f6bb b3ba182` → exit 1（已分叉）；子模块工作区 `b3ba182`（branch `main-oref`），父仓 gitlink `cb9f6bb` | — |

验证（改动后重跑）：

```
python -m unittest test_referenced_dataset_mounting
→ Ran 21 tests … OK
python -m py_compile referenced_datasets.py container_execution.py resolve_eval_input.py \
  test_referenced_dataset_mounting.py
→ ok
```

## 7. 待确认项（已全部闭环，2026-11-23）

1. **manifest 所在目录 — 已确认**：真实 compose 数据集的 `selection_manifest.jsonl` 位于真实版本号目录 `extras/<版本号>/`；`extras/TEMP_VERSION/` 下也可能有，但那是尚未发布、正在编辑的版本，不在选版范围内，因此不考虑。→ 现有实现（只认 resolved `version_id` 目录、无回退）正确，不改。
2. **规范路径是否等于宿主路径 — 已确认**：推理节点上两者一致，不需要 canonical→host 映射。→ 现有实现成立，不改。
3. **openspec change — 已决定不补。**

结论：方案与实现按 review 第 6 节收口，无遗留代码改动。

