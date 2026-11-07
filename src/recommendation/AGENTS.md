# B：推荐模块的修改边界

- 负责人：成员 B，账号待 A 指定。代码、测试、配置、依赖和说明均写在 src/recommendation/。
- 不修改 src/data_evaluation/、src/knowledge/ 或任何公共文件，不直接修改 third_party 子模块；所需公共改动在 TASKS.md 提议，由 A 处理。
- 读取原始材料和 A 的病例产物；只在 data/processed/recommendation/、outputs/recommendation/、models/recommendation/ 生成本地文件。
- 药物映射、模型词表、EHR/DDI 图由 B 负责，编号与版本必须一致；EHR 图只从训练数据构建。未映射药物不能视作没有相互作用。
- 从 b/ 分支提 PR，只提交本目录；手动请求 @lifan25 审核，不向 main 推送，不自行合并。
- 验收按 TASKS.md。未实际运行不报告通过，合成数据实验与真实病例实验分开说明。
