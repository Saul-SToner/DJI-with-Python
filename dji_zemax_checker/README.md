# Zemax 超广角镜头结构搜索工作流

> Disclaimer: This is an unofficial personal learning and research archive. It is not affiliated with, endorsed by, or sponsored by DJI.
>
> 免责声明：本仓库为个人学习与研究归档项目，与 DJI / 大疆官方无隶属、授权、合作或背书关系。

本仓库是一个**个人学习与研究的工作流归档**，记录了用于超广角镜头（W9A）结构搜索、自动重建、实光线追迹与评估的 ZOS-API 自动化脚本。

- Donor-to-DJI material transfer v0 summary: [`reports/donor_transfer_v0_summary.md`](./reports/donor_transfer_v0_summary.md)
- CN114 structure rebuild v0 report: [`reports/structure_rebuild_v0_report.md`](./reports/structure_rebuild_v0_report.md)
- Limited structure rebuild v1 report: [`reports/limited_structure_rebuild_v1_report.md`](./reports/limited_structure_rebuild_v1_report.md)

## 项目定位与重点

本项目的核心目的**不是**进行最终的光学设计优化或像质精修，而是建立一套完整的拓扑构建与评估管道：
1. **候选结构自动生成**：直接解析专利或设计候选 CSV 参数，在 Zemax LDE 中自动重建 sequential 镜头模型，并应用精确的 model glass solves ($n_d, v_d$)。
2. **光阑与渐晕校验**：在 F/2.5（或阶段性指定光圈）下通过 Real Ray Aiming 对最高 $71.5^\circ$ 的视场进行 7 射线实光线追迹。
3. **失效面自动定位**：精确识别在哪一个透镜面上发生全反射（TIR）、通光剪裁或干涉。
4. **阶段性结构冻结**：对 triage 运行结果进行物理特征量化、分类 and 封存。
5. **机器学习预筛选数据准备**：将评估得到的镜头各项物理指标输出为结构化 CSV 模板，为未来训练离线 ML 预筛选分类器提供数据支撑。

---

## 环境与安装

### OpticStudio 本地许可要求
> [!IMPORTANT]
> ZOS-API 属于 Zemax OpticStudio 的底层 C# 接口，**无法**通过 pip 直接下载安装。运行此脚本需要在 Windows 环境下安装并激活本地授权的 Ansys Zemax OpticStudio。

### Python 运行环境安装
```powershell
cd C:\ZemaxAuto\dji_zemax_checker
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

---

## 项目目录树结构

```text
├── docs/                       # 架构设计与约束条件文档
│   ├── project_overview.md     # 工作流管道概述
│   ├── design_constraints.md   # 力学与通光约束指标 (例如 F/2.5 目标)
│   ├── experiment_log.md       # 历史执行日志 (Stage 0, R106H triage)
│   ├── data_schema.md          # Processed 数据的 CSV 字段 schema
│   └── future_ml_screening_plan.md  # 离线 ML 镜头预筛选模型构建规划
│
├── reports/                    # 阶段性结果汇总与失效分析报告
│   ├── stage_summary.md        # 运行汇总与验证结论
│   ├── best_candidate_freeze.md# 候选 1、2 结构冻结报告与性能快照
│   ├── root_cause_report.md    # 大视场渐晕失效与边缘厚度冲突根因分析
│   └── failed_routes.md        # 尺寸比例不匹配以及 STOP 前移的失败路径记录
│
├── data/
│   ├── raw/                    # 原始输入数据与目录源
│   ├── processed/              # 供 ML 训练使用的空数据模板
│   │   ├── candidate_table.csv
│   │   ├── trace_result_table.csv
│   │   ├── failure_surface_table.csv
│   │   └── experiment_log.csv
│   └── manifests/              # 用于代替二进制设计文件的哈希对照清单
│       └── zos_file_manifest.csv
│
├── src/                        # ZOS-API 连接、参数读取与诊断核心代码
├── runner/                     # 顶层测试运行脚本与分级 triage 执行入口
└── notebooks/                  # 数据分析与交互探索 Notebook
```

---

## 仓库约束与安全策略

- **二进制设计文件排除**：所有的 `.ZOS`, `.ZMX`, `.ZDA` 镜头原文件以及 session 临时配置均通过 `.gitignore` 严格排除，避免污染仓库。仅由 `zos_file_manifest.csv` 记录其相对路径与 SHA-256 哈希。
- **只读诊断安全机制**：任何包含修改 LDE 行为的脚本默认仅执行 Dry-run，需要传入显式 `--apply` 参数方可保存，最大程度保护原始设计参数。
- **无虚假数据声明**：任何未经 fresh-load 校验或历史日志确认的数据和指标必须显式标记为 `UNKNOWN` 或 `TODO`，不作任何没有依据的性能推断。
