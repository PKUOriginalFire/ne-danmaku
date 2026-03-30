# Nekocast - Danmaku Core

> 元火弹幕姬核心

<span style="text-decoration:line-through">⚠️这个项目完全使用 Claude Code / Codex 生成，未经任何人工修改</span>  

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

### 搭建 OneBot v11（aiocqhttp 反向 WS）弹幕源

`onebot_v11` 配置用于在本服务内启动一个反向 WebSocket 事件入口。

请在 OneBot v11 实现（如 LLOneBot / NapCat）中将反向 WS 地址指向：

- `ws://<本服务IP>:<onebot_v11.port>/ws`

并在 `group_map` 中将 QQ 群号映射到弹幕房间名。

若 OneBot 侧配置了访问令牌或签名密钥，请同步填写 `access_token` / `secret`。

### SC 与礼物动态配置

弹幕子模块支持通过 `config.json` 动态配置文本指令里的 SC 与礼物行为。

- `/sc` 文本指令格式：`/sc [cost] 文本`
- 若省略 `cost`，使用 `danmaku.superchat.default_cost`
- SC 展示时长由金额自动计算，不再与金额脱钩：
	`duration = clamp(cost * duration_per_cost, min_duration, max_duration)`

配置示例（节选）：

```json
{
	"danmaku": {
		"superchat": {
			"default_cost": 10,
			"duration_per_cost": 1,
			"min_duration": 10,
			"max_duration": 300
		},
		"gift": {
			"default_cost": 1,
			"items": {
				"good": {
					"cost": 1,
					"aliases": ["这个好诶"],
					"image_url": "/assets/gifts/good.png"
				},
				"tower": {
					"cost": 5,
					"aliases": ["博雅塔"],
					"image_url": "/assets/gifts/tower.png"
				}
			}
		}
	}
}
```

- `/gift` 文本指令格式：`/gift 礼物名 [数量]`
- 礼物单价优先使用 `gift.items` 中命中的键名或别名；未命中时使用 `gift.default_cost`
- 礼物总价计算：`cost = 单价 * quantity`
- 礼物图片可通过 `gift.items.<key>.image_url` 配置，支持绝对 URL 或站内路径（如 `/assets/gifts/good.png`）

### 发言奖励与现金系统

对于 OneBot v11 和 Satori 弹幕源，系统内置了一套虚拟货币（火）机制，用于控制文本指令 `/sc`、`/gift` 的消费校验。

**奖励策略（可叠加）：**

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `true` | 是否启用现金系统；禁用时允许无限发送礼物/SC |
| `initial_amount` | float | `10.0` | 用户首次发言时获得的初始火量 |
| `reward_per_message` | float | `0.0` | 每条有效消息奖励的火量 |
| `reward_interval_seconds` | int | `0` | 间隔奖励周期（秒），0 表示禁用 |
| `reward_per_interval` | float | `0.0` | 每个周期额外奖励的火量 |

**配置示例（节选）：**

```json
{
  "danmaku": {
    "cash": {
      "enabled": true,
      "initial_amount": 10.0,
      "reward_per_message": 0.5,
      "reward_interval_seconds": 60,
      "reward_per_interval": 1.0
    }
  }
}
```

用户首次发言获得 10 火，之后每条消息额外获得 0.5 火；同时每隔 60 秒再额外获得 1 火。

**消费校验：** 发送 `/sc` 或 `/gift` 时会先检查余额是否足够，不足则该指令被拒绝（不会发送到弹幕流）。

### 运行服务：

将 config.example.json 复制为 config.json 并修改配置后运行

```bash
uv run main.py
```

服务会在对应的端口启动 HTTP 服务

- `/danmaku/房间名` 为弹幕网页，管理、咕咕嘎嘎、B 站弹幕均会显示在此页面，可以直接添加到 OBS
- `/danmaku/chat/房间名?key=密钥` 为管理端发送弹幕和动态配置房间设置（透明度、emoji、superchat、gift、置顶/置底定位开关）的界面
