# 上游代码

两个目录通过 Git 子模块关联。子模块让主仓库记录上游地址和固定提交，原始文件仍来自作者仓库，不把其他人的源码重新宣称为本项目实现。

| 目录 | 来源 | 角色 |
|---|---|---|
| SSPNet | https://github.com/ResearchGroupHdZhang/SSPNet | IJCAI 2025 SSPNet 官方实现 |
| Diaformer | https://github.com/jymChen/Diaformer | BIBM 使用的问诊依赖，不是 BIBM 完整实现 |

首次克隆：

```powershell
git clone --recurse-submodules https://github.com/lifan25/mmagent.git
```

已经克隆：

```powershell
git pull --ff-only
git submodule update --init --recursive
```

当前固定版本可用 git submodule status 查看。子模块更新不自动跟随作者最新分支，避免各成员运行不同代码。

Diaformer 当前版本已附带 DXY/Muzhi/Synthetic 目录及部分病例、词表和预处理文件；这些文件仍由上游提供，本次未执行 pickle 反序列化、预处理或模型训练。存在文件不表示划分和论文版本已经核对。

SSPNet 当前版本仍缺公开说明中列出的部分预处理及映射材料。子模块完整拉取不等于已具备训练条件。

BIBM 完整代码、提示词、知识规则与 MLN 设置仍待向老师取得。使用和修改上游材料时保留原作者来源，具体再分发条件按上游许可或作者授权确认。
