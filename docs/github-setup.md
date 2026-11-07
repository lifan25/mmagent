# 获取代码与日常同步

用户已确认仓库创建、上传并邀请成员。仓库地址：https://github.com/lifan25/mmagent

## 首次取得项目

```powershell
git clone --recurse-submodules https://github.com/lifan25/mmagent.git
Set-Location mmagent
python scripts/fetch_public_demo.py --check-only
```

## 已经有本地项目

在自己的项目根目录执行：

```powershell
git pull --ff-only
git submodule update --init --recursive
python scripts/fetch_public_demo.py --check-only
```

SSPNet、Diaformer 分别位于 third_party，版本由主仓库固定。BIBM 的完整实现仍待取得。

## 日常记录与同步

每个人直接更新自己模块的 TASKS.md。以 B 为例：

```powershell
git add src/recommendation/TASKS.md
git diff --cached
git commit -m "docs: update recommendation progress"
git push origin main
```

A/C 使用各自路径。不要求 Issue 或固定 PR 流程。跨模块接口或实验设置先在组内确认并记录。

git pull 提示本地有未提交修改时，先保存并提交自己的修改再同步。冲突先核对双方内容，不强制推送覆盖同伴成果。

## 数据范围

仓库包含官方公开 MIMIC-III Demo 五张原始表及许可证，可用于格式检查与流程准备。重新下载运行 python scripts/fetch_public_demo.py。

Demo 只有 100 名患者，不是 SSPNet 原论文的完整训练数据。完整 MIMIC 仍需成员各自取得访问权限。

