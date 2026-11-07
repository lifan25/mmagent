# GitHub 建仓与日常使用

A 负责首次建仓，B/C 按 CONTRIBUTING.md 协作。本地骨架不包含任何远程账号或远程仓库地址。

## 首次上传

1. 在 GitHub 新建名为 medical-medication-agent 的仓库，建议先设为 Private。
2. 先不要在 GitHub 自动生成 README、.gitignore 或 LICENSE，避免与本地内容冲突。
3. 邀请 B/C 为协作者，并确认他们能访问。
4. 在本地项目根目录打开终端，依次执行下列命令。

本地目录已初始化 Git 时直接使用以下命令；若复制来的文件夹没有 .git，先执行 git init -b main。

```powershell
git status
git add .
git diff --cached --stat
git diff --cached
git commit -m "docs: add phase one project framework"
git remote add origin YOUR_GITHUB_REPOSITORY_URL
git push -u origin main
```

先将 YOUR_GITHUB_REPOSITORY_URL 替换为真实仓库 URL。不要将访问令牌写进远程地址或文档。未配置 Git 用户信息时使用自己的 GitHub 身份完成设置，不使用其他成员身份。

检查暂存内容没有真实病例、数据或密钥后再提交。第一次上传由 A 执行；其余修改走 PR。

## 日常修改

B/C 首次用 GitHub 页面上的真实地址 clone。进入项目根目录，按任务建立分支：

```powershell
git switch main
git pull --ff-only
git switch -c docs/b-sspnet-preparation
```

修改与任务相关的文件，然后：

```powershell
git add docs/report-B.md
git diff --cached
git commit -m "docs: document SSPNet reproduction prerequisites"
git push -u origin docs/b-sspnet-preparation
```

随后在 GitHub 创建 Pull Request，选择一位其他成员评审。评审者确认任务验收条件，合并后更新对应 Issue。

## 首批建议任务

| Issue 标题 | 负责人 | 交付 |
|---|---|---|
| [P1-A] 建仓、认领角色和第一次协作合并 | A | 仓库、成员和 PR 记录 |
| [P1-A] 核实数据权限与计算资源 | A | resources.md |
| [P1-B] SSPNet 代码、数据依赖与启动检查 | B | report-B.md |
| [P1-C] BIBM/Diaformer 材料与规则样例 | C | report-C.md |
| [P1-ABC] 评审接口与实验协议 | A 汇总，B/C 确认 | protocol.md、走查记录 |
| [P1-ABC] 第一阶段验收 | A 汇总 | phase1.md 检查表、三份报告结论 |

代码尚未开始时，这些文档任务就是实际工作。不要用“目录已建好”替代资源与复现依赖的核查。

