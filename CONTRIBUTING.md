# 三人分工、修改范围与 PR 规则

更新：2026-11-07。由仓库所有者 lifan25 统一审核、合并其他成员的 PR；不要求创建 Issue。

## 1. 每人一个模块目录

| 角色 | 人员 | 日常允许修改的目录 | 负责什么 |
|---|---|---|---|
| A：组长 | @lifan25（你） | src/data_evaluation/ | 数据组织、患者划分、公共评价、最终集成；审核 B/C 的 PR |
| B：推荐 | 成员 B，姓名/账号待你指定 | src/recommendation/ | 药物映射、模型词表、EHR/DDI 图、SSPNet 适配、训练与推理 |
| C：知识 | 成员 C，姓名/账号待你指定 | src/knowledge/ | BIBM 知识提取、规则与 MLN 诊断，以及后续用药核查 |

2026-11-07 的远程核查只显示 @qicishiaaa 一名已加入的协作者；尚未给该账号分配 B/C，不据此假设三人已经全部加入。B/C 确定后，由 A 在对应 TASKS.md 填写账号即可。

各模块的代码、测试、配置、额外依赖说明、实验汇总和 TASKS.md 都放在自己的目录。不要为了写一项功能同时修改三个目录。

## 2. 公共文件归 A 维护

以下公共路径由 A 统一修改：根目录文件、.github/、docs/、examples/、scripts/、configs/、tests/、third_party/ 以及 data/outputs/models 下受版本控制的说明文件。原上游子模块保持固定，不在子模块里直接改代码。

B/C 需要改变公共接口、根依赖或上游版本时，在自己 TASKS.md 写明建议、影响和理由，交 A 处理。不能在 PR 中顺便修改公共协议或另一成员的代码。需要联动时拆成各模块 PR，由 A 按依赖顺序合并。

这个范围是协作约定，不是 GitHub 的目录写权限。个人仓库的协作者权限覆盖整个仓库；CODEOWNERS 也不限制一个人只能编辑某个文件夹。

## 3. 不进入 Git 的本地运行文件

| 角色 | 可以生成的本地产物 |
|---|---|
| A | data/processed/data_evaluation/、outputs/data_evaluation/ |
| B | data/processed/recommendation/、outputs/recommendation/、models/recommendation/ |
| C | data/processed/knowledge/、outputs/knowledge/、models/knowledge/ |

这些目录由现有 .gitignore 排除。data/public/ 和 data/local/、data/reference/ 的原始文件只读，不覆盖；当前公开数据取得方式见 docs/resources.md。大型文件下载是本地操作，不代表它们已随 Git 克隆到其他同学电脑。

完整 MIMIC、其他受控病例、权重、密钥和逐病例日志不提交。已提交的官方 MIMIC Demo 五张表保留原始来源及许可证。可提交聚合统计、运行命令和明确虚构的协议样例。

## 4. PR 怎么走

PR 是提交给组长审核的一组修改。成员不直接向 main 推送，不自行合并任何人的 PR。

1. 从最新 main 建立自己的分支：A 用 a/主题，B 用 b/主题，C 用 c/主题。
2. 修改自己的目录，执行相应检查，并更新该目录 TASKS.md 的状态、证据和下一步。
3. 推送个人分支，向 main 提 PR；使用仓库 PR 模板说明修改、运行命令、实际结果和依赖。
4. 非草稿 PR 应自动请求 @lifan25 为 Reviewer（审核人）；确认审核人已出现，若没有再手动添加。草稿准备好后点击 Ready for review。B/C 不以互相批准代替 A 的审核。
5. A 检查目录范围、能否运行、接口是否一致、是否泄漏标签/数据，再给出修改意见或批准。
6. A 执行 Squash and merge，把该 PR 合成一个提交；其他成员不点击合并。

个人分支的首次操作示例（B；C 替换为 c/knowledge-first-step）：

```powershell
git switch main
git pull --ff-only
git submodule update --init --recursive
git switch -c b/recommendation-first-step
# 完成自己目录内的修改和检查后
git add src/recommendation
git commit -m "feat: add recommendation first step"
git push -u origin b/recommendation-first-step
```

然后打开 GitHub → Pull requests → New pull request，base 选 main，compare 选自己的分支。不要使用 git add . 混入另一模块的未提交文件。

A 自己的变更也尽量使用 a/ 分支留出可审阅记录。GitHub 不允许批准自己的 PR；可请同学复核，最终由 A 使用保留的管理员权限处理。A 可以直接发布自己的维护变更，但不能用管理员权限替 B/C 绕过审核。

## 5. 审核配置的真实状态

| 项目 | 当前状态 |
|---|---|
| 核验日期与方式 | 2026-11-07，通过 GitHub API 读取实际设置 |
| 仓库 | lifan25/mmagent，公开，main 为默认分支 |
| 组长权限 | lifan25 是管理员；普通协作者为 write |
| 分支保护 | main 的经典分支保护已启用；未叠加 Ruleset，不影响保护生效 |
| PR 与批准 | 普通成员必须走 PR；至少 1 次批准，且必须由 Code Owner 批准 |
| CODEOWNERS | .github/CODEOWNERS 的 * 指定 @lifan25；API 检查 errors=[] |
| 追加提交后的审核 | dismiss_stale_reviews=true，旧批准失效，需要重新审核 |
| 合并前讨论 | required_conversation_resolution=true，必须解决讨论 |
| 强推与删除 | allow_force_pushes=false、allow_deletions=false |
| 管理员 | enforce_admins=false，A 保留绕过权限，处理自己的变更 |
| 自动指定审核人 | 非草稿 PR 应自动请求 @lifan25；草稿需先 Ready for review |
| 自动测试门槛 | 尚未配置 required_status_checks；不能声称合并前自动测试已强制通过 |
| 最终点击合并 | 仍约定仅 A 操作；批准后具有 write 权限的成员技术上也可能合并 |

当前配置符合本项目方案：普通成员不能直接向 main 推送，其 PR 必须由 @lifan25 批准；管理员例外保留。本轮核验依据为服务端配置读取与 CODEOWNERS 有效性检查。

这些设置不限制成员只能编辑特定目录，也不会在批准后把合并按钮只留给 A。目录范围和仅 A 合并仍遵守本文件。后续增加可运行的自动检查后，再将具体检查配置为 main 的必需状态；不要先设置不存在的检查阻塞合并。

官方依据：[CODEOWNERS 的可用范围及作用](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)、[分支保护](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)。

## 6. 什么情况可以批准

- 修改限定在负责目录；跨目录需求已经拆开交 A 处理。
- 运行说明能复现报告内容；未实现、未运行、阻塞分别注明。
- 病例、模型词表、药物映射和图的版本一致；原始记录与推理输入分开。
- 训练/验证/测试按协议独立，当前药物答案不进入输入；EHR 图只用训练数据。
- 没有提交病例级日志、受控数据、权重或密钥。
- TASKS.md 对照验收标准更新，有实际证据，不只写“完成”。

第一阶段的具体任务和交付标准分别见三个模块的 TASKS.md。它们是唯一任务状态入口，不再建立平行任务表。

