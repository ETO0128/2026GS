# 第一、二问代码

`question1.py` 使用 10 分钟分辨率的确定性线性规划求解第一问，将结果写入官方
`result1.xlsx`，并使用 Matplotlib 生成论文图表。

## 模型口径

- 附件中的负荷和光伏是功率，统一乘 `1/6 h` 转换为电量。
- 充电量和放电量均定义为交流母线侧电量。
- 储能状态方程为 `e[t+1] = e[t] + 0.9*c[t] - d[t]/0.9`。
- 每个时段的充电量和放电量上限为 `5000/6 = 833.3333 kWh`。
- 储电量保持在 `1200--10800 kWh`，并强制 `e[0] = e[144] = 6000 kWh`。
- 允许弃光，不允许向外网售电。
- 在最低购电费不变的前提下，第二次线性规划最小化充放电总量，消除同时充放电的退化解。

附件和模板按 `0:10, ..., 23:50, 0:00+1` 排列。程序把 `0:00+1` 对应的周期时段
旋转到优化序列开头，使储能状态从 0:00 开始计算，完成后再按模板顺序写回。

## 运行

在项目根目录执行：

```powershell
python -m pip install -r src/py/requirements.txt
python src/py/question1.py
```

默认输入、模板和输出分别为：

```text
problems/C题/附件/附件1.xlsx
src/附件5/result1.xlsx
src/附件5/result1.xlsx
```

也可以通过 `--input`、`--template` 和 `--output` 指定其他路径。程序求解后会输出
论文表 1 所需的六个时段、全天购电量、购电费以及约束检查相关汇总信息。图表默认
保存到 `src/figure/`；如果只需要更新结果文件，可添加 `--no-plots`。

## 问题二

`question2.py` 从 2025 年 1 月 1 日起逐日顺序运行，1 月作为冷启动期，正式结果覆盖
2 月 1 日至 12 月 31 日。任一天 0:00 的预测只读取此前已经发生的数据，日初储电量
继承上一日实际结束值；全天计划购电一旦确定便不再修改，供电缺口按同时段正常电价的
5 倍计入紧急购电。

正式基线采用最近七日的负荷、光伏点预测，并依据紧急购电倍率对应的报童模型临界分位
数，以历史净负荷的 80% 经验分位曲线制定风险修正后的购电计划。程序还实现了昨日同
期、星期类型以及“日历分组与形状筛选后指数衰减”的相似日预测，用于同口径消融比较。

随机规划实验保留同一历史日的完整 144 点负荷与光伏残差，先按季节、星期类型和曲线
相似度筛选场景，再以 `similarity * lambda ** age_days` 确定场景概率。第一阶段共同决定
全天计划购电和储能动作，第二阶段分别结算各场景的紧急购电与剩余电量。参数只使用
1 月实际运行费用校准，避免以 2--12 月正式评价结果反向选参：

```powershell
python src/py/question2.py --forecast seven_day --planner stochastic --calibrate-scenarios
```

当前数据上校准得到 28 个场景和 `lambda=0.90`。该方案降低了紧急购电费用，但全年
总费用高于 80% 分位基线，因此暂不写入正式 `result2.xlsx`，仅作为风险消融保留。

在项目根目录运行：

```powershell
python src/py/question2.py
python src/py/question2.py --write-results --compare --plots
```

第一条命令仅求解并打印指标；第二条命令会填充官方 `src/附件5/result2.xlsx`，生成
`src/data/question2_summary.xlsx`，并把论文图保存到 `src/tex/figure/`。完整测试命令为：

```powershell
python -m unittest discover -s src/py -p "test_*.py" -v
```
