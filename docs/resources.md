# 论文、代码、数据与资源清单

记录日期：2026-11-07。下表是启动时的已知线索，供成员继续核查，不代表已下载数据或已验证模型。

## 来源入口

| 项目 | 入口 | 启动状态 | 后续核查负责人 |
|---|---|---|---|
| BIBM 2023 | DOI: 10.1109/BIBM58861.2023.10385557；用户已提供本地 PDF | 全文可读；独立完整作者实现尚未取得 | C |
| SSPNet | [正式论文](https://www.ijcai.org/proceedings/2025/1052.pdf)；[作者仓库](https://github.com/ResearchGroupHdZhang/SSPNet) | 公开代码可查看；当前会话未运行训练 | B |
| Diaformer | [作者仓库](https://github.com/jymChen/Diaformer) | 已作为 third_party/Diaformer 子模块取得；上游自带 DXY/Muzhi/Synthetic 目录与部分文件；划分与完整性待 C 核对 | C |
| MIMIC-III Demo | [官方公开 Demo](https://physionet.org/content/mimiciii-demo/1.4/) | 已提供五张表、下载检查程序与许可说明，见 ../data/public/mimiciii-demo-1.4/README.md；不是完整复现数据 | A/B |
| MIMIC-III | [v1.4](https://physionet.org/content/mimiciii/1.4/) | 受控访问；成员申请情况未确认 | A 汇总 |
| MIMIC-IV | [官方数据页](https://physionet.org/content/mimiciv/) | 后续扩展；复现所需具体版本待核对 | A/B |
| GPU | 老师/学院/实验室资源待询问 | 用户说明目前没有可用算力 | A |
| 大模型调用 | 服务、模型版本、账号与预算待确认 | 尚未确认；未执行任何付费调用 | C/A |

BIBM 的本地 PDF 不随此仓库分发。文献资料、上游代码和数据各自遵循原有许可；仓库可访问不等于允许重新发布所有文件。

本次明确加入的公开 Demo 例外保留原始 ODbL 许可证和来源。完整 MIMIC 尚未取得。上游代码固定提交可用 git submodule status 查看。

## 已取得的诊断数据文件

- third_party/Diaformer/data/dxy_dataset：dxy_dialog_data_dialog_v2.pickle、goal_set.p、vocab.txt、preprocess.py 等。
- third_party/Diaformer/data/muzhi_dataset：acl2018-mds.p、goal_set.p、vocab.txt、preprocess.py。
- third_party/Diaformer/data/synthetic_dataset：goal_set.p、vocab.txt、preprocess.py。

这些是上游公开仓库自带文件，本次没有反序列化、运行预处理或训练。C 应核对其是否符合 BIBM 的版本、样本数及划分；文件存在不等于复现完成。

## 已知待核查点

- SSPNet README 列出了预处理和映射文件，但启动时检查的公开目录及 ZIP 未见完整材料。B 应记录自己复核的版本与缺少的具体文件。
- SSPNet 正文引用附录 A/B/C，目前取得的正式九页 PDF 未包含这些附录，需索取或核对其他作者材料。
- SSPNet 正文学习率为 1e-4，公开 main.py 默认值为 5e-4；采用哪套设置及原因必须记录。
- 作者报告使用 12GB TITAN V，不表示已经实测的最低显存需求，也不表示 CPU 能在可接受时间完成全量实验。
- 不能只下载最新 MIMIC 版本就声称与论文数据一致，应核对原论文版本、筛选与编码方法。
- DXY/Muzhi 的训练/测试划分及验证集处理要查实际来源，不能自行改动后不说明。

## 成员填写表

状态可用：未核查、入口可读、已申请、已获权限、已下载、已验证、受阻。不要混用。

| 资源及版本 | 来源/版本标识 | 实际状态 | 核查日期 | 证据或文档链接 | 负责人 | 阻塞及下一动作 |
|---|---|---|---|---|---|---|
| 待填写 | 待填写 | 未核查 | 待填写 | 待填写 | 待认领 | 待填写 |

数据下载、身份审核和本地文件可读取是不同状态；不在此表写账号、密码、证件或真实病例信息。

## 向老师集中确认的问题

1. 两篇是否有完整作者代码、预处理脚本、补充材料、规则文件、提示词或已训练权重？
2. 是否有已经获准使用的数据与访问流程？团队成员各自需要办理什么？
3. 是否能提供单卡服务器，何时可用、如何排队？
4. 是否有 GPU 租用和大模型调用预算？如有，额度和使用方式是什么？
5. “结合”是否接受先做推荐与知识核查，再扩展症状诊断接入？

以上是待确认问题清单，不代表已经联系老师或取得任何授权。

