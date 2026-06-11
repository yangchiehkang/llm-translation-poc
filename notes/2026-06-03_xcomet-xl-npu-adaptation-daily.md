# 2026-06-03 日报：XCOMET-XL QE 评分脚本 NPU 适配与全量评估完成

## 一、今日工作概述

今天主要围绕 `llm-translation-poc` 项目的机器翻译质量评估链路开展工作，重点完成了 Qwen-Max 多语言翻译结果的 XCOMET-XL QE 评分，并解决了评分脚本原本无法直接使用 Ascend NPU 的核心问题。

本次工作中，我将原先只支持 CPU / CUDA GPU 的 XCOMET 评分逻辑，改造为可以在 Ascend NPU 环境下运行。改造完成后，脚本成功加载 `Unbabel/XCOMET-XL` 模型，在 NPU 上完成多语言翻译结果的 Quality Estimation（QE）评分，并输出了完整 Excel 结果文件。

本次评分属于无参考译文质量估计，即模型输入为源语言文本和机器翻译结果，输出句子级质量分数，不依赖人工参考译文。

---

## 二、今日完成的主要工作

### 1. 确认 XCOMET-XL QE 评分方式

今天首先确认了本次机器翻译评估使用的是 `Unbabel/XCOMET-XL` 模型，并以 QE 模式进行评分。

本次评分方式可以理解为：

> 源语言文本 + 机器翻译结果 → XCOMET-XL QE 分数

也就是说，本次评估不需要参考译文，模型会直接根据原文和译文判断翻译质量。

本次使用的模型 checkpoint 位于服务器本地路径：

> `/home/yinzs/models/huggingface/hub/models--Unbabel--XCOMET-XL/snapshots/6a123c5e8e6dccab25e5fcffa3c8b417abadb462/checkpoints/model.ckpt`

最终确认本次评分配置如下：

| 项目 | 内容 |
| :--- | :--- |
| 机器翻译模型 | `qwen-max` |
| 评估指标 | `comet-qe` |
| 评估模型 | `Unbabel/XCOMET-XL` |
| 评估模式 | Quality Estimation |
| 是否需要参考译文 | 不需要 |
| 运行设备 | Ascend NPU |

---

### 2. 分析原始脚本的设备限制

原始版本的评分脚本只支持两类设备：CPU 和 CUDA GPU。

也就是说，脚本原来的设备逻辑只有：

- `cpu`
- `cuda`

在原始设计中，如果选择 CPU，就让 COMET 模型在 CPU 上执行预测；如果选择 CUDA，就让 COMET 通过 GPU 路径执行预测。

但当前服务器使用的是 Ascend NPU，不是传统 NVIDIA CUDA GPU。虽然 Ascend NPU 可以通过 `torch_npu` 运行 PyTorch 模型，但 XCOMET / COMET 的预测流程底层依赖 PyTorch Lightning，而 PyTorch Lightning 默认主要识别 CPU 和 CUDA GPU 路径。

因此，原脚本直接运行在 NPU 环境下会存在明显限制：

- COMET 的预测入口默认不直接暴露 NPU accelerator。
- PyTorch Lightning 会按 CPU / CUDA 路径管理设备。
- 如果强行使用 CPU 模式，会导致模型无法利用 NPU 加速。
- 如果简单把模型手动移动到 NPU，又可能和 Lightning 的设备管理逻辑冲突。
- 原脚本没有独立的 NPU 初始化、设备检查和兼容处理逻辑。

因此，今天的核心工作就是重新设计设备适配逻辑，让 XCOMET-XL 可以在不修改 COMET 框架源码的前提下运行在 Ascend NPU 上。

---

### 3. 设计 NPU 兼容运行方案

针对 XCOMET / COMET 原生不直接支持 Ascend NPU 的问题，我采用的解决思路是：

> 不直接修改 COMET 源码，不重写 PyTorch Lightning accelerator，而是在业务脚本层增加一层 NPU 兼容适配逻辑。

核心方法是利用 `torch_npu` 提供的 CUDA-compatible 转换能力，让 COMET 和 PyTorch Lightning 仍然走它们熟悉的 CUDA 调用路径，但底层实际计算由 Ascend NPU 执行。

整体思路如下：

| 视角 | 实际含义 |
| :--- | :--- |
| COMET / PyTorch Lightning 视角 | 仍然按照 CUDA-compatible device 运行 |
| 实际硬件执行 | Ascend NPU |
| 桥接方式 | 通过 `torch_npu` 将 CUDA 调用转发到 NPU |
| 改造位置 | 业务脚本层，不修改 COMET 框架源码 |

这样做的好处是：

- 不需要修改 COMET 框架源码。
- 不需要重写 PyTorch Lightning 的 accelerator。
- 可以最大限度复用 COMET 原有的预测流程。
- 能够让现有 XCOMET-XL checkpoint 在 Ascend NPU 上完成推理。
- 对后续扩展其他 COMET 系列模型也更友好。

---

### 4. 增加 NPU 设备识别与初始化逻辑

为支持 NPU 运行，我对脚本的设备管理逻辑做了扩展，将原本只支持 CPU / CUDA 的设备选项扩展为：

- `cpu`
- `cuda`
- `npu`

在 NPU 模式下，脚本会先完成以下检查和初始化：

- 检查当前 Python 环境是否可以正常导入 `torch_npu`。
- 检查当前机器上的 NPU 是否可用。
- 指定使用第 0 张 NPU 卡。
- 启用 `torch_npu` 的 CUDA-compatible 转换能力。
- 打印当前识别到的 NPU 设备名称，确认实际硬件可用。

实际运行中，脚本成功识别到了 Ascend 910B2。日志中显示 NPU 可用，并提示当前正在通过 CUDA-compatible path 使用 Ascend NPU。

这说明 NPU 初始化逻辑已经生效，后续模型预测可以通过兼容路径进入 NPU 推理流程。

---

### 5. 解决 PyTorch Lightning 的 CUDA capability 检查问题

在适配过程中，还遇到一个比较关键的兼容性问题：PyTorch Lightning 在初始化 CUDA accelerator 时，会检查设备能力信息，例如 CUDA capability。

但 Ascend NPU 并不是 NVIDIA GPU，部分 CUDA capability 查询接口在 NPU 环境中并不完整。如果这些接口返回异常，或者返回值不符合 Lightning 的预期，就会导致 COMET 预测流程无法继续。

为了解决这个问题，我在脚本中增加了兼容处理逻辑：

- 对 Lightning 运行过程中依赖的部分 CUDA 查询接口进行补齐。
- 让这些接口返回符合 Lightning 预期的设备信息。
- 避免预测流程在设备初始化阶段中断。
- 保持实际计算仍由 Ascend NPU 执行。

这个处理并不是为了伪造实际硬件，而是为了让 PyTorch Lightning 能够顺利完成初始化检查。完成兼容处理后，COMET 的预测流程可以正常进入 DataLoader 推理阶段，并顺利完成所有样本的评分。

---

### 6. 调整 COMET predict 的设备调用方式

原始脚本的预测逻辑本质上只有一个判断：

> 使用 GPU 就走 CUDA，不使用 GPU 就走 CPU。

但 NPU 适配后，不能简单把 NPU 当成 CPU，也不能直接把模型手动迁移到 NPU 设备上。因为 COMET 的预测过程由 PyTorch Lightning 管理，如果手动迁移模型，可能会和 Lightning 的内部设备调度冲突。

因此，我调整了整体调用思路：

| 设备模式 | 调用策略 |
| :--- | :--- |
| CPU 模式 | 明确走 CPU 推理 |
| CUDA 模式 | 走正常 CUDA GPU 推理 |
| NPU 模式 | 走 CUDA-compatible path，由 `torch_npu` 转发到 Ascend NPU |

NPU 模式下的关键原则是：

- 不手动把模型移动到 `npu:0`。
- 不把预测任务设置成 CPU 模式。
- 保持 COMET / Lightning 的 CUDA-compatible 调用方式。
- 由 `torch_npu` 负责把底层计算转发到 NPU。

这样既保留了 COMET 原有预测流程，又避免了直接改动 COMET 和 PyTorch Lightning 的内部实现。

---

### 7. 优化模型 checkpoint 加载方式

除了设备适配，我也优化了模型 checkpoint 的加载逻辑。

原始脚本对模型路径的处理比较简单，主要支持本地 checkpoint 文件或在线模型名称。新版本增强了本地模型解析能力，可以兼容 Hugging Face 缓存目录中的 snapshot 结构。

本次使用的是服务器中已经下载好的 XCOMET-XL checkpoint，因此不需要重新联网下载模型，脚本可以直接解析并加载本地模型文件。

本次实际加载的模型为：

> `Unbabel/XCOMET-XL`

本次实际使用的 checkpoint 为：

> `/home/yinzs/models/huggingface/hub/models--Unbabel--XCOMET-XL/snapshots/6a123c5e8e6dccab25e5fcffa3c8b417abadb462/checkpoints/model.ckpt`

这一步保证了后续评分任务可以稳定复现，不依赖实时网络环境。

---

### 8. 完成测试评分任务

完成 NPU 适配后，我先进行了小规模测试评分，确认脚本可以完整跑通。

测试输出文件为：

> `/home/yinzs/llm-translation-poc/data/report/test_xcomet_xl_npu.xlsx`

运行日志显示测试任务成功完成，结果文件成功写出。

这说明脚本已经能够完成以下完整流程：

- 读取 jsonl 翻译文件。
- 加载 XCOMET-XL checkpoint。
- 初始化 Ascend NPU。
- 通过 CUDA-compatible path 执行 COMET predict。
- 生成句子级 QE 分数。
- 写出 Excel 评分结果。

---

### 9. 完成 15 个语言方向的全量评分

测试通过后，我执行了全量评分任务，对 `data/mt` 目录下的 Qwen-Max 翻译结果进行统一评分。

全量评分任务共匹配到 15 个语言方向文件：

| 序号 | 文件名 |
| ---: | :--- |
| 1 | `mt_ar._qwen-max.jsonl` |
| 2 | `mt_de._qwen-max.jsonl` |
| 3 | `mt_en._qwen-max.jsonl` |
| 4 | `mt_es._qwen-max.jsonl` |
| 5 | `mt_fr._qwen-max.jsonl` |
| 6 | `mt_id._qwen-max.jsonl` |
| 7 | `mt_it._qwen-max.jsonl` |
| 8 | `mt_ms._qwen-max.jsonl` |
| 9 | `mt_nl._qwen-max.jsonl` |
| 10 | `mt_no._qwen-max.jsonl` |
| 11 | `mt_pt._qwen-max.jsonl` |
| 12 | `mt_ru._qwen-max.jsonl` |
| 13 | `mt_sv._qwen-max.jsonl` |
| 14 | `mt_th._qwen-max.jsonl` |
| 15 | `mt_vi._qwen-max.jsonl` |

全量评分最终成功完成，服务器端输出文件为：

> `/home/yinzs/llm-translation-poc/data/report/score_xcomet_xl_npu.xlsx`

之后将该结果文件下载到了本地：

> `E:\Working\llm-translation-poc\data\report\score_xcomet_xl_npu.xlsx`

---

## 三、核心问题与解决过程

### 1. 核心问题

今天最主要的问题是：

> XCOMET / COMET 原始评分逻辑只能直接使用 CPU 或 CUDA GPU，无法直接识别并使用 Ascend NPU。

这个问题的根本原因是：

- XCOMET-XL 通过 COMET 框架运行。
- COMET 的预测流程依赖 PyTorch Lightning。
- PyTorch Lightning 默认对 CPU / CUDA GPU 支持更直接。
- Ascend NPU 需要通过 `torch_npu` 接入 PyTorch 生态。
- 原始脚本没有针对 NPU 的设备初始化和兼容处理逻辑。

如果不处理这个问题，评分任务只能走 CPU，速度和资源利用率都不理想；或者在设备初始化阶段因为 CUDA / NPU 兼容问题失败。

---

### 2. 解决方法

我的解决方法是在业务脚本中增加一层 NPU 适配逻辑，而不是修改 COMET 或 PyTorch Lightning 源码。

整体方案可以概括为：

> 使用 `torch_npu` 提供的 CUDA-compatible 转换能力，让 COMET / PyTorch Lightning 继续走 CUDA 形式的调用路径，同时将底层实际计算转发到 Ascend NPU 上执行。

具体处理思路包括：

- 在脚本中增加 `npu` 设备选项。
- 启动时检查 `torch_npu` 是否可用。
- 初始化 Ascend NPU 并指定运行设备。
- 启用 `torch_npu` 的 CUDA 到 NPU 转换能力。
- 对 PyTorch Lightning 依赖的 CUDA 设备信息查询进行兼容处理。
- 在 NPU 模式下保持 COMET 的 CUDA-compatible predict 调用方式。
- 避免手动迁移模型到 NPU，防止和 Lightning 的设备管理冲突。

最终形成的运行链路为：

> XCOMET-XL checkpoint → COMET model.predict → PyTorch Lightning CUDA-compatible accelerator → torch_npu transfer_to_npu → Ascend NPU 实际执行 → 输出 QE score

---

### 3. 解决结果

改造完成后，脚本成功在 Ascend NPU 上运行 XCOMET-XL QE 评分。

从运行日志可以确认：

- NPU 可用。
- 识别到 Ascend910B2。
- COMET predict 通过 CUDA-compatible Ascend path 执行。
- 每个语言文件均成功完成 DataLoader 推理。
- 最终成功写出 Excel 评分结果。

最终结果文件为：

> `/home/yinzs/llm-translation-poc/data/report/score_xcomet_xl_npu.xlsx`

这个问题的解决，使当前评估链路从原本的 CPU / GPU 环境扩展到了 Ascend NPU 环境，提升了脚本在国产化硬件环境下的可运行性和工程适配价值。

---

## 四、评分结果概览

本次正式评分结果文件为：

> `score_xcomet_xl_npu.xlsx`

本次评分配置如下：

| 项目 | 内容 |
| :--- | :--- |
| MT Model | `qwen-max` |
| Metric | `comet-qe` |
| Metric Model | `Unbabel_XCOMET-XL` |
| Device | `npu` |
| Batch Size | 1 |
| Matched Files | 15 |

部分语言方向的平均分如下：

| 语言方向 | 样本数 | Mean |
| :--- | ---: | ---: |
| Swedish → Chinese | 200 | 0.8079 |
| Malay → Chinese | 200 | 0.7835 |
| German → Chinese | 200 | 0.7799 |
| Norwegian → Chinese | 200 | 0.7674 |
| Thai → Chinese | 200 | 0.7584 |
| English → Chinese | 200 | 0.7539 |
| Dutch → Chinese | 135 | 0.7413 |
| Portuguese → Chinese | 200 | 0.6987 |
| Indonesian → Chinese | 200 | 0.6970 |
| Russian → Chinese | 180 | 0.6866 |
| Italian → Chinese | 200 | 0.6137 |
| Spanish → Chinese | 50 | 0.5952 |
| French → Chinese | 200 | 0.5639 |
| Arabic → Chinese | 118 | 0.3263 |

从结果看，Qwen-Max 在 Swedish、Malay、German、Norwegian、Thai、English 等语言到中文的技术 / 法律文本翻译中表现相对较好。Arabic → Chinese 得分最低，后续需要重点分析低分样本。

---

## 五、今日产出

### 1. 完成 XCOMET-XL QE 评分脚本 NPU 适配

脚本现在支持以下设备模式：

- `cpu`
- `cuda`
- `npu`

其中 NPU 模式通过 `torch_npu` 的 CUDA-compatible 路径实现，不需要修改 COMET 框架源码。

---

### 2. 生成测试评分结果

测试结果文件为：

> `/home/yinzs/llm-translation-poc/data/report/test_xcomet_xl_npu.xlsx`

---

### 3. 生成全量评分结果

服务器端结果文件为：

> `/home/yinzs/llm-translation-poc/data/report/score_xcomet_xl_npu.xlsx`

本地结果文件为：

> `E:\Working\llm-translation-poc\data\report\score_xcomet_xl_npu.xlsx`

---

### 4. 完成新旧评分结果对比

今天还对比了本次正式 XCOMET-XL QE 评分结果和之前的 pseudo-QE 评分结果。

主要结论为：

- 本次正式 XCOMET-XL QE 分数整体更严格。
- 旧 pseudo-QE 分数整体偏高。
- 两次结果的语言表现趋势大体一致。
- 后续正式质量分析建议以本次 NPU 上跑出的 XCOMET-XL QE 结果为准。

---

## 六、后续计划

1. 继续完善语言字段映射，统一不同语言方向的命名格式。
2. 检查 Vietnamese 语言方向在 summary 中的展示是否存在解析异常。
3. 对低分语言方向进行样本级分析，优先关注 Arabic、French、Spanish、Italian。
4. 对低分样本进行错误归因，重点检查漏译、误译、术语不一致、结构错位和模型输出额外说明等问题。
5. 基于本次正式 XCOMET-XL QE 结果整理最终机器翻译质量评估报告。
