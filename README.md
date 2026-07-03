# DJI-with-Python

> Disclaimer: This is an unofficial personal learning and research archive. It is not affiliated with, endorsed by, or sponsored by DJI.
>
> 免责声明：本仓库为个人学习与研究归档项目，与 DJI / 大疆官方无隶属、授权、合作或背书关系。

本仓库包含个人 Zemax 自动化与超广角镜头结构搜索工作流的归档。

当前已整理的项目入口为：

- [`dji_zemax_checker/`](./dji_zemax_checker/)
- [`dji_zemax_checker/README.md`](./dji_zemax_checker/README.md)（项目技术细节与数据树）
- [`dji_zemax_checker/docs/`](./dji_zemax_checker/docs/)（设计约束、实验日志与 ML 规划）
- [`dji_zemax_checker/reports/`](./dji_zemax_checker/reports/)（阶段性评估与根因分析报告）
- [`dji_zemax_checker/data/`](./dji_zemax_checker/data/)（物理文件哈希清单与 ML 数据模板）

## 当前项目重点

本仓库并非声明已完成的最终光学设计。当前归档分支的核心重点在于：

1. **Zemax/ZOS-API 工作流归档**：实现基于 Python 和 ZOSPy 的头模式自动化镜头构建。
2. **超广角候选结构搜索**：从文献或专利参数中自动重建镜头三维模型。
3. **光路追迹与渐晕校验**：在 F/2.5 工作光圈下使用实光线追迹校验高场通光能力。
4. **失效面与力学边缘分析**：定位发生全反射（TIR）或机械干涉的透镜面，分析边缘间隔。
5. **机器学习预筛选数据准备**：将良性与恶性镜头结构数据化，为训练离线 ML 预筛选模型做准备。

## 重要说明

- **无原始设计文件**：Git 仓库中不追踪任何原始 `.ZOS` 或 `.ZMX` 二进制设计文件。
- **排除本地缓存**：所有的 results、outputs、logs、temp 以及本地二进制输出目录均已通过 .gitignore 排除。
- **光学结论真实性**：所有的光学结论和度量值仅在有历史日志或 fresh-load 校验支持时才予以记录。
- **未知数据标记**：所有未知或未经验证的数值和指标必须显式标记为 `UNKNOWN` 或 `TODO`。

## 归档分支

当前项目整理分支为：

`archive/triage_organization`
