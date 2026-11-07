# C：知识模块的修改边界

- 负责人：成员 C，账号待 A 指定。代码、测试、配置、候选规则和说明均写在 src/knowledge/。
- 不修改 src/data_evaluation/、src/recommendation/ 或任何公共文件，不直接修改 third_party 子模块；公共改动在 TASKS.md 提议，由 A 处理。
- 原始数据与他人输出只读；生成物写入 data/processed/knowledge/、outputs/knowledge/、models/knowledge/，不提交病例、权重和密钥。
- BIBM 诊断复现与用药核查扩展分开。按共享协议保留未知信息、条件与来源；未映射的药物或未覆盖的规则不得给出通过结论。
- 大模型付费调用和发送病例到外部服务不因本分工自动获授权。离线样例必须标记 synthetic_fixture，不能冒充模型提取或 MLN 推理。
- 从 c/ 分支提 PR，只提交本目录；确认已自动请求 @lifan25 审核，缺失时手动添加。不向 main 推送，不自行合并。实际进度和验收证据维护在 TASKS.md。
