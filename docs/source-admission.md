# 真实来源准入门槛

`data/source-audit.json` 只保存页面和政策元信息，不保存第三方正文。`scripts/check_source_admission.py` 根据这份台账检查某个来源是否可以进入指定用途；它不会下载、解析或导入正文。

需要向来源方取得确认时，按 [真实来源授权记录模板](source-authorization-request.md) 逐项记录对象、授权人、用途、条件和期限。

来源台账中的政策页和公开仓库许可证复核也只允许保存链接、标题、更新时间、摘要和范围判断。准入检查会拒绝保存政策原文或许可证文件原文的记录，并拒绝把 CC、MIT 或 MulanPSL 等许可证线索直接转换为某项来源用途的 `allowed`；仍需单独记录明确的授权人和用途范围。

准入必须同时满足：页面的 `admission_status` 为 `allowed` 或 `limited`，有非空的 `authorization_confirmed_by`、`authorization_reference`、`authorization_checked_on` 和 `authorization_scope`，其中核验日期使用 ISO `YYYY-MM-DD`，并且命令请求的每一项用途都明确为 `allowed`。`unknown`、缺少核验人、缺少可复核记录或只有站内编辑规则时都会拒绝。`limited` 表示仍需按台账中的条件限制用途，命令会按请求用途逐项检查。

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
