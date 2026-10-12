# 文本与人物关系样本契约 v0.1

本契约源于 T02 结构验证，已被 T03 页面与 T04 本地存储复用，不是生产数据库或公开 API。对应输入为 `data/samples/story.json`，校验与裁剪工具为 `scripts/validate_sample.py`，仅使用 Python 标准库。T04 存储包装和跨快照策略见 `storage-pipeline.md`，不改变输入 v0.1 格式。

当前实现明确只接受 `dataset_kind: synthetic`。它不会证明真实剧情正确、核实第三方授权或提供生产环境访问控制。真实来源的观察记录单独保存在 `data/source-audit.json`，不得当作剧情语料输入。

## 1. 数据集与标识

| 字段 | v0.1 规则 |
| --- | --- |
| `schema_version` | 固定为字符串 `0.1` |
| `dataset_kind` | 固定为 `synthetic`，避免将真实数据误标成已验证样本 |
| `notice` | 非空，明确声明全部剧情及用途开关均为测试数据 |
| `snapshot_id` | 非空字符串；每条记录必须使用相同快照 |
| `language` | 当前为 `zh-CN` |
| `scope_ids` | 可请求的范围标识，不重复；本样本为 opening、east、west、later |
| `branch_ids` | 互斥分支标识，同时必须属于范围标识集合 |
| `withdrawn_ids` | 已知记录的撤下标识；不因采用旧快照而忽略 |

记录标识全局唯一，不使用名称或原文内容代替标识。两个名字相同的人物仍有不同标识；一句话出现在两个位置时保留两条出现位置记录。

数组中的顺序不代表剧情时间线。样本特意让 `passage:31` 出现在 `passage:24` 之前的情节路径中，阅读顺序以 `next_ids` 为准。

## 2. 记录类型

每条记录都包含 `id` 和 `snapshot_id`。

| 集合 | 核心字段 | 约束 |
| --- | --- | --- |
| `sources` | content_type、locator、rights | 来源类型必须为 synthetic，保存用途必须明确 allowed |
| `entries` | title、category、source_id、required_scope_ids | 当前仅验证 quest，归属来源必须存在 |
| `characters` | name、source_id、required_scope_ids | 名称可以相同，不据此自动合并 |
| `passages` | entry_id、text、speaker_id、source_id、source_locator、required_scope_ids、branch_id、next_ids | 说话人和分支未知时显式为 null；引用必须存在 |
| `relationships` | from_id、to_id、predicate、direction、description、source_id、required_scope_ids、branch_id、review_status、claim_kind、evidence_groups | 双方人物存在，关系类型与方向一致，完整证据可追溯 |

样本出处定位采用来源 `locator` 加 JSON Pointer，例如 `data/samples/story.json#/passages/10`。校验器检查它确实指向当前出现位置，而不只检查字段非空。它是原创样本的文件定位，不是伪造的游戏原文链接。

真实来源还需要作者、修订、分项使用范围及许可依据等字段；这些需求记录在来源台账，不能因本样本通过就跳过后续真实数据契约扩展。

## 3. 范围、分支与用途

- `required_scope_ids` 采用全部满足语义，例如 `['opening', 'east']` 需要同时允许 opening 和 east。
- 选择 all 仅表示测试数据中的全部范围，不代表某个玩家已体验所有剧情。
- east 和 west 是互斥情节。记录中的 `branch_id` 非空时，必须将相应分支加入该记录所需范围。
- 同一条关系的证据组不能混用互斥分支；公共上下文可以与所属分支共同作为证据。
- 同时查看两个分支时仍保留每条关系的条件，不能解释为同一时间线上共同发生。

样本来源的 `rights` 包含 storage、display、export 和 external_ai，每项为 allowed、denied 或 unknown。只有明确 allowed 才能用于相应投影；unknown 不自动放行。这些值是原创样例的模拟策略，不是对真实网站许可的判断。

本工具的用途裁剪只演示 display、export 和 external_ai。真实数据的采集许可、AI 检索处理许可和第三方授权核实仍由来源准入流程处理。

## 4. 人物关系与证据组

| 关系类型 | 方向 | 读法 |
| --- | --- | --- |
| mentor_of | directed | from 是 to 的师父 |
| parent_of | directed | from 是 to 的家长 |
| opposes | directed | from 对抗 to，不自动推断反向关系 |
| cooperates_with | symmetric | 双方合作，反向重复不新增一条事实 |

同一人物对可以在不同分支或阶段有不同类型的关系；相同人物对、类型、分支和范围的重复关系断言会被拒绝。对称关系的两端顺序不影响去重。

`review_status` 为 approved、pending 或 rejected；`claim_kind` 为 explicit、inference 或 disputed。公开投影仅采用 approved 且 explicit 的关系。

`evidence_groups` 是“组间任选其一、组内全部满足”的列表。例如 `[['passage:03', 'passage:04'], ['passage:31']]` 表示前三段中的前两段共同支持结论，或第三段单独支持结论。

一条关系可见，必须同时满足：

1. 关系记录及来源未撤下，使用范围允许，情节范围满足。
2. 双方人物可见。
3. 审核状态与断言性质满足公开条件。
4. 至少一个证据组的所有段落都可用于当前范围和用途。

返回值仅保留完整可用的证据组；不存在完整证据组时不返回关系。待审共现推断、部分证据和被限制用途的材料不能产生公开事实连线。

## 5. 投影与查询

`project()` 按范围、用途和撤下状态返回条目、人物、段落和关系。段落的 `next_ids` 同样裁剪，不向调用者返回被过滤段落的标识。它输出供后续 UI 使用的图数据，不负责图形布局、两跳查询、分页或五十节点限额。

T05 的 `search_archive.py` 在此投影之上实现服务端查询与签名分页，不修改输入契约。网页搜索采用独立的 `/api/search` 响应，不再把完整投影当作搜索结果；规则见 `search-pipeline.md`。CLI 与 HTTP 的空查询行为分别记录，不混为一个接口。

命令行查询只是裁剪后样本的规范化连续字符串匹配：统一空白，保留原文，不执行中文分词或语义检索。空查询返回错误，未命中返回空列表。

```bash
python3 scripts/validate_sample.py
python3 scripts/validate_sample.py --query '先核对物资' --scope all
python3 scripts/validate_sample.py --view --scope opening
python3 scripts/validate_sample.py --view --scope all --purpose external_ai
```

普通校验返回 valid、数据性质、快照和记录数量；查询或投影要求显式传入范围。命令成功退出码为 0，读取、结构或请求错误退出码为 1，并在标准错误输出 JSON 错误。

## 6. 已知边界

- 校验器检查结构与演示策略，不自动判断对白是否真的支持某段关系说明，也不评审真实人物身份。
- 只使用自制任务样本；T04 已支持多快照持久化和本地读取，但没有正式数据库升级、真实来源适配或生产服务。
- 未做完整 JSON Schema 实现、任意字段级防泄露、剧情图环路分析或生产级鉴权；不得直接部署为公开接口。
- 数据文件公开包含完整原创故事，CLI 的范围裁剪是规则试验，不是对该本地文件的访问控制。
- 已有原文复制、局部图与固定快照链接；素材界面、完整发布恢复、限制解除与 Skill 连接仍待实现。
