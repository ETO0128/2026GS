# 2026 中国大学生数学建模竞赛项目

本仓库用于 **2026 年中国大学生数学建模竞赛（CUMCM）** 的赛前准备、论文撰写与材料整理。目前仓库以 LaTeX 论文模板为基础，后续可按比赛进度逐步补充建模代码、数据、图表和最终提交材料。

## 目录结构

```text
2026GS/
├── MODELING_PLAN.md  # C 题建模方案、难点与团队分工
├── TEAM_GIT_GUIDE.md # 团队 Git、SSH 与分支协作手册
├── problems/      # 竞赛题目、数据附件与结果模板
├── src/figure/    # 论文图片与绘图资源
├── src/py/        # 建模、求解、结果写入与绘图代码
├── src/tex/       # 正式论文、LaTeX 模板和样式文件
└── example.pdf    # 模板编译效果示例
```

## 团队协作

团队采用 `cmx`、`xtc`、`lcy` 三个个人分支开发，稳定内容最终合并到 `main`。首次配置 GitHub SSH、下载仓库、日常提交和处理冲突的方法见 [`TEAM_GIT_GUIDE.md`](TEAM_GIT_GUIDE.md)。

当前选定 C 题，统一数学模型、四问依赖关系、强化学习路线、难点和分工见 [`MODELING_PLAN.md`](MODELING_PLAN.md)。

## 问题跟踪

题意歧义、数据异常、模型假设、程序错误、公共接口和论文待办等需要全队关注的事项，统一使用 [GitHub Issues](https://github.com/ETO0128/2026GS/issues) 记录。Issue 属于 GitHub 仓库功能，不能通过普通的本地 `git commit` 创建。

最简单的创建方式是在仓库网站进入 `Issues`，点击 `New issue`，写清问题、影响范围、当前判断和需要采取的下一步操作。不要在 Issue 中发布密码、SSH 私钥、Token、手机号或其他敏感信息。

已经安装并登录 GitHub CLI 的队员也可以在本地终端创建：

```powershell
gh issue create
```

提交或 Pull Request 可以使用 `#编号` 关联 Issue；若合并后应自动关闭该问题，在 Pull Request 描述中写：

```text
Closes #编号
```

## 论文写作与编译

- 正式论文统一在 [`src/tex/main.tex`](src/tex/main.tex) 中编写。
- 论文图片源文件统一放入 `src/figure/`；同步至在线平台时，将其中的图片上传到
  在线工程根目录的 `figures/` 文件夹，`main.tex` 使用 `figures/...` 路径引用。
- `src/tex/example.tex` 仅作为模板用法参考，不在其中撰写正式论文。
- 不在本地编译 LaTeX。团队统一在[上海交通大学 LaTeX 平台](https://latex.sjtu.edu.cn/project/6aa2629ebd92933f73a45794)编译；将 `src/tex/` 内的文件放在在线工程根目录，并将 `src/figure/` 内的图片上传到在线工程的 `figures/` 文件夹。
- 编译前后根据当年竞赛官方要求检查封面、编号页、承诺书及 AI 工具使用声明等内容。

模板的详细说明与更新记录见 [`src/tex/README.md`](src/tex/README.md)。

## 后续规划

- 整理赛题分析、假设与符号说明
- 按题目维护数据处理和建模代码
- 统一保存论文所用图表与实验结果
- 记录模型验证、灵敏度分析和迭代过程
- 汇总最终论文及相关提交材料

## 注意事项

- 竞赛格式和提交要求以 2026 年官方通知为准。
- 请勿将报名号、队员个人信息、账号凭据或未脱敏的敏感数据提交到公开仓库。
- 向在线平台同步时，应同时上传 `src/tex` 中的 LaTeX 文件和 `src/figure/` 中使用的图片；
  在线工程采用 `main.tex` 与 `figures/` 同级的目录结构。

## License

仓库中的 LaTeX 模板沿用其原有许可与版权声明；团队新增内容的使用方式另行约定。
