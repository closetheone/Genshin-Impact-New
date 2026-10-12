# 本机备份、恢复与发布回滚

适用对象：当前合成 SQLite 档案和本机私有反馈库。命令使用 Python 标准库，无公共维护 HTTP 接口。所有输出文件必须是新路径；工具不会覆盖运行中的数据库，也不会自动切换网站配置。

## 备份与核验

```bash
python3 scripts/maintain_archive.py verify --database data/local/archive.sqlite3
python3 scripts/maintain_archive.py backup --database data/local/archive.sqlite3 --output data/local/backups/archive-checkpoint.sqlite3
python3 scripts/maintain_archive.py backup --kind feedback --database data/local/feedback.sqlite3 --output data/local/backups/feedback-checkpoint.sqlite3
```

反馈库不存在时跳过该条命令，不创建空库来冒充备份成功。保存备份命令返回的 SHA-256、时间与摘要到维护记录；文件权限为 `0600`。摘要不输出正文、反馈描述或联系方式。档案备份不包含反馈库，两个文件是各自一致的 SQLite 检查点，并非跨库原子事务；如果需要同一停写时刻，先停止服务和导入进程。

使用 SQLite backup API，包含 WAL 中已提交状态。写入临时文件、完整校验后以原子、不覆盖的方式公布目标；失败清理临时文件；若目标已发布后的目录同步失败，命令仍报错并保留该目标，需要另行 verify，不能直接重试覆盖。备份 API 单次最长 60 秒；锁定或高写入压力下失败可在写入停止后重试。大库完整验证另外耗时，不受这 60 秒限制。没有修改日常库的 journal mode。

备份只在本机生成。上线前需要由维护者将备份与校验摘要另存到独立故障域，并演练读取权限和完整性；本轮没有配置云存储、自动备份或异地恢复。SHA-256 用于核对已保存的可信副本，不能证明恶意篡改者未同时改动文件与摘要。

## 发布回滚

先备份，然后核验当前活动版本；以下两个版本 ID 应替换为实际已导入值：

```bash
python3 scripts/maintain_archive.py activate --database data/local/archive.sqlite3 --snapshot fixture-2026-10-10-v1 --expect-active your-current-snapshot --reason '回滚到已核验批次'
```

该命令在事务内切换活动指针，保留全部快照、当前撤下与来源用途限制；错误版本、并发版本变化或失败写入不提交。`maintenance_events` 保存时间、原因、前后版本和限制摘要。相同版本返回 `unchanged`，不生成虚假变更。

浏览器已有链接仍固定旧快照，须点击“读取当前发布快照”才切换。AI 会话固定启动时快照；如果要改变会话快照，需要在相同允许范围下显式重启该会话。当前没有独立搜索索引，数据和图谱从同一快照投影；未来增加索引时必须同时处理版本切换。

## 恢复到新路径

1. 停止网站、导入器和其他写入者。核对需要保留的最新撤下 / 用途状态；保存原库，不删除或就地覆盖。
2. 指定可信内容备份、当时保存的 SHA-256，以及包含最新限制的可信档案库。原库若损坏，可用已独立核验的较新恢复副本；没有可信最新限制时，工具不会从损坏库静默降级，应保持服务停止，补齐限制记录后再上线。
3. 执行恢复，验证新库及反馈库，再以新路径启动服务。

```bash
python3 scripts/maintain_archive.py restore --backup data/local/backups/archive-checkpoint.sqlite3 --expected-sha256 SHA256_FROM_BACKUP --current-database data/local/archive.sqlite3 --output data/local/recovered/archive.sqlite3
python3 scripts/maintain_archive.py verify --database data/local/recovered/archive.sqlite3
python3 scripts/maintain_archive.py backup --kind feedback --database data/local/feedback.sqlite3 --output data/local/recovered/feedback.sqlite3
python3 scripts/serve_prototype.py --database data/local/recovered/archive.sqlite3 --port 4176
```

`SHA256_FROM_BACKUP` 须换成备份时返回的完整值。反馈使用最新可信库；若原反馈库损坏，应改用可信反馈备份作为该命令的来源，并明确备份之后可能丢失的提交。服务按档案库所在目录找 `feedback.sqlite3`，必须一并准备；不要误指向空的新收件箱。反馈恢复不会合并两份收件箱的新旧条目。

恢复合并双方更严格的来源用途和撤下 ID，保留旧内容快照引用；不复制当前库的新内容快照。旧备份缺少较新受限来源 / 撤下身份，或双方同一快照 ID 内容不同，都会拒绝并要求更新恢复点。原撤下批次可能不在旧备份：审计事件保留其原批次，数据库外键改指向恢复库中包含该身份的快照，不据此外推真实撤下时间。

限制状态只代表指定当前库读取事务的时刻，程序无法知道未提供的外部更新。恢复输出的 SHA-256 会因合并限制和审计记录而不同于原备份。先检查旧段落链接、搜索、关系证据和导出；只有结果正确才切换本机使用路径。不能以回滚旧备份作为解除限制的办法。

## 验证与尚未覆盖

```bash
python3 -m unittest discover -s scripts -p 'test_maintenance.py' -v
```

演练使用临时合成数据库，不替换日常库。覆盖 WAL、错误哈希、已有目标、部分写入失败、损坏主库、反馈校验、旧引用和限制保持。没有完成异地备份、加密存储、损坏限制账本修复、实际生产停机切换和四小时恢复目标验收，不能用小样本进程启动时间宣称达到生产 RTO。
