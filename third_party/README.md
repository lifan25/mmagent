# 上游代码

| 目录 | 原始来源 | 固定提交 | 用途 |
|---|---|---|---|
| SSPNet | https://github.com/ResearchGroupHdZhang/SSPNet | 4a2695ec67e0dc30cd3fa8e67a4f1536f0bfc90d | SSPNet 官方实现 |
| Diaformer | https://github.com/jymChen/Diaformer | 45491f33145003290278d0eacdc87a1d1d786b2d | BIBM 的问诊依赖，不是 BIBM 完整实现 |

两个目录通过 Git 子模块关联，保留原作者来源和固定版本。同步命令：

```powershell
git submodule update --init --recursive
```

不自动升级上游提交；需要升级时先核对是否影响实验。

Diaformer 附带的 DXY、Muzhi、Synthetic 病例文件已经做过只读结构与数量检查。SSPNet 尚缺部分预处理和辅助数据，BIBM 完整实现待老师提供。当前状态见 [资源清单](../docs/resources.md)。

在自己的模块内保存适配代码、配置和实验记录。使用上游内容遵循其许可或作者授权，不重新宣称为本项目原创。
