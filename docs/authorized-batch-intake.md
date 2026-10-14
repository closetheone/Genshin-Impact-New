# 获授权批次接入清单

`scripts/validate_authorized_batch.py` 只校验授权批次的元数据，不读取或保存来源正文。它用于授权确认后的第一道接入检查，不能替代正文数据契约、来源定位、分支核验或关系证据审核。

可先从台账生成空白模板；模板故意不能通过批次校验，必须在取得书面确认后补齐授权字段和记录元数据：

```bash
python3 scripts/create_authorized_batch.py \
  --source-id bwiki_genshin \
  --page-id audit:bwiki-task \
  --output /tmp/bwiki-authorized-batch.json
```

模板只包含页面 ID、用途清单和空白字段，不包含正文。不要把网页 HTML、Markdown 或对白复制到模板；正文应在授权范围内单独整理为待校验 fixture。

批次清单使用 `authorized-batch-0.1` 格式，至少记录：

- `source_id`、授权记录定位、授权核验日期、授权范围和有效期；
- 请求用途（例如 `collect`、`store`、`display`），且每项必须在来源台账中明确获准；
- 首批页面 ID、批次快照 ID，以及每条记录的稳定来源定位、内容类型和可选修订 ID；
- 不包含 `text`、`body`、`content`、HTML、Markdown 或其他正文载荷。

示例命令：

```bash
python3 scripts/validate_authorized_batch.py /path/to/authorized-batch.json \
  --audit data/source-audit.json
```

命令成功只表示元数据和来源准入字段满足第一道门槛。之后仍需在授权范围内准备独立 fixture，运行 `scripts/validate_sample.py` 和完整回归测试，再由导入流程写入数据库。当前三项来源仍处于待确认状态，仓库没有可通过的真实批次文件。
