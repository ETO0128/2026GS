# 2026GS 团队 Git 协作手册

本手册面向第一次使用 Git 和 GitHub 的队员。团队采用“一人一个长期分支”的方式协作，最终通过 Pull Request 合并到 `main`。

## 分支分工

| 队员 | 工作分支 | 说明 |
| --- | --- | --- |
| cmx | `cmx` | 只在该分支完成自己的工作 |
| xtc | `xtc` | 只在该分支完成自己的工作 |
| lcy | `lcy` | 只在该分支完成自己的工作 |
| 全队 | `main` | 稳定版本，只通过合并更新，不直接在这里开发 |

最重要的规则：开始工作前确认自己位于正确分支；不要直接向 `main` 提交或推送。

## 一 首次配置 Git

### 1 安装 Git

从 [Git 官方网站](https://git-scm.com/download/win) 安装 Windows 版本。安装完成后打开 PowerShell 或 Git Bash，检查：

```powershell
git --version
```

### 2 设置姓名和邮箱

把示例内容替换成自己的姓名和 GitHub 邮箱：

```powershell
git config --global user.name "你的名字"
git config --global user.email "你的GitHub邮箱"
```

检查配置：

```powershell
git config --global --list
```

为了让 Git 状态中的中文文件名正常显示，可以执行：

```powershell
git config --global core.quotepath false
```

## 二 配置 GitHub SSH

SSH 配置在每台新电脑上做一次即可。私钥只能保存在自己的电脑上，绝对不要发给他人或提交到仓库。

### 1 生成密钥

在 PowerShell 中执行：

```powershell
ssh-keygen -t ed25519 -C "你的GitHub邮箱"
```

连续按回车可使用默认保存位置。建议为密钥设置一个自己能记住的密码。

默认生成两个文件：

- `id_ed25519`：私钥，不得分享；
- `id_ed25519.pub`：公钥，可以上传到 GitHub。

### 2 将公钥复制到剪贴板

```powershell
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub" | Set-Clipboard
```

打开 GitHub 的 `Settings` → `SSH and GPG keys` → `New SSH key`，填写一个便于识别的标题，粘贴公钥并保存。

### 3 测试连接

```powershell
ssh -T git@github.com
```

首次连接可能询问是否信任 GitHub 主机，确认显示的主机为 GitHub 后输入 `yes`。如果看到包含自己 GitHub 用户名的认证成功提示，就说明配置完成。

### 4 如果提示 Permission denied publickey

先启动 SSH Agent，再添加私钥：

```powershell
Get-Service ssh-agent
Start-Service ssh-agent
ssh-add "$env:USERPROFILE\.ssh\id_ed25519"
ssh -T git@github.com
```

如果 `Start-Service` 提示权限不足，请以管理员身份打开 PowerShell，执行：

```powershell
Set-Service ssh-agent -StartupType Automatic
Start-Service ssh-agent
```

如果当前网络屏蔽 SSH 的 22 端口，可在 `$env:USERPROFILE\.ssh\config` 中加入：

```text
Host github.com
    HostName ssh.github.com
    User git
    Port 443
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

保存后重新执行 `ssh -T git@github.com`。

## 三 获得仓库写入权限

仓库管理员需要在 GitHub 仓库的 `Settings` → `Collaborators` 中邀请其他队员。受邀队员必须先登录自己的 GitHub 账号并接受邀请，否则即使 SSH 测试成功，也可能没有向仓库推送代码的权限。

## 四 第一次下载项目

选择一个合适的本地目录，然后执行：

```powershell
git clone git@github.com:ETO0128/2026GS.git
cd 2026GS
```

确认仓库使用 SSH 地址：

```powershell
git remote -v
```

正常情况下会看到 `git@github.com:ETO0128/2026GS.git`。如果显示 HTTPS 地址，可以改成 SSH：

```powershell
git remote set-url origin git@github.com:ETO0128/2026GS.git
```

查看远端分支：

```powershell
git branch --all
```

根据自己的名字，只执行下面对应的一条命令：

```powershell
git switch cmx
git switch xtc
git switch lcy
```

检查当前分支：

```powershell
git branch --show-current
```

输出必须是自己的分支名。如果输出为 `main`，不要开始修改文件。

## 五 每次工作的标准流程

### 1 开始工作前拉取自己的最新版本

以下命令中的 `<你的分支>` 替换为 `cmx`、`xtc` 或 `lcy`：

```powershell
git switch <你的分支>
git pull --ff-only
git status
```

确认 `git status` 显示当前位于自己的分支，再开始编辑文件。

### 2 查看修改

```powershell
git status
git diff
```

`git status` 会列出新增、修改和删除的文件；`git diff` 会显示尚未暂存的文本变化。

### 3 提交修改

优先明确写出需要提交的文件，不要不加检查地使用 `git add .`：

```powershell
git add 文件名1 文件名2
git status
git commit -m "说明本次完成的工作"
```

提交信息示例：

```text
model: add linear programming baseline
data: clean photovoltaic forecast data
docs: write assumptions for problem one
fix: correct battery efficiency calculation
```

### 4 推送到自己的远端分支

```powershell
git push
```

绝对不要使用 `git push origin main`，也不要使用 `git push --force`。

## 六 同步 main 的最新内容

当其他人的 Pull Request 已经合并到 `main` 后，在自己的分支执行：

```powershell
git switch <你的分支>
git status
git fetch origin
git merge origin/main
git push
```

执行合并前，应先提交或妥善保存自己的修改，保证 `git status` 干净。

如果 Git 报告冲突：

1. 不要删除整个文件，也不要强制推送；
2. 打开标记冲突的文件，寻找 `<<<<<<<`、`=======` 和 `>>>>>>>`；
3. 与相关队友确认应该保留的内容；
4. 删除冲突标记，保存正确结果；
5. 重新提交并推送：

```powershell
git add 冲突文件
git commit -m "merge: resolve conflict with main"
git push
```

如果不确定如何处理，先停止操作，把 `git status` 的完整输出发到群里。

## 七 合并到 main

完成功能并确认代码、数据或论文内容可用后：

1. 把自己的分支全部提交并执行 `git push`；
2. 打开仓库的 GitHub 页面；
3. 点击 `Pull requests` → `New pull request`；
4. `base` 选择 `main`，`compare` 选择自己的分支；
5. 标题说明完成了什么，正文写明主要文件、运行方法和验证结果；
6. 请至少一名队友检查后再合并；
7. 合并完成后，各队员按照上一节同步最新的 `main`。

建议不要在三个人都大量修改同一个文件时才集中合并。一个独立且验证完成的小功能就可以提交一次 Pull Request。

## 八 推荐的文件分工方式

为降低冲突，尽量按目录或模块分工。例如：

```text
src/
├── data/          # 数据读取、清洗和特征构造
├── optimization/  # 线性规划与滚动优化
├── rl/            # 强化学习环境、训练和评估
└── evaluation/    # 指标、对比实验和绘图
```

论文源文件容易冲突。建议确定一人主要维护论文主文件，其他队员把文字、公式和图片放入独立章节文件或独立目录，再由负责人整合。

## 九 不应提交的内容

- SSH 私钥、密码、Token 和账号凭据；
- `~$` 开头的 Office 临时文件；
- Python 虚拟环境、缓存和临时输出；
- 可以由代码重新生成的大量中间结果；
- 包含队员身份证号、手机号等个人敏感信息的文件；
- 尚未确认来源和授权的大型外部数据。

提交前始终执行：

```powershell
git status
```

确认列表里没有私钥、密码、缓存或无关文件，再执行 `git commit`。

## 十 常用检查和恢复命令

查看当前状态和最近提交：

```powershell
git status
git log --oneline -10
```

撤销尚未暂存的某个文本文件修改：

```powershell
git restore 文件名
```

取消暂存但保留本地修改：

```powershell
git restore --staged 文件名
```

上述命令执行前要确认文件名。不要使用 `git reset --hard`、`git clean -fd` 或强制推送来处理不熟悉的问题。

## 十一 每次推送前的快速检查

```powershell
git branch --show-current
git status
git diff --cached
git push
```

确认四件事：当前是自己的分支、文件范围正确、没有敏感信息、提交内容能够运行或正常编译。
