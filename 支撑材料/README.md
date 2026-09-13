# C 题支撑材料说明

本目录汇总定稿论文实际使用的计算源程序、派生数据、结果文件、图表、验证程序和参考资料。
所有 Python 源程序均由仓库 `src/py/` 原样复制，未改变文件内容或格式。

## 目录结构

```text
支撑材料/
├── AI工具使用说明.md  # 与论文附录 C 一致的 AI 工具使用记录
├── src/
│   ├── py/          # 四问正式模型、结果回填、制表、绘图与敏感性分析程序
│   ├── data/        # 程序生成的汇总数据，不含赛题原始数据
│   ├── outputs/     # 正文表图所依据的机器可读结果与核验报告
│   └── figure/      # 定稿论文实际使用的 PDF 图表
├── 附件5/       # 四问最终结果工作簿
├── 验证程序/        # 单元测试和结果工作簿审计程序
├── 参考资料/        # 正文实际引用文献及关键方法的资料索引
└── 补充分析/        # 条件残差与随机规划的对照实验记录
```

## 程序与问题对应关系

| 问题 | 主要入口 | 关键依赖与辅助程序 | 最终结果 |
| --- | --- | --- | --- |
| 问题一 | `question1.py` | `microgrid_core.py`、`question1_analysis.py`、`innovation_analysis.py` | `result1.xlsx` |
| 问题二 | `question2.py` | `question2_data.py`、`question2_forecast.py`、`question2_scenarios.py`、`question2_dispatch.py` | `result2.xlsx` |
| 问题三 | `run_q3.py`、`fill_result3.py` | `q3_model.py` 及场景数、敏感性、预报价值等实验程序 | `result3.xlsx` |
| 问题四日前方案 | `run_q4_2.py`、`fill_result4_2.py` | `question4_2*.py`、`q4_innovation_experiment.py` | `result4-2.xlsx` |
| 问题四日内方案 | `run_q4_3.py`、`fill_result4_3.py` | `q4_model.py`、问题三公共模块 | `result4-3.xlsx` |

`make_q*_tables.py` 和 `plot_question*.py` 用于由正式结果生成论文表图；`workbook_style.py`
统一结果工作簿字体。其余纳入的实验程序对应正文中的场景数稳定性、终端状态、预报节点价值、
灵敏度或跨日前瞻对照。强化学习程序没有进入定稿模型，因此未收入本支撑材料。

## 数据边界

本目录只包含模型计算所得的派生数据、汇总结果和官方结果模板的已填报版本，不包含赛题 PDF，
也不包含附件 1--4 的负荷、光伏、预测和电价原始数据。若需完整复现，应由使用者自行取得赛题
原始附件，并按程序原有路径放置在 `problems/C题/附件/` 下；本材料没有为迁移目录而改写程序。

## 环境与复核

依赖版本入口为 `src/py/requirements.txt`。在补齐官方原始数据后，可从支撑材料根目录运行：

```powershell
python -m pip install -r src/py/requirements.txt
python src/py/question1.py
python src/py/question2.py
python src/py/run_q3.py
python src/py/run_q4_2.py
python src/py/run_q4_3.py
```

结果工作簿可使用 `验证程序/audit_result_workbooks.py` 复核。验证程序与计算程序分开保存，
运行前应将计算程序目录加入模块搜索路径：

```powershell
$env:PYTHONPATH = (Resolve-Path "src/py").Path
python 验证程序/audit_result_workbooks.py
python -m unittest discover -s 验证程序 -p "test_*.py" -v
```

论文 LaTeX 源文件仍以仓库 `src/tex/main.tex` 为准，不在本目录重复维护。

## 定稿口径

- 正式评价区间、模型参数和费用结果以定稿论文及 `附件5/` 为准。
- `AI工具使用说明.md` 与论文附录 C 使用相同口径，单独列出工具信息、具体用途、人工核验和责任边界。
- `src/outputs/` 仅保留正文表图所需结果和有解释价值的对照实验，不含缓存、运行日志或 RL 试验结果。
- 参考资料只收录正文实际引用文献及与正式方法直接相关的研究记录。
- 材料中不包含队员姓名、账号凭据或其他个人信息。
