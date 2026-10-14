# 真实来源准入门槛

`data/source-audit.json` 只保存页面和政策元信息，不保存第三方正文。`scripts/check_source_admission.py` 根据这份台账检查某个来源是否可以进入指定用途；它不会下载、解析或导入正文。

准入必须同时满足：页面的 `admission_status` 为 `allowed` 或 `limited`，有非空的 `authorization_confirmed_by`，并且命令请求的每一项用途都明确为 `allowed`。`unknown`、缺少核验人或只有站内编辑规则时都会拒绝。`limited` 表示仍需按台账中的条件限制用途，命令会按请求用途逐项检查。

当前审计记录中的 BWIKI、观测枢和空荧酒馆页面都处于待确认或用途未知状态，因此收集和存储检查应失败：

```bash
python3 scripts/check_source_admission.py --source-id bwiki_genshin
```

取得明确记录后，可以按实际范围检查，例如：

```bash
python3 scripts/check_source_admission.py \
  --source-id bwiki_genshin \
  --require collect \
  --require store \
  --require display
```

命令的成功只说明台账中的准入字段满足项目门槛，不证明来源内容真实、完整或没有其他法律限制；正文导入仍需经过数据契约、来源定位、分支和关系证据核验。没有明确的外部授权记录时，继续使用原创合成样本。
