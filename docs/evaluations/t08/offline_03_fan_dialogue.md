# 离线｜约200字同人对白：先把话说清

> **原创合成演练，非原神剧情。**仅使用 `opening`，固定快照 `fixture-2026-10-10-v1`。

离线模式：使用指定 JSON 素材包，显式 `--scope opening` 校验通过；只验证结构和声明用途，未联网核验文件真实性或最新撤下状态。

## 正文

【原创场景：桥边。阿砚在木板上比画，阿宁蹲在另一端。】

阿宁：你点头了，我还不知道你要我先做什么。
阿砚：我以为你看懂我的手势了。
阿宁：我又没跟着你的师父学三年。
阿砚（笑）：是我没说清。你先扶住这一端，我核对位置；发现不对，就喊停。
阿宁：如果是你弄错了呢？
阿砚：照样喊。共同负责，又不是共同装作没看见。
阿宁：这句话说得明白。
阿砚：那我再说一遍步骤？
阿宁：说吧，这次我也把自己的想法告诉你。

【阿砚放下工具，两人重新商量。】

## 创作说明

同人创作：保留木匠青禾为阿砚师父、学习三年、阿砚与阿宁合作负责桥面的边界。场景、动作、性格表现及所有对白均为原创，不是离线包记载。

## 证据与边界

以下段落共同元数据：`snapshot_id=fixture-2026-10-10-v1`；`required_scope_ids=[opening]`；`branch_id=null`；`source_id=source:fixture`。出处是资料返回的定位符，未直接读取该源文件。

| 事实 | passage.id | source_locator | 原文 |
| --- | --- | --- | --- |
| 木匠青禾是阿砚师父 | passage:03 | data/samples/story.json#/passages/2 | 阿砚是我的徒弟。 |
| 阿砚跟随木匠青禾学木工三年 | passage:04 | data/samples/story.json#/passages/3 | 我跟随木匠青禾学习木工，已经三年。 |
| 阿宁邀请阿砚一起修桥 | passage:06 | data/samples/story.json#/passages/5 | 阿砚，我们一起修桥。 |
| 阿砚答应两人共同负责桥面 | passage:07 | data/samples/story.json#/passages/6 | 好，阿宁，我们共同负责桥面。 |

师徒关系：`relation:mentor`，`mentor_of`，`directed`，`person:carpenter → person:student`，完整使用证据组 `[passage:03, passage:04]`。`review_status=approved`，`claim_kind=explicit`，`branch_id=null`，所需范围 `[opening]`，快照同上；未另给关系 condition 字段，不虚构其值。

离线包没有合作关系记录。本稿仅以 `[passage:06, passage:07]` 的明确对白说明本次合作，不冒称存在已核验的合作关系 ID。包内全部相关段落 `branch_id=null`，没有后续、路线选择或修桥完成的证据，不从在线结果补入离线稿。
