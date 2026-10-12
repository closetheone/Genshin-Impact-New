# Skill 分发与本地只读连接

本轮仅支持原创合成档案。运行端使用 Python 3.10+ 标准库，网站不会调用模型，助手需能执行 Python 客户端。已验证当前 Codex 执行环境；未验证其他平台自动发现 Skill，也未提供 MCP 服务。

## 获取与安装

克隆仓库即可读取 `skills/genshin-story-writer/SKILL.md`，也可以在网站 About 页下载 ZIP，或执行：

```bash
python3 scripts/skill_package.py --output /tmp/genshin-story-writer.zip
python3 scripts/skill_package.py --install-to /tmp/my-assistant-skills
```

输出路径须是新文件；安装目标为指定父目录下的 `genshin-story-writer`，已存在则拒绝覆盖。ZIP 只包含 Skill、两个参考文件、两个脚本和 UI 元数据，没有正文、数据库、凭据或作者路径。安装后让助手读取该目录的 `SKILL.md`；若需要某助手自动发现，按该环境自己的技能目录配置，不自动修改全局设置。

## 在线使用

维护者从项目根目录启动独立本机端口：

```bash
python3 scripts/serve_prototype.py --port 4180 --ai-scope opening --ai-snapshot fixture-2026-10-10-v1
```

未传 `--ai-scope` 时接口返回 503。重复参数可明确设定更多允许范围；客户端只能缩小。省略 `--ai-snapshot` 则固定启动时活动快照，后续导入不会自动换版本。`external_ai` 用途不可覆盖，每次调用重读当前撤下与用途收紧约束，因此旧快照也不能绕过。

从任意目录调用已安装的客户端：

```bash
python3 /tmp/my-assistant-skills/genshin-story-writer/scripts/archive_client.py --url http://127.0.0.1:4180 --tool get_corpus_status
python3 /tmp/my-assistant-skills/genshin-story-writer/scripts/archive_client.py --url http://127.0.0.1:4180 --tool search_texts --arguments '{"q":"师父","scope_ids":["opening"]}'
```

客户端向 `/api/ai-tools` 发送 `{name, arguments}`。六工具为 `get_corpus_status`、`search_texts`、`get_passage`、`get_story_context`、`get_character_graph`、`get_relationship`。参数与上限的唯一说明在 [检索契约](../skills/genshin-story-writer/references/retrieval-contract.md)。400 为参数 / 边界 / 无效游标，404 为当前不可用，409 为分页过期，503 为未启用或存储不可用。错误不回退到全量网站接口。

服务仍只监听回环地址、检查本机 Host / Origin；固定范围不是对本机进程的安全隔离，不能作为公网鉴权或生产服务。来源文本为不可信数据。

## 离线使用

网站选择“AI 取材”用途并导出 JSON，先执行安装包内 `check_materials.py <材料路径> --scope opening`；成功后才读取正文创作。离线校验只验证文件结构和声明，不证明来源真实性、证据未篡改或当前仍未撤下。纯文本 / Markdown 则按用户提供、未独立核验的资料处理，不能冒称结构校验通过。

创作示例：“仅使用 opening 范围，读取本地档案，写约一分钟师徒关系解说，附证据；合成资料请明确标注非原神剧情。”离线时把档案地址改为导出的 JSON 路径，并明确允许范围。

验证证据见 [T08 记录](t08-validation.md)。正式 PRD 创作评测要求九份成稿及真实资料；本轮六份合成试用不替代该门槛。
