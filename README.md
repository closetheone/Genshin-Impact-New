# Genshin-Impact-New

一个用于查阅原神文本、探索有依据的人物关系，并让 AI 基于资料创作剧情脚本的项目。

## 核心体验

```text
检索原文 → 阅读上下文 → 核对出处
                         ↓
                   人物关系图 → 关系证据
                         ↓
                      素材包 → Skill 剧情创作
```

首发计划为简体中文响应式网站。AI 创作优先通过外部助手中的 Skill 完成，站内 AI 工作台属于后续范围。

## 当前状态

截至 2026-10-12，T08 已完成合成样本上的可移植 Skill、固定范围六个只读工具、在线客户端和离线素材校验；在线 / 离线各三种创作成稿已实际试用。48 个 Python 自动化测试通过，详情及试用偏差见 `docs/t08-validation.md`。真实来源准入和真实剧情验收仍未通过，不代表 M0、正式 M3 或公开 V1 完成。

所有样本故事都明确标为原创测试内容，不是原神剧情。仅审核通过且证据完整的关系进入页面，原始样本全部范围下为 6 条。真实正文与使用范围仍待确认；本机 AI 工具已可用，尚无真实采集器或生产部署。

## 打开网站原型

使用 Python 3.10 或以上版本，在项目根目录运行，无需安装第三方依赖：

```bash
python3 scripts/serve_prototype.py
```

浏览器打开 `http://127.0.0.1:4173`。端口占用时可加 `--port 4174`；Ctrl+C 停止服务。仅监听本机回环地址，不要作为公网服务部署，也不能双击 HTML 代替启动服务。

第一次默认启动会把原创样本导入 `data/local/archive.sqlite3`；之后读取数据库，不重新灌入 JSON。数据库只保存在本机，不提交到仓库。已有空库、损坏库或不兼容版本会明确报错，不覆盖修复。

- 搜索：服务端原句包含 / 同段关键词 AND、分类 / 说话人筛选、8 / 16 / 32 条分页、重复对白分别定位，以及统一范围 / 用途切换。
- 阅读：上下文、分支、稳定段落 ID、出处、可见后续连接，以及重新核验后的引用复制。
- 素材：搜索 / 阅读 / 关系证据加入同一快照清单、主题备注、去重移除、50 个独立片段上限，以及重新核验后的 Markdown / JSON / 复制导出。只在本浏览器保存 ID 和主题，清理浏览器数据会丢失。
- 收录纠错：收录说明、已知缺口与六类问题反馈，写入本机私有收件箱并返回编号。
- 图谱：服务端人物查找、一跳 / 二跳、类型 / 情节筛选、50 人物 / 100 关系的有界分页、方向与完整证据、图 / 列表、拖拽缩放、分享恢复及重新核验后的 JSON / PNG 导出。

默认只看开篇；手动选择全部样本才展开后续。切换“素材导出”或“AI 取材”会排除仅可展示的内容。AI 取材在此仅演示数据筛选，不会向外部模型发送材料，也不会生成剧情脚本。

关键词用空格分隔，原句模式按连续文本包含匹配。当前只有原创任务分类，不支持自动中文分词或语义检索。分页固定查询、快照和边界；撤下导致结果变化时旧分页返回失效提示，需从第一页重查。服务重启也会使旧游标失效。

分享固定快照、中心、筛选、页码与布局，继续使用接收者当前范围，新页面默认开篇。分享地址仍指向本机服务。JSON 和 PNG 导出都会重新核验当前用途与导出用途；失效或受限内容会阻止下载，需刷新或切换用途。PNG 在图谱模式下可用。详见 [图谱方案](docs/graph-pipeline.md)。

## 导入与快照

```bash
python3 scripts/import_sample.py
python3 scripts/import_sample.py /path/to/synthetic-v2.json --activate
```

重复导入原文件返回 `unchanged`。新内容必须使用新快照 ID；除首次导入外，只有 `--activate` 才切换活动快照。网页 URL 自动固定实际读取的版本，点击顶部“读取当前发布快照”才切到新发布内容。

撤下与来源用途收紧在成功导入后对旧快照也生效，不能通过切旧版本绕过；目前没有限制解除操作，测试请使用独立数据库。导入参数、存储结构和操作边界见 `docs/storage-pipeline.md`。

## 运行样本验证

使用 Python 3.10 或以上版本，无需安装第三方依赖：

```bash
python3 scripts/validate_sample.py
python3 -m unittest discover -s scripts -p 'test_*.py' -v
python3 scripts/validate_sample.py --query '先核对物资' --scope all
python3 scripts/validate_sample.py --view --scope opening
python3 scripts/validate_sample.py --view --scope all --purpose external_ai
```

第一条命令检查数据契约，第二条运行图谱、素材、反馈和 AI 工具自动化回归；后续命令演示保留不同出处的查询，以及按范围、用途和证据完整性裁剪图数据。这些测试使用合成数据，不会触发模型调用。

仓库提供 [可移植 Skill](skills/genshin-story-writer/SKILL.md)，About 页面可下载 ZIP。安装、连接和使用示例见 [AI 连接方案](docs/ai-pipeline.md)。本轮没有覆盖本机已有的个人 Skill。

## 查看本地纠错反馈

```bash
python3 scripts/manage_feedback.py
python3 scripts/manage_feedback.py --include-contact
python3 scripts/manage_feedback.py --resolve <反馈编号>
```

收件箱为档案数据库同目录的 `feedback.sqlite3`，默认在 Git 忽略的 `data/local/`，没有公开读取接口。默认隐藏联系信息，显式选项才显示。每十分钟最多五条新反馈，失败保留表单；没有承诺处理时限或外部通知。自定义档案库时通过 `--inbox` 指定其同目录收件箱。详见 [素材与维护方案](docs/material-pipeline.md)。

## 文档导航

| 文档 | 职责 |
| --- | --- |
| [PRD](PRD.md) | 产品范围、十一项核心功能、数据约束与公开 V1 验收 |
| [下一步执行清单](NEXT_STEPS.md) | 当前状态、T01 至 T09 顺序、最近工作包和完成条件 |
| [资料来源与接入台账](DATA_SOURCES.md) | BWIKI、观测枢、空荧酒馆的入口、核对记录、具体使用范围与样本状态 |
| [数据契约](docs/data-contract.md) | 已实现的 v0.1 样本字段、证据组、方向、范围与用途规则 |
| [首次验证报告](docs/sample-validation.md) | 五页技术观察、24 项检查、实际结果与未通过的真实数据门槛 |
| [原型技术方案](docs/technical-prototype.md) | 已实现的技术选择、页面、原型接口、边界和 T04 迁移方案 |
| [原型验证记录](docs/prototype-validation.md) | 73 项原型检查、浏览器覆盖、复核步骤及未验收项 |
| [存储与导入链路](docs/storage-pipeline.md) | SQLite、事务导入、不可变快照、当前限制和固定引用 |
| [存储验证记录](docs/storage-validation.md) | T04 的 94 项检查、重启与回滚结果、复核步骤和未验收项 |
| [服务端搜索方案](docs/search-pipeline.md) | 匹配方式、分页接口、筛选计数、签名游标和统一内容边界 |
| [搜索验证记录](docs/search-validation.md) | T05 的 151 项检查、撤下与分页一致性、移动端及未验收项 |
| [局部图、分享与导出](docs/graph-pipeline.md) | 图查询、详情、限额、续取、分享边界和导出检查 |
| [图谱验证记录](docs/graph-validation.md) | 19 个自动化测试、54 项浏览器断言、实际撤下与导出验证 |
| [素材与维护流程](docs/material-pipeline.md) | 本地选择、固定证据组、素材核验、导出与私有收件箱 |
| [素材验证记录](docs/material-validation.md) | 34 个回归测试、62 项浏览器断言、跨版本 / 撤下与反馈演练 |
| [AI 连接与分发](docs/ai-pipeline.md) | Skill 安装、六个工具、固定边界与错误处理 |
| [T08 验证记录](docs/t08-validation.md) | 自动化检查、在线 / 离线创作试用及局限 |
| [AI 剧情创作方案](AI_STORY_PLAN.md) | Skill 的取材、查证、创作及人物关系图联动流程 |
| [项目协作约定](AGENTS.md) | 检查、提交、推送与失败处理规则 |

## 下一步

下一步进入 **T09 首批扩充与发布验收准备**：补核真实来源批次、准备获准正文导入，并验证性能、备份恢复和正式 AI 环境。真实来源未获准前继续保持合成样本，不宣称公开 V1 已通过。

已指定资料来源不等于已获得所有使用许可；仅对实际可用且获准用于相应用途的内容进行处理。不能用自制原型数据代替真实资料的准入或准确性验收。

## 协作

每轮相关修改检查通过后提交并推送到当前上游；不强制推送、不提交私密材料。任务执行时同步更新实际完成状态，不将规划文件或示例接口写成已实现功能。
