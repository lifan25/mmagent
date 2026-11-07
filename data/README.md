# 本地数据

除 public/mimiciii-demo-1.4 内明确列出的官方公开 Demo 与许可证外，此目录其他数据被 Git 忽略。数据申请、来源、版本和状态记录在 ../docs/resources.md。

将受控原始与处理后数据留在符合来源协议的本地或授权环境中。不要提交受控患者 ID、病例样本、数据压缩包或可重建病例的中间文件。官方公开 Demo 保留其原有开放许可；虚构接口示例放在 ../examples/。

已获访问权限、取得文件、完成预处理分别记录。不要共享数据账号。文件存入本目录不表示已获授权。

## 本阶段目录约定

| 路径 | 内容 | 谁读取/生成 |
|---|---|---|
| public/mimiciii-demo-1.4/ | 已提交的官方 Demo 原表及许可证 | A/B 读取 |
| local/synthea-apr2020/ | 另行下载的合成原表 | A/B 读取，原表不覆盖 |
| reference/MoleRec/ | 另行取得的映射、参考脚本和 DDI | B 读取，保留来源与许可证 |
| processed/data_evaluation/ | 日后由 A 生成的原始编码病例、划分与清单 | A 生成、B 读取 |
| processed/recommendation/ | 日后由 B 生成的模型记录、词表与图 | B 生成，A/C 按接口读取 |
| processed/knowledge/ | 日后由 C 生成的规则/诊断中间材料 | C 生成，A 按约定核验 |

processed 三个目录只是产物位置约定，框架整理未生成这些业务数据，不用 .gitkeep 使它们进入 Git。下载步骤见 [开工说明](../docs/onboarding.md)，交接字段见 [共享协议](../docs/protocol.md#9-开发交接文件约定草案)。

