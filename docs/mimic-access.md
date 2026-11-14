# MIMIC-IV 本人申请与当前公开数据准备

核查日期：2026-11-14。当前尚无完整 MIMIC-IV 访问权限；已准备官方公开 Demo 的五张表。申请、培训和协议由本人完成，代码与数据接口准备可以并行推进。

## 1. 注册并填写研究者身份

1. 打开 [PhysioNet 登录入口](https://physionet.org/login/)，已有账号直接登录；没有账号点击 **Create an account**，完成邮箱验证。
2. 打开 [Credentialing 申请入口](https://physionet.org/settings/credentialing/)（未登录时会先跳登录页）。真实填写姓名、学校、院系、学生身份和研究用途；有学校邮箱时优先使用。
3. 学生按页面要求提供导师或能够核实学籍/机构身份的负责人信息；不要填写自己或另一位同学。先核实老师姓名、职务与工作邮箱，不臆造机构和推荐人。
4. 研究用途按实际项目填写：研究历次就诊的药物集合推荐及可追溯的药物相互作用核查，进行患者级划分和回顾性评价。不要声称已有临床部署或未取得的审批。

机构身份核验与培训报告审核是不同事项，可以同时准备。官方申请说明见 [MIMIC 获取权限步骤](https://mimic.mit.edu/docs/faq/how-to-get-access.html)。页面给出的处理周期只是预期，不保证某日获批；资料不完整可能延长处理时间。

## 2. 本人完成 CITI 培训

按照 [PhysioNet 官方 CITI 操作说明](https://physionet.org/about/citi-course/)进入 [CITI Program](https://about.citiprogram.org/)，注册/登录个人账号。

1. 在 **My Courses → Add affiliation** 搜索 **Massachusetts Institute of Technology Affiliates**。这是官方提供给非 MIT 人员访问培训的途径，不表示你在 MIT 就读或工作；个人信息仍填写真实学校资料。
2. 按当前页面完成机构关联和问卷，加入 **Data or Specimens Only Research**；官方说明同时要求完成 **Conflicts of Interest** 模块。课程菜单可能调整，以该官方说明和当前页面为准。
3. 本人学习并完成课程测验，不让助手代做。不要选择付费 Independent Learner 路线来替代官方机构关联。
4. 在 CITI 的 **Records → Completion Record → View-Print-Share / view-print** 下载完整的 **Completion Report（培训报告）**。PhysioNet 要求报告，不只是单页 Certificate（证书）。
5. 到 [PhysioNet Training 页面](https://physionet.org/settings/training/)提交报告，检查课程、姓名及有效状态。

培训报告及账号材料留在个人安全位置，不放入仓库，也不粘贴密码或验证码到聊天中。

## 3. 签署 MIMIC-IV 对应协议

1. 身份与培训状态满足要求后，打开 [MIMIC-IV 3.1 官方项目](https://physionet.org/content/mimiciv/3.1/)。
2. 阅读页面 **Access / Files** 部分和 **Data Use Agreement（数据使用协议，DUA）**；由本人确认并签署。
3. 回到项目页，确认已具备文件访问权限。记录获准的数据集和版本即可，不共享登录凭证。
4. 后续实际需要接触完整数据的 B/C 也必须取得各自授权。一个人的账号不替整个小组授权；MIMIC-III、MIMIC-IV-Note 等项目另有各自协议，当前无需一并申请所有扩展库。

本轮没有代申请、代签协议或访问完整受控库。获批后先确认权限状态和本地存储空间，再按研究需要取得表；无需先下载全部 ICU 高频数据。原始数据、逐病例文件及凭证不上传 GitHub，不传给未经许可的外部模型服务。

## 4. 已经准备好的公开文件

官方来源：[MIMIC-IV Clinical Database Demo 2.2](https://physionet.org/content/mimic-iv-demo/2.2/)。该 Demo 无需完整库权限，采用 **Open Data Commons Open Database License v1.0**。它有 100 位真实患者，适合验证读取和关联逻辑；它是完整版子集，不能作为完整版的独立外部测试集，也不能用这点样本替代正式研究数据。

本地目录：`data/local/mimic-iv-demo-2.2/`。现有五张表均已下载并成功解压读取，原文件仍保留为 `.csv.gz`：

| 文件 | 数据行数（不含表头） | 压缩字节数 |
|---|---:|---:|
| patients.csv.gz | 100 | 1,083 |
| admissions.csv.gz | 275 | 11,072 |
| diagnoses_icd.csv.gz | 4,506 | 24,198 |
| procedures_icd.csv.gz | 722 | 6,602 |
| prescriptions.csv.gz | 18,087 | 606,447 |

同时保留官方 `LICENSE.txt` 与 `source.json`。后者记录固定版本、精确下载地址、列名、行数、字节数和文件摘要。这些文件在 Git 忽略目录内，未提交；其他人 pull 不会得到数据，需要自行运行下载脚本。275 次原始住院不等于 275 条有效预测样本，尚未进行本批 Demo 的有效队列筛选、药物映射或模型评价。

另一个已准备的公开材料是 [LLM-Uncertainty-DDI](https://github.com/AIChemist-Lab/LLM-Uncertainty-DDI)，本地放在 `data/local/llm-uncertainty-ddi/`：`drug5.csv`、原始 MIT `LICENSE`、`source.json`。固定提交为 `9872bb0c3e28cd03a7d460cdde3f01e0e8a26542`。核验得到 250 条药物清单，C/D/X 分别 81/92/77 条；每例 4–6 种药。它不含纵向病例，只能辅助评价相互作用核查模块；全部清单含阳性目标，不能单凭它估计整张清单无相互作用时的误报率。公开数据也可能进入模型预训练；“零样本”仅表示本项目不提供示例或微调，不证明模型从未见过这些材料。本次仅下载与聚合核验，没有逐例分析或调参。

复现下载（仓库根目录，使用已有 Python；仅标准库，无新增依赖）：

```powershell
.\.venv\Scripts\python.exe src/data_evaluation/fetch_public_validation.py
```

脚本只访问固定提交的 DDI 文件和上述公开 Demo，不访问受控库。已有原始文件不覆盖；已有来源记录存在时核验文件摘要。输出只有字段核验后的聚合统计，不打印病例。
