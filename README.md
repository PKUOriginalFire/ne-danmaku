# Nekocast - Danmaku Core

> 元火弹幕姬核心

<span style="text-decoration:line-through">⚠️这个项目完全使用 Claude Code / Codex 生成，未经任何人工修改</span>  
这个项目在上述的基础上，使用ChatGPT以及智人能工进行了修改

## 使用

你需要 [`uv`](https://docs.astral.sh/uv) + `node` + `pnpm` 来运行这个项目

### 构建前端部分：

```bash
cd frontend
pnpm install
pnpm build
```

### 搭建 Satori 弹幕源

由于 gugugaga bot 的日新月异，我们只尝试了 [LLBot](https://www.llonebot.com/guide/getting-started) 的 Satori 服务作为 gugugaga 弹幕源。

请配置后在 config.json 中填写 Satori 相关配置。

### 搭建 B 站弹幕源

请从 bilibili 直播间获取房号填写在 config.json 中。

SESS_DATA 为可选，如果需要查看具体观众昵称请从 cookie 获取后填写。

### 运行服务：

将 config.example.json 复制为 config.json 并修改配置后运行

```bash
uv run main.py
```

服务会在对应的端口启动 HTTP 服务

- `/danmaku/房间名` 为弹幕网页，管理、咕咕嘎嘎、B 站弹幕均会显示在此页面，可以直接添加到 OBS
- `/danmaku/chat/房间名?key=密钥` 为管理端发送弹幕的接口，在这里也能实时调整弹幕姬透明度