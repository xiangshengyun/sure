# DOA Model Onboarding Playbook

本文是 `../AGENTS.md` 的 DOA(direction of arrival,声源方位估计)任务补充。

## 1. 任务边界

DOA 在当前 SURE harness 中按"多通道音频帧 -> 声源方位"处理。与 ASR/TTS 不同,
输出的不是文本或音频,而是**每帧的声源方向列表**:

- 输入: `audio_path`,必须是多通道阵列音频(`num_channels >= 2`),且 `num_channels` 必须与参考帧一致。
- 输出: `sources` 数组,每个元素至少包含 `source_id`、`azimuth`(度)与
  `activity`(布尔);3D 任务再加 `elevation`。

最小输出:

```json
{"sources": [{"source_id": "source_0", "azimuth": 30.0, "activity": true}]}
```

`model.spec.yaml` 推荐:

```yaml
task_type: "doa"
io_contract:
  input_type: "audio_path"
  output_type: "sources"
  primary_field: "sources"
  required_fields: ["sources"]
  nonempty_fields: ["sources"]
  json_serializable: true
```

坐标系默认 `array_local_spherical`,角度单位 `degree`。模型若用别的坐标系
(例如以阵列正面为 0 度、顺时针为正),必须在 wrapper 里换算到该约定,不能
在 playbook 或 fixture 里改基准。

## 2. Fixture

共享 fixture 库中的 DOA 代表样例位于:

```text
fixtures/tasks/doa/doa_smoke/
```

索引见 `fixtures/tasks/doa/README.md`。该 fixture 是单帧、双通道、2D 的
最小契约样例:一行 `gt.jsonl` 给出 `recording_id`、`frame_index`、
`timestamp`、`num_channels`、`coordinate_system`、`angle_unit` 与
`sources[].azimuth`。接入新模型时复制这一帧
音频到模型目录,不要修改共享 fixture。

DOA metric namespace:

```text
src/sure_eval/evaluation/tasks/doa/
```

`/sure_onboard` 的本地验证仍以 task-local `validate.py` 检查
import/load/infer/output contract 为最小门槛;正式 DOA 指标必须通过 SURE
evaluation 工具链计算,不允许用自写的角度误差替代。

## 3. 正式评测

DOA 引擎 manifest 声明 8 个默认指标,全部走同一条 `doa_jsonl` 输入契约:

- 平均误差: `mae`(默认)、`rmse`。
- 阈值准确率: `acc_10`、`acc_15`、`acc_30`(角度误差在阈值内的配对比例)。
- 存在性: `localization_recall`、`localization_precision`、`localization_f1`。

`doa_jsonl` 契约的角色是 `reference_jsonl` + `sample_output`,对齐键是
`(recording_id, frame_index)`:预测与参考的键集合必须完全一致,`timestamp`
与 `num_channels` 也必须相同,否则归一化节点直接拒绝,而不是按位置对齐。
聚合方式是 `micro`(配对后微平均),默认阈值 `threshold_deg=10.0`。

推荐入口:

```bash
sure-eval metric describe doa \
  --language any \
  --metric mae \
  --output /tmp/doa_pipeline.json \
  --json
```

doa 是原子单指标任务,一次 `describe` 只收一个 `--metric`;其余 7 个指标各自
`describe` 一次(各对应 `doa.any.<metric>.…` pipeline),CSV 多指标写法会按字面
找不到路由。

```bash
sure-eval metric run \
  --pipeline /tmp/doa_pipeline.json \
  --reference-jsonl fixtures/tasks/doa/doa_smoke/gt.jsonl \
  --sample-output outputs/doa_pred.jsonl \
  --output-dir /tmp/sure_eval/doa_eval \
  --device cpu \
  --json
```

doa 不走 `--samples-jsonl` 机制(那是 TTS/TTA/VC/SE/TSE/RIR 的输入面),必须
用 `--reference-jsonl` + `--sample-output` 两个显式参数。3D 任务给 run 传
`--dimension 3d`,阈值与聚合用 `--threshold-deg` / `--aggregation` 显式传。

`prediction_jsonl`(即 `--sample-output` 指向的文件)每行至少包含:

```json
{"recording_id":"doa_smoke_001","frame_index":0,"timestamp":0.0,"num_channels":2,"coordinate_system":"array_local_spherical","angle_unit":"degree","sources":[{"source_id":"source_0","azimuth":30.0,"activity":true}]}
```

2D 任务只写 `azimuth`;3D 任务补 `elevation`。
没有真实多通道输入的模型不要声称支持 DOA:单通道音频无法确定方位,这类提交
应按 `blocked` 记录,而不是用一个恒定角度凑指标。

## 4. 验证标准

`validation.log` 至少要有:

- `VALIDATE_SPEC passed`
- `VALIDATE_IMPORT passed`
- `VALIDATE_LOAD passed`
- `VALIDATE_CONTRACT passed`

并记录每帧的 `recording_id`/`frame_index`、输出 `sources` 数量、`azimuth`
取值范围、坐标系与角度单位。若已运行正式指标,记录 `report.json`、
`pipeline_description.json` 与 metric backend。

## 5. 新 DOA 模型接入检查表

- [ ] 已读 `../AGENTS.md` 和本文。
- [ ] 输入确实是多通道音频;单通道提交记录为 `blocked`。
- [ ] wrapper 输出 `sources[].azimuth` 且已换算到 `array_local_spherical` / 度。
- [ ] `(recording_id, frame_index)` 与参考帧一一对齐,`timestamp` 与
      `num_channels` 一致。
- [ ] 权重与 runtime cache 都在 model-local `.runtime`。
- [ ] 本地验证通过,帧级输出元信息写入 artifacts。
- [ ] 正式指标通过 `sure-eval metric describe/run` 计算;没有手写角度误差替代。
