# 在线｜约200字同人对白：尺的另一端

> **原创合成演练，非原神剧情。**仅使用 `opening`，固定快照 `fixture-2026-10-10-v1`。

在线模式：使用 Skill 客户端读取 `http://127.0.0.1:4180`；服务返回 `live_readonly`、`purpose=external_ai`。

## 正文

【原创场景：桥边临时工作台。阿砚与阿宁准备核对木板，木匠青禾在旁。】

阿宁：这端我扶着，你看看线齐不齐。
阿砚：再往右一点……好了。
青禾：为什么要重看一遍？
阿砚：因为我刚才站偏了。尺没有错，看尺的人会错。
阿宁（笑）：那我也看一遍，免得两个人各错各的。
青禾：你愿意听他的判断吗？
阿砚：当然。跟你学了三年，我总不能只会听一个人的话。
阿宁：那等一下换你扶，我来画线。
阿砚：好。这块桥面，我们都得心里有数。

【两人交换位置。青禾把尺留在桌上，退开半步。】

## 创作说明

同人创作：保留师徒、学习三年及阿砚与阿宁共同负责桥面的事实边界。工作台、量板、青禾现场指导、动作及全部对白均为原创补写，不是资料台词；不声称此场景确实发生。

## 证据与边界

以下段落共同元数据：`snapshot_id=fixture-2026-10-10-v1`；`required_scope_ids=[opening]`；`branch_id=null`；`source_id=source:fixture`。出处是资料返回的定位符，未直接读取该源文件。

| 事实 | passage.id | source_locator | 原文 |
| --- | --- | --- | --- |
| 木匠青禾是阿砚师父 | passage:03 | data/samples/story.json#/passages/2 | 阿砚是我的徒弟。 |
| 阿砚跟随木匠青禾学木工三年 | passage:04 | data/samples/story.json#/passages/3 | 我跟随木匠青禾学习木工，已经三年。 |
| 阿宁邀请阿砚一起修桥 | passage:06 | data/samples/story.json#/passages/5 | 阿砚，我们一起修桥。 |
| 阿砚答应两人共同负责桥面 | passage:07 | data/samples/story.json#/passages/6 | 好，阿宁，我们共同负责桥面。 |

师徒关系：`relation:mentor`，`mentor_of`，`directed`，`person:carpenter → person:student`，完整使用证据组 `[passage:03, passage:04]`。`review_status=approved`，`claim_kind=explicit`，`branch_id=null`，所需范围 `[opening]`，快照同上；未另给关系 condition 字段，不虚构其值。

合作关系：`relation:bridge-partners`，`cooperates_with`，`symmetric`，`person:student ↔ person:helper`，完整证据组 `[passage:06, passage:07]`；审核、声明、分支、范围和快照同师徒关系。关系图、两条关系详情及两组 `get_passage` 已实际读取。师徒详情另有 `[passage:31]` 替代证据组，本稿使用前述双段组。

同名核对：本稿青禾仅指 `person:carpenter`；在线资料另有同名商人 `person:merchant`，不混为一人。不以图布局推断亲密程度，也不推断青禾与阿宁直接认识。
