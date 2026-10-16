# Next.js 前端迁移壳

这是现有原生前端的并行迁移入口，暂不替换 `web/` 原型。

## 启动

推荐在项目根目录使用统一启动脚本，它会先启动 Python API，确认 API 可用后再启动 Next.js：

```bash
./scripts/dev_next.sh
```

默认地址为 `http://127.0.0.1:3000`，可用 `API_PORT=4176 NEXT_PORT=3001 ./scripts/dev_next.sh` 覆盖端口。按 Ctrl+C 会同时停止两个开发服务。

也可以分开启动：

先在项目根目录启动 Python API：

```bash
python3 scripts/serve_prototype.py --port 4175
```

再在本目录安装依赖并启动 Next.js：

```bash
npm install
npm run dev
```

浏览器打开 `http://localhost:3000/characters`。

当前迁移壳包含：

- `/characters`：角色目录、搜索、元素与地区筛选、分页、URL 状态保留。
- `/characters/[id]`：角色基础资料、官网立绘、官网入口和来源核对记录。
- `/real-characters` 与 `/real-character/[id]`：兼容原型中的真实角色入口。
- `/search`：原创样本文本检索，支持原句/关键词、范围、分类、说话人和游标分页。
- `/read`：从命中位置回到完整原文上下文，并显示出处与显式后续连接。
- `/graph`：原创样本人物关系列表、中心人物/层级/类型/分支筛选和证据核验面板。
- `/materials`：浏览器本地素材清单、服务端重新核验和 Markdown/JSON 导出。
- `/about`：收录边界、来源准入状态和本机纠错反馈。

页面继续通过 Next.js rewrite 访问现有 Python API，不复制数据库，也不把官网简介当作完整角色故事。官网图片仅使用已核对的远程引用；图片加载失败时会回退到文字占位。

职责边界：Next.js 负责页面、路由、导航和轻量代理接口；Python 负责数据校验、来源准入、SQLite 初始化、搜索 / 阅读 / 图谱查询、素材复核和批量维护。真实数据接入前，Python 的来源门禁仍是唯一准入依据。

检查命令：

```bash
npm run lint
npx tsc --noEmit
npm run build
```
