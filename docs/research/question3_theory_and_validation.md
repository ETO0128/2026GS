# 问题三理论依据与模型调整结论

## 理论对应

1. 滚动时域：Silvente 等把微网供需与储能调度置于滚动时域框架，在新信息到达时冻结已
   执行决策并更新剩余时域。这直接支持本文 0:00/6:00/12:00/18:00 的递进决策结构。
2. 联合残差场景：两阶段随机规划要求场景保持随机过程的联合结构；本文按历史日保留连续
   负荷—光伏残差轨迹，不逐时独立拼接。
3. 滚动预测价值：Ghadimi 与 Powell 强调储能策略应在能够模拟预测持续更新的基准模型中
   评价，并用仿真优化调整参数化前瞻策略。这支持本文用全年顺序仿真评价节点和阈值。
4. 预测频率：已有微网滚动优化研究表明，新预报只有在剩余执行时域足够长时才有价值；
   本题 18:00 节点边际价值近零与这一机制一致。

## 已验证但不采用的调整

- 正式问题二七日均值负荷预测直接接入问题三：全年费用增加 317.74 万元。
- 光伏整点值改为十分钟线性插值：全年费用增加 55.98 万元。
- 场景概率加入相似度与时间指数衰减：全年费用增加 5.93 万元。
- 简单线性跨日终端价值：全年费用增加约 6.90 万元。

因此保留原滚动残差场景模型为正式方案，上述结构只作消融接口。不能仅因方法更复杂就
认定更优。

## 参考文献（IEEE）

[1] J. Silvente, G. M. Kopanos, E. N. Pistikopoulos, and A. Espuña, “A rolling
horizon optimization framework for the simultaneous energy supply and demand
planning in microgrids,” *Applied Energy*, vol. 155, pp. 485–501, 2015,
doi: 10.1016/j.apenergy.2015.05.090.

[2] J. Silvente, G. M. Kopanos, and A. Espuña, “A rolling horizon stochastic
programming framework for the energy supply and demand management in microgrids,”
*Computer Aided Chemical Engineering*, vol. 37, pp. 2321–2326, 2015,
doi: 10.1016/B978-0-444-63576-1.50081-9.

[3] S. Ghadimi and W. B. Powell, “Stochastic search for a parametric cost function
approximation: Energy storage with rolling forecasts,” *European Journal of
Operational Research*, vol. 312, no. 2, pp. 641–652, 2024,
doi: 10.1016/j.ejor.2023.08.003.

[4] J. R. Birge and F. Louveaux, *Introduction to Stochastic Programming*, 2nd ed.
New York, NY, USA: Springer, 2011.
