# 本地只读连接与素材包

## 在线入口

维护者在档案项目中启动：

```bash
python3 scripts/serve_prototype.py --port 4173 --ai-scope opening
```

AI 工具默认关闭；`--ai-scope` 开启并固定最大范围，可重复指定。`--ai-snapshot` 可固定一个已导入版本；省略时固定启动时的活动版本，后续导入不自动切换。当前接口仅供本机使用，无远程认证或公网承诺。助手不要自行放宽启动参数。

在 Skill 目录运行（若当前不在此目录，将脚本参数替换为实际安装路径）：

```bash
python3 scripts/archive_client.py --url http://127.0.0.1:4173 --tool get_corpus_status
python3 scripts/archive_client.py --url http://127.0.0.1:4173 --tool search_texts --arguments '{"q":"师父","scope_ids":["opening"],"limit":8}'
python3 scripts/archive_client.py --url http://127.0.0.1:4173 --tool get_passage --arguments '{"id":"passage:03","radius":1,"scope_ids":["opening"]}'
```

六个工具真实映射到 `POST /api/ai-tools` 的 `{name, arguments}`；不是 MCP 工具注册名称。当前可通过具备 Python 命令执行能力的助手调用。客户端只接受显式本机 HTTP 地址，不重定向、不读取代理配置，不存凭据或正文缓存。

所有参数支持可选 `snapshot`（必须与会话相同）和 `scope_ids`（默认会话最大范围，只能缩小）。用途固定 `external_ai`，不能传入 display / export 覆盖。返回快照、实际范围、合成声明、来源记录和 `connection=live_readonly`。

| 工具 | 特定参数 | 返回 / 限额 |
| --- | --- | --- |
| get_corpus_status | 无 | 当前允许数量、语言、来源和已知缺口、会话范围 |
| search_texts | q、mode=literal/keywords、category、speaker、limit=1–50、cursor | 当前页原文与出处、签名分页；默认 8 条 |
| get_passage | id；radius=0–2，默认 1 | 目标及按显式连接找到的邻接；最多 20 段，截断明确；不推测缺失连接 |
| get_story_context | entry_id；limit=1–50，默认 20；cursor | 当前允许条目段落、分支与页内连接、稳定续页；无推断时间线 |
| get_character_graph | center、hops=1/2、predicate、condition、page、cursor | 每页最多 50 人物 / 100 关系、完整证据、截断与续取 |
| get_relationship | id | 已审核明确关系、方向、条件及所有当前完整允许证据组 |

类型 / 情节枚举由收录样本定义：predicate 为 all / mentor_of / parent_of / opposes / cooperates_with；condition 为 all / opening / east / west / later。条件不会扩大 scope_ids。

只返回过滤后的内容与数量。上下文不保证完整任务，包外 / 页外 next_ids 不返回；继续检索或分页核对。关系详情不能绕过范围或用途。每次调用重新读取当前限制：撤下与用途收紧立即影响旧快照。

400 表示参数、边界或游标无效；404 表示当前不可用；409 表示资料改变导致旧分页失效，须重查；503 表示连接未启用或存储不可用。客户端返回非零退出码并明确错误；不要当成空结果或成功。

## 离线素材包

使用网站“AI 取材”用途核验并导出 JSON，随后在 Skill 目录运行：

```bash
python3 scripts/check_materials.py /path/to/materials.json --scope opening
```

检查格式、同一快照、明确范围、来源 storage/export/external_ai 声明、引用完整性、关系方向 / 审核 / 完整证据组和互斥分支。检查通过也不代表文件未被篡改或资料仍有效；报告离线状态，不能宣称重新联网核验。工具失败时不要先读正文再试着绕过限制。没有此 JSON 格式时按用户文本处理，不能伪造校验成功。

关键引用保留 passage.id、source_locator、snapshot_id、required_scope_ids、branch_id。关系须同时保留 ID、方向、条件及所用完整组。新增分析和对白应在正文说明其性质。
