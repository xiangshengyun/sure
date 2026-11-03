# develop 分支对比与完备性分析（2026-11-03）

对比 `develop`（`31ef1150`）与 `main`（`cf8d389e`, tag `m-0.0.6`），审查 develop
相对 main 的增量改动是否完备。

## 结论摘要

截至提交 `31ef1150`，develop 相对 main 的**净改动为 19 个文件 / +1699 −22，全部在 `sure/skills/`**，实质内容
是一件事：**给容器交付补上"路径契约"** —— 模型包在镜像里被挂到哪个绝对路径，Dockerfile、
镜像实际 ENV、`config.yaml server.env` 三处必须一致。

方向正确、实现质量高、测试充分（新增 55 个用例全通过，`npm run check` 12/12 绿），但
**修复前不完备**：同一套契约存在三份独立实现、口径互不一致，实测能构造出
"onboard 通过 + approval 通过 + infer 拒绝"的组合 —— 也就是它自己声称要消灭的那类
"跑完全程才发现"的失败。

**复核结论（修复后的工作区，2026-11-03）**：🔴 三份实现已收敛成
`deployment_contract.validate_runtime_path_env` 一处，approve / infer 的判定与错误文本
**逐条一致**（实测 15 组声明全部同进同退）。但本轮改动引入了一个**新的回归**：
`container_execution.py:16` 在模块导入期把 `sure_onboard/scripts` 插到 `sys.path` 最前，
遮蔽了 infer 侧同名的 `docker_runtime`，导致推理侧**静默忽略 `SURE_EVAL_DOCKER_BIN`**
（改用 `SURE_ONBOARD_DOCKER_BIN`），并新增 5 个测试失败。详见 §三·复核新增。

**本文档的边界**：这一轮是**复核**——代码一行没改（工作区里那 5 个改动文件是上一轮
修复留下的，未提交）。新发现的问题只做记录，修法写进 §三·复核新增与 §六·建议动作，
是否实施由维护者决定。

## 一、分支拓扑：真实差异比 commit 数小得多

| 关系 | 结果 |
| --- | --- |
| `main` 是否 `develop` 的祖先 | 是（`git rev-list --count develop..main` = 0，合并是 fast-forward） |
| `develop` 领先 `main` | 32 个 commit |
| `develop` 领先 `upstream/harness-tui-agent` | 59 个 commit |
| **净树差异** | **19 文件 / +1699 / −22** |

32 个 commit 里只有 7 个真正产生内容差异，即 `fix/container-runtime-contract-20261027`
那条线加收尾提交：

```
a4c06a8a fix(agent): enforce container runtime paths and smoke the approved server
d21f4e2e fix(agent): repair container approval server smoke
f54a4c09 fix(agent): reject a baked MODEL_PATH outside the model mount
b00a0456 fix(agent): start approval container smokes with --entrypoint
29e4824a fix(agent): verify the image's own WORKDIR and ENV, and partition the server smoke
ac6dfe6e fix(agent): drive the approved tool and preflight infer paths
31ef1150 fix(agent): align container approval and inference contracts
```

其余 18 个（RIR 集成、TTA 集成、SURE skill bridge、engine bump、Worker device 归一化等）在
main 上已经通过 `upstream/harness-tui-agent` 有了同内容副本；两次
`Merge branch 'main' into develop`（`81360eb5`、`c41d21ba`）之后它们在树上变成空操作。

`git cherry main develop` 仍把这 18 个标成 `+`（基线不同导致 patch-id 不匹配），所以
`git log main..develop` 会显示 32 行噪音，其中 18 行是重复内容。

**历史整理建议不作为合并前置条件：main 已是 develop 的祖先，最终树差异没有重复代码。是否整理重复语义 commit 属于团队历史策略，不影响功能合并。

## 二、改动的四层

### onboard

- `sure/skills/sure_onboard/schemas/docker_validation.schema.json`
  `model_runtime` 新增必填 `working_dir` + `server_command`，新增可选 `external_command_paths`。
- `sure/skills/sure_onboard/scripts/deployment_contract.py:432`
  新增 `validate_container_runtime_contract()`：解析 Dockerfile 的 `FROM/WORKDIR/ENV`，
  只认最后构建阶段，支持具名 stage 继承、相对 WORKDIR 解析、`${VAR}` 延迟到运行时。
- `sure/skills/sure_onboard/scripts/deployment_contract.py:411`
  新增 `validate_image_runtime_env()`：对 `docker image inspect` 拿到的真实 `Config.Env`
  再跑一遍同规则（ENV 可能来自基础镜像或 ARG 展开，Dockerfile 文本里看不到）。
- `sure/skills/sure_onboard/scripts/check_container_package.py`
  现在**总是**拿 digest-pinned 镜像的真实 `Config.WorkingDir` 去比
  `model_runtime.working_dir`（不再只在 Dockerfile 声明 WORKDIR 时才比）。
- `sure/skills/sure_onboard/scripts/write_runtime_inventory.py`
  `runtime = validated_model_runtime` 取代了原来的 `validation.get("runtime")`。
  **这是一个真 bug 修复**：schema 里根本没有顶层 `runtime` 键，旧代码永远落到
  `"/workspace/model"` 兜底。
- `sure/skills/sure_onboard/scripts/check_runtime_inventory.py`
  新增 `container.working_dir == mount_policy.model_bundle.target`。
- `sure/skills/sure_onboard/scripts/stage_model_artifacts.py`
  把 `server_smoke_input.json` 加进可选产物。链路完整：`run_validate` 读 run 目录 →
  staging 拷进 bundle → candidate 整树 copytree → approval 读 `candidate/artifacts/`。

### approve（`sure/skills/sure_approve/scripts/approval_core.py`，+467）

- `verify_server_contract` 新增容器分支（`:889`）：`server.working_dir` vs 已批准的
  `working_dir`；`SURE_MODEL_DIR`/`MODEL_DIR` vs 模型挂载点（`:899`）；
  `PYTHONPATH`/`PYTHONHOME` 的"改根目录"检测（`:912`）。
- 新增 `_verify_container_server()`：在 digest-pinned 镜像里真起一次 MCP/JSONL server，
  **真的调一次工具**，用 `run_server_smoke.py` 判定，不退化到 `--list-only`。
- `--entrypoint` 修掉镜像自带 ENTRYPOINT 被叠加成 `python3 python3 validate.py`。
- 判定改看**阶段产物**而不是 exit code（`_validation_evidence`）—— 本地容器 CLI 有
  "容器退出 1 但返回 0" 的坑。
- 收据新增 `image_config`（镜像解析后的 `WorkingDir`/`Env`/`Entrypoint`）+ 凭据脱敏的环境快照。

### infer

- `sure/skills/sure_infer/scripts/deployment_binding.py`
  `external_command_paths` 缺省即"旧 inventory"，不判；存在才判。
- `sure/skills/sure_infer/scripts/container_execution.py:222`
  新增 `validate_infer_path_contract()`：推理前置校验 `server_command` 与
  `config.yaml server.env` 的路径。

### 文档

`sure_onboard/SKILL.md`、`references/playbooks/env_docker.md`、
`references/specs/wrapper_contract.md`、`sure_approve/SKILL.md`。

## 三、完备性缺口清单

### 🔴 高：三份契约实现，口径互不一致 —— 已修复

`deployment_contract.py:367` `_validate_runtime_path_env`（onboard）、
`approval_core.py:899/912`（approve）、`container_execution.py:222`（infer）此前是同一套规则的
三份独立代码；本次修复已抽出共享校验函数 `validate_runtime_path_env`，三个闸门统一调用。

修复前实测三个闸门对同一份 `config.yaml server.env` 的反应：

| 声明 | onboard 镜像 ENV | approve config | infer config |
| --- | --- | --- | --- |
| `MODEL_PATH: /opt/model/w` | 拒 | 拒 | 拒 |
| `PYTHONHOME: /opt/model` | 拒 | 拒 | 拒 |
| `PYTHONPATH: /opt/model` | 拒 | **过** ❌ | 拒 |
| `MODEL_DIR: /opt/models` | 拒 | 拒 | 拒 |

（`working_dir = /workspace/model`，`model_mount.target = /workspace/model`）

后果：

1. **`approval_core.py:899` 的 key 列表少了 `MODEL_PATH`** —— onboard 和 infer 都拒。
2. `PYTHONHOME` 曾由 onboard 漏检。
3. `PYTHONPATH` 三处判定顺序与错误文本各不相同。

**修复后实测（15 组声明 × 3 个闸门）**：approve 与 infer **逐条一致**，连错误文本都相同；
onboard 走的是镜像 ENV 通道（`validate_image_runtime_env`），判定规则相同、措辞带
`image ENV` 前缀。统一后的规则：

| 变量 | 判定 |
| --- | --- |
| `MODEL_PATH` | 必须**包含**在挂载点下（权重常在子目录） |
| `MODEL_DIR` / `SURE_MODEL_DIR` | 必须**等于**挂载点 |
| `PYTHONPATH` / `PYTHONHOME` | 仅当路径含 `model` 段时判，且必须在挂载点下 |
| 其它键 | 不判（镜像自带的路径合法） |

路径先归一化（`..` 不能逃逸），`${VAR}` 延迟展开的值跳过。**这次是真的收成一份实现了。**

### 🟠 中：破坏性变更没有迁移说明

`write_runtime_inventory.py` 换成真实 `working_dir` 之后，**所有存量
`runtime_inventory.json` 的 `container_runtime.working_dir` 都是旧的 `/workspace/model`
兜底值**，新的 `check_runtime_inventory.py` 要求它等于 `model_bundle.target`，存量的会挂。
`sure_approve/SKILL.md` 写了"必须重新 onboard"，但 `sure_onboard/SKILL.md` 一句迁移提示
都没有（grep `re-onboard|重新 onboard|存量` → 零命中）。

### 🟠 中：infer 侧的新前置校验没有任何文档 —— 已补

`container_execution.py:222` 会因为 `config.yaml server.env` 里的绝对路径直接拒绝一次推理。
修复前 `sure_infer/SKILL.md` 对
`MODEL_PATH|working_dir|model_mount|external_command_paths|PYTHONPATH` **零命中**。
现已补 `## Container Runtime Path Contract` 一节，写明挂载点是唯一模型根、
`external_command_paths` 的用途、`..` 先归一化再判定。

遗留：该节把 `PYTHONPATH`/`PYTHONHOME` 一概写成"对照已批准的挂载点检查"，而实际规则是
**只有路径含 `model` 段时才检查**（`/usr/lib/python` 放行）。措辞按实际规则收紧即可。

### 🟠 中：`--entrypoint` 只在 approve 侧修，onboard 侧没写

`approval_core.py` 两处 smoke 都补了 `--entrypoint`。但 onboard 自己的容器校验
（`run_validate.py:444/738` 的 `rewrite_container_env`）**只是保留** agent 写的
`--entrypoint`，不会补；`references/playbooks/env_docker.md` 第 4 步"Run Model Runtime
... checks inside that image" 也没要求 `--entrypoint`。同一类缺陷在 onboard 侧留着。

### 🟡 低-中：`_container_argument` 的兜底会把越界路径当字面量 —— 已修，但判定偏严

`approval_core.py` 里 `_container_argument` 抛 `ApprovalError`（路径不在 bundle 内）时，
`_fixture_arguments` 原先直接 `except ApprovalError: arguments[name] = value` 当成 prompt
传下去：一个真实的越界绝对路径被塞给工具，报错变成"candidate server failed under the
approved container mount"而不是"这个路径不在 bundle 内"。

现已改为越界即抛（绝对路径，或含 `/`、`\`）。**遗留风险**：字面量提示词只要含 `/`
（例如 `"ASR/NLU 模型"`、`"https://..."`）现在也会被拒。`/outside/input.wav` 这类绝对路径
有测试覆盖，含斜杠的字面量没有。判定可再收窄到"绝对路径"。

### 🟡 低：其余

- `write_runtime_inventory.py` 调 `validate_container_runtime_contract` 前没确认 Dockerfile
  存在（`check_container_package.py:160` 有），缺文件时抛的是未包装的 `FileNotFoundError`。
- `verify_live_image` 现在总比 WORKDIR，基镜像没设 WORKDIR 时 `Config.WorkingDir` 是 `""`，
  `normpath("")` = `"."`，报错文案会是 `WORKDIR '' disagrees with ...`，不如写成
  "镜像未声明 WORKDIR"。
- `container_execution.py:230` 的注释"`working_dir` is not required to equal the target
  (sure_trans mounts the model elsewhere)"已过时：`write_runtime_inventory.py` 现在强制两者
  相等。trans 走自己的 writer，不受影响，但注释会误导。

## 三·复核新增（本轮修复引入 / 遗留）

### 🔴 高：`container_execution.py:16` 遮蔽 infer 侧的同名模块

```python
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sure_onboard" / "scripts"))
from deployment_contract import validate_runtime_path_env   # ← 顺带遮蔽了 docker_runtime
```

`sure_infer/scripts` 与 `sure_onboard/scripts` 有 **7 个同名模块**：
`build_run_digest` / `check_memory_extraction` / `check_memory_index` /
`docker_runtime` / `publish_memory` / `test_docker_runtime` / `test_model_registry`。
把 onboard 目录插到 `sys.path` **最前**，这些名字在 infer 进程里全部指向 onboard 版本。

已实测确认（`container_execution` 导入后）：

```
resolved docker_runtime file: .../sure_onboard/scripts/docker_runtime.py
has DOCKER_BIN_ENV(SURE_EVAL_DOCKER_BIN): False
has ONBOARD_DOCKER_BIN_ENV: True
```

**生产影响**：`container_execution.py:23` 和 `check_execution_surface_compliance.py:36`
的 `from docker_runtime import resolve_docker_binary` 拿到的是 onboard 版本，于是
推理侧的 Docker 路径覆盖变量 **`SURE_EVAL_DOCKER_BIN` 被静默忽略**，改认
`SURE_ONBOARD_DOCKER_BIN`。两个模块只差一个环境变量名，所以不会有报错——正因如此更危险。

**测试影响**：`sure_infer` 新增 5 个失败（`test_docker_runtime` 全红，报
`module 'docker_runtime' has no attribute 'DOCKER_BIN_ENV'`）。

**仓库里已有的正确写法**：`deployment_contract.py:167` 的 `_server_protocol_module()`
在函数内**惰性**插入路径，docstring 明说"the path insert happens per call, so it
cannot shadow a same-named module elsewhere on the path for the whole process"。
本轮修复恰好复制了它警告的那种写法。

两条修法，二选一：

```python
# A. 惰性插入，抄仓库里已有的 _server_protocol_module()
def _onboard_contract():
    scripts = Path(__file__).resolve().parents[2] / "sure_onboard" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.append(scripts)
    import deployment_contract
    return deployment_contract

# B. 命名空间包导入，完全不碰 sys.path（repo root 已在 parents[4] 上）
from sure.skills.sure_onboard.scripts.deployment_contract import validate_runtime_path_env
```

B 更干净：`deployment_contract.py` 只依赖标准库，实测 `import` 成功。
`approval_core.py:30` 的 `sys.path.append(str(ONBOARD_SCRIPTS))` 是安全的 ——
approve 与 onboard 两个目录**没有**同名模块。

### 🟡 低：`_refuse_renamed_bundle_root` 成了死代码

`approval_core.py:718` 定义、**零调用点**（全仓 grep 只命中定义本身）。
它原来守的"改名根"规则已被共享函数的包含判定覆盖（`/model` 不在 `/workspace/model`
之下 → 拒），消息文案换了但拦截没丢。按"删除优于新增"应当删掉。

### 🟡 低：infer 侧 `MODEL_DIR`/`SURE_MODEL_DIR` 由"包含"收紧为"相等"

旧 infer 用 `_posix_within`（包含），共享函数用相等（`!= working_dir` 即拒）。
`/workspace/model/sub` 这类声明现在会被拒。这与 approve 侧旧行为一致（approve 一直
是相等），所以是**有意对齐**，不是 bug；但存量 bundle 若声明了子目录会在推理时新被拒，
需要一条迁移说明。

## 四、修复后验证结果

复核跑在**当前工作区**（含本轮未提交改动），`TEMP` 指向长路径以避开 8.3 短路径噪声：

| 检查 | 结果 |
| --- | --- |
| `npm run check` | **12/12 通过** |
| `sure_approve` 全量 | **78 tests OK**（较上一轮 +2，即新增的两个用例） |
| `sure_infer` 全量 | 777 tests，**6 errors** = 5（本轮**新引入**的 `docker_runtime` 遮蔽）+ 1（存量） |
| `sure_onboard` 全量 | 183 tests，1 失败（存量） |
| 三闸门一致性实测 | 15 组声明 × 3 闸门，approve/infer **逐条一致** |

存量失败（**在 `main` 上完全相同**）：

- `test_evaluation_runtime::EvaluationLockTests::test_crlf_checkout_uses_the_same_pyproject_identity`
  —— Windows CRLF checkout
- `test_python_delivery_contract::PythonDeliveryContractTests::test_package_none_with_installed_adapter_passes_the_inventory_gate`

基线对比方法：`git worktree add <path> main` 拉一份 main 出来跑同样的用例，失败用例
名单 `diff` 结果为 IDENTICAL。

另外注意：Windows 上 `TEMP` 指向 8.3 短路径（`SHENGY~1.XIA`）时，会额外炸 7 个与路径拼写
相关的用例；把 `TEMP` 指到长路径后全绿。**这 7 个也是 main 上同样失败的**，不是本分支引入的。

结论：**分支本身**没有引入新的测试失败，CI 全绿；**本轮修复**引入的 5 个失败来自
`container_execution.py` 的 `sys.path` 遮蔽（见 §三·复核新增），修掉即可。

## 五、复现契约分歧（修复后仍可跑，且能看出遮蔽）

```python
import sys, tempfile, os
from pathlib import Path

REPO = Path(r"D:/develop/code/aispeech/aiagent/sure/github/sure-xsy")
for p in ("sure/skills/sure_onboard/scripts", "sure/skills/sure_infer/scripts",
          "sure/skills/sure_approve/scripts", "sure/runtime/harness"):
    sys.path.insert(0, str(REPO / p))
sys.path.insert(0, str(REPO))

import deployment_contract, container_execution, approval_core

WD = "/workspace/model"
bundle = Path(os.path.join(tempfile.gettempdir(), "sure_probe_bundle"))
bundle.mkdir(exist_ok=True)
(bundle / "config.yaml").write_text(
    "task: asr\nserver:\n  command: [python, server.py]\n  protocol: mcp\n"
    f"  working_dir: {WD}\n  env:\n    MODEL_PATH: /opt/model/w\n"
    "tools:\n  - name: predict\n    input_schema:\n      type: object\n"
    "      properties:\n        audio_path: {type: string}\n", encoding="utf-8")

container = {"model_mount": {"target": WD}, "working_dir": WD,
             "server_command": ["python", "server.py"], "external_command_paths": []}
binding = {"runtime_kind": "container", "target_image_ref": "r@sha256:" + "a" * 64,
           "container": container}

try:
    approval_core.verify_server_contract(bundle, "container", binding)
    print("approve: REFUSED")
except approval_core.ApprovalError as e:
    print("approve: REFUSED:", e)

try:
    container_execution.validate_infer_path_contract(bundle, container)
    print("infer:   PASSED")
except ValueError as e:
    print("infer:   REFUSED:", e)

# 遮蔽检查：infer 进程里的 docker_runtime 必须是 infer 自己那份
import docker_runtime
print("docker_runtime:", docker_runtime.__file__)
print("has SURE_EVAL_DOCKER_BIN:", hasattr(docker_runtime, "DOCKER_BIN_ENV"))
```

预期输出（修复遮蔽后）：

```
approve: REFUSED: config.yaml server.env MODEL_PATH '/opt/model/w' disagrees with
         model_runtime.working_dir '/workspace/model'
infer:   REFUSED: config.yaml server.env MODEL_PATH '/opt/model/w' disagrees with
         model_runtime.working_dir '/workspace/model'
docker_runtime: .../sure/skills/sure_infer/scripts/docker_runtime.py
has SURE_EVAL_DOCKER_BIN: True
```

当前工作区的实际输出（遮蔽未修）：

```
docker_runtime: .../sure/skills/sure_onboard/scripts/docker_runtime.py
has SURE_EVAL_DOCKER_BIN: False
```

## 六、建议动作

以下全部**尚未实施**——本轮只做复核与记录，没有改动任何代码。

1. **修 `container_execution.py:16` 的 `sys.path` 遮蔽**（本轮新引入，最高优先级）。
   抄 `deployment_contract.py:167` 的惰性插入写法，或改用命名空间包导入（两条修法见
   §三·复核新增）。
2. 删掉 `approval_core.py:718` 的 `_refuse_renamed_bundle_root`（死代码，规则已被共享函数覆盖）。
3. `sure_onboard/SKILL.md` 补一句存量 inventory 需重新 onboard
   （`write_runtime_inventory.py` 换成真实 `working_dir` 后，存量的
   `container_runtime.working_dir` 还是旧的 `/workspace/model` 兜底值，
   新的 `check_runtime_inventory.py` 要求它等于 `model_bundle.target`，存量的会挂）。
4. `env_docker.md` 第 4 步补"`docker run` 必须显式 `--entrypoint <interpreter>`"。
5. `write_runtime_inventory.py` 调 `validate_container_runtime_contract` 前确认 Dockerfile 存在。
6. `verify_live_image` 的 WORKDIR 空值文案改成"镜像未声明 WORKDIR"。
7. `sure_infer/SKILL.md` 的新一节把 `PYTHONPATH`/`PYTHONHOME` 的判定写准：
   只有路径含 `model` 段时才检查。
8. `approval_core.py` 的 `_authored_smoke_arguments` 兜底判定可再收窄到"绝对路径"，
   免得含 `/` 的字面量提示词被误拒；或补一条含斜杠字面量的用例。
9. 补一条跨阶段契约测试：同一份 `config.yaml server.env` 喂给 onboard / approve / infer
   三个闸门，断言三者的判定与错误文本一致 —— 这正是本分支想消灭的那类漂移。
10. 如需整理历史，可单独规划 rebase；不作为功能合并前置条件。

## 七、值得保留的实现

review 时不要改掉这几处：

- `write_runtime_inventory.py` 的 `runtime = validated_model_runtime` 是真 bug 修复，
  不是风格改动。
- approval 的容器 smoke **真的调工具**、不退化 `--list-only`；fixture 填不满 required
  输入时拒绝而不是丢弃字段。
- 用阶段产物而非 exit code 判定（本地容器 CLI 退出码不可信）。
- 复制进容器的 runner 文件清单与 `run_server_smoke.py` 的实际 import 图**完全吻合**
  （`sure/runtime/{gpu_partition,onboard_gpu,prediction_payload}.py`、
  `evaluation/task_registry.py` + `engine-capabilities.generated.json`，无遗漏、无多余）。
- `runtime_verification.schema.json` 是 `additionalProperties: true`，新增
  `server_smoke`/`image_config` 不需要改 schema。
- `external_command_paths` 的"缺省 = 旧 inventory 不判"保证存量 bundle 不被卡死。
- `deployment_contract.py:167` 的**惰性**路径插入：函数内插路径，只影响调用那一刻，
  不会像模块级 `sys.path.insert(0, ...)` 那样整程遮蔽同名模块。跨 skill 目录引用代码时
  应该照这个写法，别照 `approval_core.py:30` 的 `append`（那是安全的，因为它没有同名模块）。

## 附录：关键代码位置索引

| 位置 | 内容 |
| --- | --- |
| `sure/skills/sure_onboard/scripts/deployment_contract.py:367` | `_validate_runtime_path_env`（母本） |
| `sure/skills/sure_onboard/scripts/deployment_contract.py:421` | `validate_runtime_path_env`（公共入口） |
| `sure/skills/sure_onboard/scripts/deployment_contract.py:426` | `validate_image_runtime_env` |
| `sure/skills/sure_onboard/scripts/deployment_contract.py:447` | `validate_container_runtime_contract` |
| `sure/skills/sure_onboard/scripts/deployment_contract.py:167` | `_server_protocol_module`（惰性插入路径的正确范例） |
| `sure/skills/sure_approve/scripts/approval_core.py:901` | 容器分支调用共享 env 校验 |
| `sure/skills/sure_approve/scripts/approval_core.py:718` | `_refuse_renamed_bundle_root`（**死代码**） |
| `sure/skills/sure_approve/scripts/approval_core.py:1146` | `_verify_container_server` |
| `sure/skills/sure_approve/scripts/approval_core.py:1202/1424` | `--entrypoint` |
| `sure/skills/sure_infer/scripts/container_execution.py:221` | `validate_infer_path_contract` |
| `sure/skills/sure_infer/scripts/container_execution.py:252` | infer 路径契约调用共享 env 校验 |
| `sure/skills/sure_infer/scripts/container_execution.py:16` | **sys.path 遮蔽点** |
| `sure/skills/sure_onboard/scripts/check_runtime_inventory.py:85` | `working_dir == model_bundle.target` |
| `sure/skills/sure_onboard/scripts/write_runtime_inventory.py:229` | `runtime = validated_model_runtime` |
