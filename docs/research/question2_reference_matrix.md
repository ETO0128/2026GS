# 问题二参考矩阵：预测、日前计划与不确定性调度

**记录日期：2026-09-11。** 本矩阵把可复核的来源与设计中的建模主张逐一对应。\
“基准阶段”只指首个可复现的确定性闭环；“后续创新阶段”须在基准通过审计后再作为\
对照或消融加入。题目给定的物理参数、5 倍紧急购电规则和 80% 分位数的一阶条件不由\
下列文献设定。

| Claim | Source | Evidence | Use in Question 2 | Limit |
| --- | --- | --- | --- | --- |
| Forecast validation must preserve time order | Hyndman and Athanasopoulos, *Forecasting: Principles and Practice*, §5.10 [11]（作者维护教材页面） | 该节定义每个测试点只用其之前的观测作训练集，并称为 rolling forecasting origin；还说明可用多步误差及以交叉验证 RMSE 选模型。 | **基准阶段采用：** 月度/逐日 expanding-window 验证 MAE、RMSE、Bias；任何候选预测器、窗口或回退规则只能用决策日前的误差选择。 | 是通用时间序列评估原则，不规定本题的 144 点日曲线、工作日类别或成本目标；成本感知选择留作后续阶段。 |
| Similar days can be selected by calendar and curve similarity | Mandal, Senjyu, Urasaki and Funabashi (2006) [12]；PV 侧补充 Acharya, Wi and Lee (2020) [13] | [12] 用带权 Euclidean 距离寻找历史相似日，并按天气/季节差异进行短期负荷预测；[13] 的题名和方法对象表明可对小规模 PV 做日前的相似日检测及选择性天气变量。 | **后续创新阶段采用：** 在历史日期中先按工作日、月份/季节等日历条件筛选，再以完整日曲线距离排序；负荷与 PV 分别选择候选数及衰减参数。 | [12] 是数小时负荷 ANN 案例，并不验证本题的指数衰减权重或 PV 规则；[13] 是 PV 方法补充。二者均不能替代严格的滚动验证、也不能使用未来天气/实测。 |
| Day-ahead schedules and real-time controls can be separated | Parisio, Rikos and Glielmo (2016) [14] | 该同行评审微网案例明确以 stochastic MPC 的在线优化管理运行，并列出 two-stage stochastic programming 和 MILP 为关键词；它提供“计划层—随信息到达的在线控制层”这一架构先例。 | **基准阶段采用：** 0:00 固定普通购电计划；日内执行只可按已观测源荷调整储能并以紧急购电补缺。 | 文献不是本赛题结算规则，且不证明“计划购电不得修改”这一题目约束；本实现须独立审计信息边界与能量平衡。 |
| Whole-day paired residual scenarios preserve source/load dependence | Liu *et al.* (2017) [15] | 论文针对日前微网调度同时纳入 PV 与负荷不确定性，并明确分析二者的相关性（天气会共同影响二者）；其模型是相关不确定性的 P-OPF。 | **后续创新阶段采用：** 从同一历史来源日联合抽取 144 点负荷、PV 残差，保留来源日期、曲线内连续结构和源荷配对，供情景 LP 使用。 | [15] 采用相关性与两点估计，不提出“整日配对残差重抽样”；本项目的经验场景生成是为保留该依赖关系作出的实现选择，须与逐时独立抽样消融比较。 |
| CVaR can be represented in an optimization model | Rockafellar and Uryasev (2000) [16]（原论文；作者维护发表列表亦列出该文） | 原论文给出以阈值和正部损失辅助变量表示 CVaR 的优化构造，使有限离散情景下的尾部损失项可线性化。 | **后续创新阶段采用：** 在两阶段随机 LP 的紧急购电费用上加 Rockafellar--Uryasev epigraph；置信水平、风险权重均由仅含过去日的滚动验证选取。 | 论文的金融损失例子不校准微网的置信水平、权重或情景分布；CVaR 是风险扩展/消融，不是首个确定性基准目标。 |
| Stored energy has a cross-day opportunity value | Jiang and Powell (2015) [17] | 该 INFORMS 论文把电池状态置于逐时竞价的 approximate dynamic programming 决策中，学习并使用未来价值近似；因此储电的价值不只限于当前时段。 | **后续创新阶段采用：** 用截至决策日前的运行结果拟合 SOC 的分段线性终端价值；历史不足时回退固定安全储备。 | [17] 研究的是小时级实时市场竞价，未给出本题“次日节省”拟合式或保证其凸性；网格、断点、符号与回退阈值均须由本项目滚动验证。 |

## 支撑材料、状态与非主张

- **类似日术语整理（非方法主证据，后续阶段）：** Borunda *et al.* (2026) [18] 回顾\
  2000--2025 年短期负荷相似日研究，并按 similarity 定义和 forecast generation 组织\
  分类。它只帮助统一术语；相似日的具体方法主张仍由原始同行评审文献 [12] 支撑。
- **80% 分位数是本设计的可检验推导，不是外部经验参数：** 在无储能、正常价格为\
  \(p\)、缺口价格为 \(5p\) 的简化损失下，次梯度条件给出\
  \(\Pr(D>g)=1/5\)。故使用净需求 80% 条件分位数作**后续阶段**理论基线；它不得\
  替代含 SOC 与跨时段约束的联合优化。
- **两阶段随机 LP 也先作为后续阶段：** [14] 给出微网随机/在线优化的架构背景，\
  [15] 给出源荷相关不确定性的理由，[16] 仅给出 CVaR 的可优化表示。它们并不共同\
  推导本题的变量、概率或物理约束；这些由题目与设计的显式方程定义。

## 可用于 LaTeX 的书目信息

对应条目已添加到 `src/tex/references.txt` 的 [11]--[18]。所有链接均为 DOI 落地页、\
作者维护页面或作者维护的在线教材；访问日期为 2026-09-11。
