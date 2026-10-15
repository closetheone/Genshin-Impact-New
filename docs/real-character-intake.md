# 真实角色基础资料目录

v1 保留安柏、凯亚、丽莎、琴四名角色；v2 收录同一固定版本中文 characters 目录中的全部 124 条记录。社区来源覆盖不等于官方当前已实装名单，本项目没有据此推定角色上线状态。它只包含姓名、元素、武器类型、稀有度、地区、所属组织、生日、命之座等简短基础字段；不包含游戏简介、对白、故事原文、图像、配音或人物关系推断。

## 来源与范围

- 来源：theBowja 与贡献者维护的 [genshin-db](https://github.com/theBowja/genshin-db)。这是社区整理资料，不是官方接口。
- 固定提交：`49a6544a6c6ae36089cb42fa591fc46f01de8bcf`；核对日期：2026-10-15。
- 每个角色保存固定提交的中文 JSON 链接、原始响应 SHA-256，以及所选字段到上游字段的映射。只保留挑选的基础字段，不保存完整上游角色正文。
- 仓库 `LICENSE` 为 MIT，`readme.md` 的 Licensing / Contributing 也明确允许使用其数据；原许可及署名保留在 `data/licenses/genshin-db-MIT.txt`。这不是对游戏剧情、美术等第三方素材的全面授权声明。
- 此次采用公开许可依据与有限基础字段核对，不要求虚构邮件授权或填写不存在的授权人。原有 BWIKI、观测枢、空荧酒馆正文来源台账仍待确认，没有将它们改成获准。

## 存储与页面

```bash
python3 scripts/character_catalog.py
python3 scripts/serve_prototype.py --port 4175
```

启动服务会幂等导入 `data/characters/genshin-basics-v1.json` 与 `data/characters/genshin-basics-v2.json`，默认打开 v2；旧链接仍固定 v1。两个批次分别写入同目录的 `character-catalog.sqlite3`（默认在 `data/local`）。相同批次 ID 不允许改写内容；后续更新必须新增批次 ID。网页运行时只读取本地 SQLite，不请求上游网站。

- 首页与“真实角色”导航打开 `#/real-characters`，成功读取后固定 `catalog` 参数。
- 详情使用 `#/real-character?catalog=...&id=genshin:...`，目录、返回链接与刷新保留同一批次。
- `/api/character-catalog` 支持 `catalog` 与可选 `character`，错误版本或角色返回 404，不回退到合成样本。不接收剧情范围或导出用途参数。
- 名称、武器检索和元素 / 地区筛选仅作用于当前批次，每页最多 24 条。查询、筛选和页码写入 URL，详情与返回目录保留这些条件。立绘用明确标注的文字占位，故事与真实关系显示未收录。
- 原有剧情 SQLite、合成导入器、素材清单和 AI 只读接口保持原有内容边界；真实基础资料不会伪装为 `synthetic` 注入这些接口。

校验器只接受已核对来源和固定字段集合，拒绝附加故事、图片或关系字段。校验只能确保结构和定位约束，SHA-256 是抓取时的核对记录，不证明上游本身无误。扩大来源或内容类型需要重新核对。

## 全目录构建与特殊字段

`build_character_catalog.py` 从本地 Git 对象读取固定提交的完整中文角色目录，不依赖可能被截断的 GitHub 递归树 API。仅请求清单中的 JSON，并验证每个响应的 Git blob SHA-1 与目录中的对象一致，随后只提取白名单基础字段。未存储剧情正文或图片。任一文件失败即不生成批次，不静默跳过。

```bash
git clone --filter=blob:none --no-checkout --depth=1 https://github.com/theBowja/genshin-db.git /tmp/genshin-db-source
# 若上游主分支已更新，先获取以下固定提交；不把新主分支内容当作旧版本。
git -C /tmp/genshin-db-source fetch --depth=1 origin 49a6544a6c6ae36089cb42fa591fc46f01de8bcf
python3 scripts/build_character_catalog.py \
  --repository /tmp/genshin-db-source \
  --revision 49a6544a6c6ae36089cb42fa591fc46f01de8bcf \
  --catalog-id genshin-basics-2026-10-15-v2 \
  --checked-on 2026-10-15 --output /tmp/genshin-basics-v2.json
```

v2 为 `character-catalog-2`：保存覆盖记录数、完整文件清单摘要及每条记录的 Git blob 标识。124 条记录 ID 均不重复，13 条地区为空或缺失；地区、组织、生日、命之座的缺项允许为 null，页面显示“来源未提供”。四条来源元素为“无”的记录保留原值，页面标为“无固定元素（来源标注）”，不人为拆成多个元素版本。v1 仍按原来的严格契约验证，没有改写旧批次。

验证：`PYTHONPATH=scripts python3 -m unittest scripts/test_character_catalog.py` 与 `node --test scripts/test_character_catalog_ui.mjs`。
