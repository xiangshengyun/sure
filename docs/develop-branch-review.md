# develop 分支对比与完备性分析（2026-11-03）

对比 `develop`（`20df1b76`）与 `main`（`cf8d389e`, tag `m-0.0.6`），审查 develop
相对 main 的增量改动是否完备。

## 结论摘要

截至提交 `20df1b76`，develop 相对 main 的**净改动为 20 个代码文件 / +1721 −24，全部在 `sure/skills/`**
（另有本文档 1 个文件），实质内容
是一件事：**给容器交付补上"路径契约"** —— 模型包在镜像里被挂到哪个绝对路径，Dockerfile、
镜像实际 ENV、`config.yaml server.env` 三处必须一致。

方向正确、实现质量高，但初始实现存在跨阶段契约不一致；后续复核又发现模块导入遮蔽问题。改动应按必要性分层，不能把所有防御性增强都视为核心缺陷。
**修复前不完备**：同一套契约存在三份独立实现、口径互不一致，实测能构造出
"onboard 通过 + approval 通过 + infer 拒绝"的组合 —— 也就是它自己声称要消灭的那类
"跑完全程才发现"的失败。

**复核结论（2026-11-03）**：🔴 三份实现已收敛成
`deployment_contract.validate_runtime_path_env` 一处，approve / infer 的判定与错误文本
逐条一致。复核发现的 `sys.path` 模块遮蔽问题已修复：infer 现在使用命名空间导入 onboard 的契约模块，
不会覆盖 infer 自己的 `docker_runtime`。`_refuse_renamed_bundle_root` 死代码也已删除。详见 §三·复核新增。

**本文档的边界**：上一版复核只记录问题；随后已实施 §三·复核新增中的导入遮蔽修复和死代码清理，
并补充了存量 inventory 迁移说明。最新一轮又把剩余的文档/文案缺口补齐
（`env_docker.md` 的 `--entrypoint`、`write_runtime_inventory.py` 的 Dockerfile 存在性检查、
`verify_live_image` 的 WORKDIR 空值文案、`sure_infer/SKILL.md` 的判定描述），
并给共享规则补了直接用例；只剩 §六 第 9 条的取舍待维护者拍板。

**运行期新发现（2026-11-04）**：一次真实 `/sure_approve` 被 `verify_runtime` 阻断。根因是镜像把
产物目录内置到了挂载点之外（`SURE_ARTIFACTS_DIR=/outputs`），审批 smoke 读不到阶段证据，
而容器退出码仍是 0。共享路径契约只校验**读**路径、没校验**写**路径，正是缺口所在；本轮
已把写路径规则补进同一个校验器（打包闸门即拒），并改写了审批失败信息以打印镜像内置 ENV。
详见 §三·复核新增。

## 改动必要性分层

并非近期所有改动都是同等级的“刚需”。应区分核心逻辑修复、交付质量增强和可能过度收紧的兼容性规则：

### 必须保留的核心修复

- 审批冒烟与实际推理使用同一个批准的 Model Python 解释器；否则可能出现 approval 通过、infer 失败。
- `server_smoke_input.json` 与 fixture 参数合并；否则多输入模型或非音频输入模型会被错误拒绝。
- onboard、approval、infer 统一校验 `MODEL_PATH`、`MODEL_DIR`、`SURE_MODEL_DIR`、`PYTHONPATH`、`PYTHONHOME`；否则会出现前一闸门通过、后一闸门拒绝。
- 对容器路径先做 `normpath` 再判断 containment，避免 `..` 绕过挂载边界。
- 使用命名空间导入避免 `sys.path` 遮蔽 infer 侧 `docker_runtime`；否则 `SURE_EVAL_DOCKER_BIN` 可能被静默忽略。

### 合理的交付质量增强

- 容器 approval 阶段真实调用一次工具，而不是只执行 `tools/list`，用于发现“能启动但首次推理失败”的镜像。
- 对 digest-pinned 镜像的实际 `WORKDIR`、ENV、ENTRYPOINT 做校验，避免只相信 Dockerfile 文本。
- `external_command_paths` 作为镜像自带解释器/脚本的显式 allowlist；该 allowlist 不能用于放行模型包越界路径。

这些增强提高交付门禁质量，但不应与核心业务修复混为一谈。

### 需要谨慎控制的收紧规则

- `MODEL_DIR`/`SURE_MODEL_DIR` 强制等于 model mount root 是兼容性收紧，不是所有模型场景下的绝对事实；当前按“模型根目录”语义处理，并要求存量 bundle 重新 onboard。`MODEL_PATH` 仍可指向挂载根下的权重子目录。
- authored smoke input 不应仅因为字符串包含 `/` 或 `\` 就判为路径并拒绝；应优先识别绝对路径、bundle 内相对路径和确实越界的路径，普通业务字符串、URL 或语言/说话人标识不能被误拒。

后续修改应优先保证核心修复，再评估兼容性收紧，避免为低概率问题扩大拒绝范围。

## 一、分支拓扑：真实差异比 commit 数小得多

| 关系 | 结果 |
| --- | --- |
| `main` 是否 `develop` 的祖先 | 是（`git rev-list --count develop..main` = 0，合并是 fast-forward） |
| `develop` 领先 `main` | 34 个 commit（其中 7 个是 merge） |
| `develop` 领先 `upstream/harness-tui-agent` | 61 个 commit |
| **净树差异** | **21 文件 / +2167 / −24**（代码 20 文件 / +1721 / −24，另有本文档 1 个） |

34 个 commit 里只有 9 个真正产生内容差异，即 `fix/container-runtime-contract-20261027`
那条线加两轮收尾提交：

```
a4c06a8a fix(agent): enforce container runtime paths and smoke the approved server
d21f4e2e fix(agent): repair container approval server smoke
f54a4c09 fix(agent): reject a baked MODEL_PATH outside the model mount
b00a0456 fix(agent): start approval container smokes with --entrypoint
29e4824a fix(agent): verify the image's own WORKDIR and ENV, and partition the server smoke
ac6dfe6e fix(agent): drive the approved tool and preflight infer paths
31ef1150 fix(agent): align container approval and inference contracts
a495f657 fix(agent): align shared container path validation
20df1b76 fix(agent): close container contract review gaps
```

其余 18 个（RIR 集成、TTA 集成、SURE skill bridge、engine bump、Worker device 归一化等）在
main 上已经通过 `upstream/harness-tui-agent` 有了同内容副本；两次
`Merge branch 'main' into develop`（`81360eb5`、`c41d21ba`）之后它们在树上变成空操作。

`git cherry main develop` 仍把这 18 个标成 `+`（基线不同导致 patch-id 不匹配），所以
`git log main..develop` 会显示 34 行噪音，其中 18 行是重复内容。

**历史整理建议不作为合并前置条件：main 已是 develop 的祖先，最终树差异没有重复代码。是否整理重复语义 commit 属于团队历史策略，不影响功能合并。

## 二、改动的四层

### onboard

- `sure/skills/sure_onboard/schemas/docker_validation.schema.json`
  `model_runtime` 新增必填 `working_dir` + `server_command`，新增可选 `external_command_paths`。
- `sure/skills/sure_onboard/scripts/deployment_contract.py:447`
  新增 `validate_container_runtime_contract()`：解析 Dockerfile 的 `FROM/WORKDIR/ENV`，
  只认最后构建阶段，支持具名 stage 继承、相对 WORKDIR 解析、`${VAR}` 延迟到运行时。
- `sure/skills/sure_onboard/scripts/deployment_contract.py:426`
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

- `verify_server_contract` 新增容器分支（`:828`）：`server.working_dir` vs 已批准的
  `working_dir`（`:872`）；`server.env` 的路径契约现统一交给共享函数
  `validate_runtime_path_env`（`:877`），覆盖 `MODEL_PATH`/`MODEL_DIR`/
  `SURE_MODEL_DIR`/`PYTHONPATH`/`PYTHONHOME`。
- 新增 `_verify_container_server()`：在 digest-pinned 镜像里真起一次 MCP/JSONL server，
  **真的调一次工具**，用 `run_server_smoke.py` 判定，不退化到 `--list-only`。
- `--entrypoint` 修掉镜像自带 ENTRYPOINT 被叠加成 `python3 python3 validate.py`。
- 判定改看**阶段产物**而不是 exit code（`_validation_evidence`）—— 本地容器 CLI 有
  "容器退出 1 但返回 0" 的坑。
- 收据新增 `image_config`（镜像解析后的 `WorkingDir`/`Env`/`Entrypoint`）+ 凭据脱敏的环境快照。

### infer

- `sure/skills/sure_infer/scripts/deployment_binding.py`
  `external_command_paths` 缺省即"旧 inventory"，不判；存在才判。
- `sure/skills/sure_infer/scripts/container_execution.py:220`
  新增 `validate_infer_path_contract()`：推理前置校验 `server_command` 与
  `config.yaml server.env` 的路径；`server.env` 部分同样调用共享函数
  `validate_runtime_path_env`（`:251`）。

### 文档

`sure_onboard/SKILL.md`、`references/playbooks/env_docker.md`、
`references/specs/wrapper_contract.md`、`sure_approve/SKILL.md`。

## 三、完备性缺口清单

### 🔴 高：三份契约实现，口径互不一致 —— 已修复

`deployment_contract.py:367` `_validate_runtime_path_env`（onboard）、
`approval_core.py:877`（approve）、`container_execution.py:220`（infer）此前是同一套规则的
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

1. **`approval_core.py` 容器分支的 key 列表少了 `MODEL_PATH`** —— onboard 和 infer 都拒。
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

`container_execution.py:220` 会因为 `config.yaml server.env` 里的绝对路径直接拒绝一次推理。
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
有测试覆盖，含斜杠的字面量没有。

**本轮决定不改**：收窄到"绝对路径"会让**相对** fixture 路径重新被当字面量传给工具
（`_container_argument` 用 `Path(value).resolve()`，相对值是按**当前工作目录**解析的，
不在 bundle 内 → 抛 → 落到字面量分支），而服务器在容器里按自己的 WORKDIR 解析相对路径，
有时反而是对的。现在的取舍是：含 `/` 的越界路径**响亮地拒**，错误信息已经说明
"the container mounts only the bundle, at `<target>`"，操作者把 fixture 改写成
bundle 内的绝对路径即可。代价是含 `/` 的**字面量**提示词也会被拒 —— 冒烟 fixture
用得少，是否再收窄由维护者定。

### 🟡 低：其余 —— 已处理

- ✅ `write_runtime_inventory.py` 现在在 `validate_container_runtime_contract` 前确认
  Dockerfile 存在（`check_container_package.py` 有同样的检查），缺文件时给出可读的
  `ValueError`，不再抛未包装的 `FileNotFoundError`。
- ✅ `verify_live_image` 的 WORKDIR 空值文案改成"digest-pinned image declares no WORKDIR"，
  不再是 `WORKDIR '' disagrees with ...`；**WORKDIR 不一致时的原文案保留**
  （`test_docker_delivery_contract.py` 有断言依赖）。
- ⚠️ `container_execution.py:228` 的注释"`working_dir` is not required to equal the target
  (sure_trans mounts the model elsewhere)"已过时：`write_runtime_inventory.py` 现在强制两者
  相等。trans 走自己的 writer，不受影响，但注释会误导。**保留**：它描述的是
  `validate_infer_path_contract` 里 `server_command` 路径用"包含"而非"相等"的规则，
  这一点没变；变的是 `server.env` 的 `MODEL_DIR` 判定。注释应拆成两句，而不是整句删。

## 三·复核新增（本轮修复引入 / 遗留）

### 🔴 高：`container_execution.py`（原 `:16`）遮蔽 infer 侧的同名模块（已修复）

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

**生产影响**：`container_execution.py` 的 `from docker_runtime import resolve_docker_binary`
（现 `:22`）和 `check_execution_surface_compliance.py:36` 的同名 import 拿到的是 onboard
版本，于是推理侧的 Docker 路径覆盖变量 **`SURE_EVAL_DOCKER_BIN` 被静默忽略**，改认
`SURE_ONBOARD_DOCKER_BIN`。两个模块只差一个环境变量名，所以不会有报错——正因如此更危险。

**测试影响**：`sure_infer` 新增 5 个失败（`test_docker_runtime` 全红，报
`module 'docker_runtime' has no attribute 'DOCKER_BIN_ENV'`）。

**仓库里已有的正确写法**：`deployment_contract.py:166` 的 `_server_protocol_module()`
在函数内**惰性**插入路径，docstring 明说"the path insert happens per call, so it
cannot shadow a same-named module elsewhere on the path for the whole process"。
本轮修复恰好复制了它警告的那种写法。

修复方案：已采用命名空间包导入，不再修改 `sys.path`：

```python
from sure.skills.sure_onboard.scripts.deployment_contract import validate_runtime_path_env
```

该修复保留 infer 侧 `docker_runtime` 的正常解析；`test_docker_runtime.py` 的 5 个新增错误已消失。

命名空间包导入可行是因为 `deployment_contract.py` 只依赖标准库，且
`sure/`、`sure/skills/`、`sure/skills/sure_onboard/`、`.../scripts/` 都没有
`__init__.py`，PEP 420 命名空间包让 `sure.skills.sure_onboard.scripts.deployment_contract`
可以直接 import（repo root 已在 `container_execution.py:15` 的 `sys.path` 上）。
`approval_core.py:30` 的 `sys.path.append(str(ONBOARD_SCRIPTS))` 保持原样是安全的 ——
approve 与 onboard 两个目录**没有**同名模块。

### 🟡 低：`_refuse_renamed_bundle_root` 成了死代码（已修复）

`approval_core.py`（原 `:718`）定义、**零调用点**（全仓 grep 只命中定义本身）。
它原来守的"改名根"规则已被共享函数的包含判定覆盖（`/model` 不在 `/workspace/model`
之下 → 拒），消息文案换了但拦截没丢。按“删除优于新增”已删除。

### 🔴 高：镜像把产物目录指向挂载点之外 —— 运行证据丢失，审批被拒（已修）

**现象**（`/sure_approve` 的 `verify_runtime` 阻断）：

```
candidate runtime verification did not persist a passing result for: import, load, infer, contract;
the local container CLI can report exit code 0 for a failed run, so this smoke trusts the stage artifacts
```

诊断报告给出的根因：镜像内置了 `SURE_ARTIFACTS_DIR=/outputs`，而审批 smoke 只挂载
`/model`（只读）和 `/model/artifacts`（可写），`validate.py` 因此把结果写进容器自身的
可写层；`--rm` 退出后文件消失，容器退出码仍是 0，审批侧读不到任何阶段证据，判定为
“无证据的 vacuous pass”。同一 argv 只增加 `SURE_ARTIFACTS_DIR=/model/artifacts` 后
import/load/infer/contract 全部通过（约 20 秒），说明候选模型本身是好的，**是打包配置
而不是模型推理的问题**。

**已确认的代码事实**：

- `SURE_ARTIFACTS_DIR` **全仓 0 命中**，`git log --all -S"SURE_ARTIFACTS_DIR"` 也 **0 命中**
  —— 它是模型自造变量，不是 harness 定义的契约。
- approve smoke 的挂载只有两处：`approval_core.py:1402-1405`
  （`<model_target>` 只读 + `<model_target>/artifacts` 可写）；`/outputs` 不在其中。
- harness 自带的模板 `sure_onboard/scripts/templates/validate.py:32-33` 把产物目录写死为
  `Path(__file__).resolve().parent / "artifacts"`，**不读任何环境变量**，所以官方模板永远
  产生不了这个失败。
- “无证据即拒”是 `approval_core.py` 的既定行为，不是 bug。

**harness 侧的缺口**：共享路径契约 `deployment_contract._validate_runtime_path_env`
（`:367`）只校验**读**路径（`MODEL_PATH` / `MODEL_DIR` / `SURE_MODEL_DIR` / `PYTHONPATH` /
`PYTHONHOME`），**没有校验写路径**。而审批的“阶段证据”规则恰恰依赖写路径，于是这类
“镜像内置了挂载点之外的绝对路径”的缺陷可以完整通过 onboard（含打包闸门、push、digest
解析），只在 approve（已经占了 GPU、已经拉了镜像）才暴露。读写不对称就是缺口本身。

**本次修复**：

1. `approval_core.py` 的阶段证据失败信息改为指名可写挂载点，并打印镜像内置 ENV（已脱敏）。
   原文案写的是“本地容器 CLI 可能对失败返回 0”，指向的是错误的原因，而且**从不显示**
   `SURE_ARTIFACTS_DIR`——运维只能自己 `docker image inspect` 才能定位。
2. 写路径规则进共享校验器 `_validate_runtime_path_env`：镜像 ENV、Dockerfile ENV、
   `config.yaml server.env` 三个闸门统一生效；被打包闸门
   （`check_container_package.py:87` → `validate_image_runtime_env`）在 push 之后、
   approve 之前就拒，不再浪费一整轮 approve。
3. 文档：`sure_onboard/SKILL.md` 的 `generate_wrapper` 契约与
   `references/playbooks/env_docker.md` 的运行时契约都写明产物目录就是 bundle 自己的
   `artifacts/`（容器内 `<working_dir>/artifacts`），镜像不得内置把它指到别处的变量。

**边界与取舍**：

- 规则按变量名匹配（名字含 `ARTIFACT` 且以 `DIR` 结尾），变量名归生产者所有，属于启发式；
  但仓库内没有任何 Dockerfile 内置这类变量（全仓 Dockerfile 扫描 0 命中），误报代价是重建镜像。
- **没有**在 approve 阶段注入环境变量兜底：那会改变被审计镜像的运行配置，审批就证明了
  一个没被审的东西。
- **没有**改成“按镜像声明的产物目录额外挂一个可写卷”：那等于给镜像一条可写路径的注入口
  （镜像可以声明任意路径），并且改变了 approve 所证明的语义。作为备选记在第六节。

### 🟡 低：infer 侧 `MODEL_DIR`/`SURE_MODEL_DIR` 由“包含”收紧为“相等”（已补迁移说明）

旧 infer 用 `_posix_within`（包含），共享函数用相等（`!= working_dir` 即拒）。
`/workspace/model/sub` 这类声明现在会被拒。这与 approve 侧旧行为一致（approve 一直
是相等），所以是**有意对齐**，不是 bug；但存量 bundle 若声明了子目录会在推理时新被拒，
已在 `sure/skills/sure_onboard/SKILL.md` 增加存量 inventory 重新 onboard 的迁移说明。

## 四、修复后验证结果

复核跑在**当前工作区**（遮蔽修复已应用、未提交），`TEMP` 指向长路径以避开 8.3 短路径噪声：

| 检查 | 结果 |
| --- | --- |
| `npm run check` | **12/12 通过**（连续两次复核均为 12/12；此前记录的 10/12 未复现） |
| `sure_approve` 全量 | **79 tests**（较上一轮 +3：共享规则 2 + 诊断信息 1） |
| `sure_infer` 全量 | 777 tests，**1 error** = 存量 CRLF 用例；遮蔽引入的 5 个已消失 |
| `sure_onboard` 全量 | 185 tests（+1 写路径规则的直接用例），1 失败（存量） |
| 本轮改动的失败集对比 | `git stash` 前后逐 skill 跑全量，失败用例名单 **diff 为空**（只有用例计数 +1/+1 与耗时差异） |
| 遮蔽复检 | `docker_runtime` → `sure_infer/scripts/docker_runtime.py`，`SURE_EVAL_DOCKER_BIN` **在位** |
| 三闸门一致性实测 | 15 组声明 × 3 闸门，approve/infer **逐条一致** |

存量失败（**在 `main` 上完全相同**）：

- `test_evaluation_runtime::EvaluationLockTests::test_crlf_checkout_uses_the_same_pyproject_identity`
  —— Windows CRLF checkout
- `test_python_delivery_contract::PythonDeliveryContractTests::test_package_none_with_installed_adapter_passes_the_inventory_gate`

基线对比方法：`git worktree add <path> main` 拉一份 main 出来跑同样的用例，失败用例
名单 `diff` 结果为 IDENTICAL。

另外注意：Windows 上 `TEMP` 指向 8.3 短路径（`SHENGY~1.XIA`）时，会额外炸 7 个与路径拼写
相关的用例；把 `TEMP` 指到长路径后全绿。**这 7 个也是 main 上同样失败的**，不是本分支引入的。

结论：`sys.path` 遮蔽已修复且有测试佐证，核心契约修复是必要的；剩余失败均为存量环境问题，
需与业务缺陷分开处理。

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

**已完成**（本轮已实施并复核通过）：

1. ✅ 修 `container_execution.py` 的 `sys.path` 遮蔽 —— 改用命名空间包导入，
   `sys.path` 不再被污染；`docker_runtime` 恢复正常解析。
2. ✅ 删掉 `_refuse_renamed_bundle_root`（死代码，规则已被共享函数覆盖）。
3. ✅ `sure_onboard/SKILL.md` 补存量 inventory 迁移说明
   （`write_runtime_inventory.py` 换成真实 `working_dir` 后，存量的
   `container_runtime.working_dir` 还是旧的 `/workspace/model` 兜底值，
   新的 `check_runtime_inventory.py` 要求它等于 `model_bundle.target`，存量的会挂；
   同时提示 `MODEL_DIR`/`SURE_MODEL_DIR` 必须是 `working_dir` 本身而非子目录）。

**本轮一并补齐**：

4. ✅ `env_docker.md` 第 4 步写明"每次 `docker run` 都要显式 `--entrypoint <interpreter>`"，
   并说明镜像自带 ENTRYPOINT 时会变成 `python3 python3 validate.py`。
5. ✅ `write_runtime_inventory.py` 在 `validate_container_runtime_contract` 前确认 Dockerfile
   存在，缺文件时给出可读的 `ValueError`（`main()` 已捕获，打印
   `write_runtime_inventory failed: ...` 并返回 1），不再抛未包装的 `FileNotFoundError`。
6. ✅ `verify_live_image` 的 WORKDIR 空值文案改成"digest-pinned image declares no WORKDIR"，
   不再报 `WORKDIR '' disagrees with ...`。**WORKDIR 不一致时的原文案不变**
   （`test_docker_delivery_contract.py` 有断言依赖）。
7. ✅ `sure_infer/SKILL.md` 的新一节把判定写准：`MODEL_PATH` 必须在挂载点下，
   `MODEL_DIR`/`SURE_MODEL_DIR` 必须**等于**挂载点，`PYTHONPATH`/`PYTHONHOME`
   **只有路径含 `model` 段时才检查**，其余绝对路径属于镜像、放行。
8. ✅ 补了共享规则的**直接**用例
   （`test_docker_delivery_contract.py::test_the_shared_runtime_path_rule_is_one_rule_for_every_gate`）：
   6 组合法声明放行、6 组越界声明拒绝（含 `..` 逃逸、`MODEL_DIR` 子目录、
   非 model 段的 `PYTHONHOME` 放行、`${VAR}` 延迟展开跳过）。
   共享函数此前只被三个闸门间接覆盖，没有直接断言。

**仍待处理**：

9. `approval_core.py` 的 `_authored_smoke_arguments` 兜底判定**不改**。
   收窄到"绝对路径"会让相对 fixture 路径重新被当字面量传给工具；而放宽又会放回
   越界绝对路径。现在的取舍是：含 `/` 的越界路径**响亮地拒**（错误信息已说明
   "the container mounts only the bundle, at <target>"），操作者改写成 bundle 内的绝对路径即可。
   代价是含 `/` 的**字面量**提示词也会被拒 —— 冒烟 fixture 用得少，值不值得再收窄由维护者定。
10. 如需整理历史，可单独规划 rebase；不作为功能合并前置条件。
11. **备选（本轮未做）**：让 approve 的容器 smoke 额外按镜像声明的产物目录挂一个可写卷，
   使"镜像自带 `SURE_ARTIFACTS_DIR`"这类候选也能通过审批。**未做**的理由：镜像可以声明
   任意路径，等于给它一条可写路径的注入口；而且 approve 证明的语义会从"按 harness 契约
   运行"变成"按镜像声明运行"。真要做，必须先约束挂载目标（不得是 `/`、不得在模型挂载点之下）。
   当前的取舍是：这种候选在**打包闸门**就被拒（写路径规则），由生产者重打镜像，
   比在审批阶段给镜像开可写路径更干净。

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
- `deployment_contract.py:166` 的**惰性**路径插入：函数内插路径，只影响调用那一刻，
  不会像模块级 `sys.path.insert(0, ...)` 那样整程遮蔽同名模块。跨 skill 目录引用代码时
  应该照这个写法，别照 `approval_core.py:30` 的 `append`（那是安全的，因为它没有同名模块）。

## 附录：关键代码位置索引

| 位置 | 内容 |
| --- | --- |
| `sure/skills/sure_onboard/scripts/deployment_contract.py:367` | `_validate_runtime_path_env`（母本） |
| `sure/skills/sure_onboard/scripts/deployment_contract.py:440` | `validate_runtime_path_env`（公共入口） |
| `sure/skills/sure_onboard/scripts/deployment_contract.py:445` | `validate_image_runtime_env` |
| `sure/skills/sure_onboard/scripts/deployment_contract.py:466` | `validate_container_runtime_contract` |
| `sure/skills/sure_onboard/scripts/deployment_contract.py:166` | `_server_protocol_module`（惰性插入路径的正确范例） |
| `sure/skills/sure_approve/scripts/approval_core.py:877` | 容器分支调用共享 env 校验 |
| `sure/skills/sure_approve/scripts/approval_core.py:1402` | 容器 smoke 的两处挂载（模型只读 + `artifacts` 可写） |
| `sure/skills/sure_approve/scripts/approval_core.py:1418` | 阶段证据失败信息（现指名可写挂载点 + 打印镜像 ENV） |
| `sure/skills/sure_approve/scripts/approval_core.py:718` | `_redacted_env`（原 `_refuse_renamed_bundle_root` 位置，死代码已删） |
| `sure/skills/sure_approve/scripts/approval_core.py:1122` | `_verify_container_server` |
| `sure/skills/sure_approve/scripts/approval_core.py:1178/1400` | `--entrypoint` |
| `sure/skills/sure_infer/scripts/container_execution.py:220` | `validate_infer_path_contract` |
| `sure/skills/sure_infer/scripts/container_execution.py:251` | infer 路径契约调用共享 env 校验 |
| `sure/skills/sure_infer/scripts/container_execution.py:21` | 命名空间包导入（遮蔽点的替代写法） |
| `sure/skills/sure_onboard/scripts/check_runtime_inventory.py:86` | `working_dir == model_bundle.target` |
| `sure/skills/sure_onboard/scripts/write_runtime_inventory.py:229` | `runtime = validated_model_runtime` |
