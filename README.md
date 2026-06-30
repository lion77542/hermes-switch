# Hermes Switch ⚡

**一键切换 AI 模型，就像切换输入法一样简单。**

你装了很多 AI（DeepSeek、Kimi、本地模型…），但每次换模型都要改配置文件，烦不烦？
Hermes Switch 让你在浏览器里点一下，就切换 Hermes Agent 当前用的模型。

---

## 小白入门

### 这个工具解决了什么问题？

你用 Hermes Agent 聊天时，只能**同时用一个 AI 模型**（比如 DeepSeek v4）。想换别的（比如本地跑的小模型、或者 Kimi），以前要：

1. 打开配置文件
2. 找到模型设置那一段
3. 手动改 provider、api_key、base_url
4. 保存
5. 重启 Hermes

**Hermes Switch = 上面的步骤全部自动化**，点点鼠标就搞定。

### 三个核心概念

```
┌─────────────────────────────────────────────────┐
│  提供商 (Provider)                               │
│  ┌──────────┐  ┌──────────┐  ┌────────────────┐ │
│  │DeepSeek   │  │OpenAI    │  │你的本地模型     │ │
│  │官方接口    │  │官方接口   │  │(自定义)         │ │
│  └──────────┘  └──────────┘  └────────────────┘ │
│       │              │               │           │
│       ▼              ▼               ▼           │
│  ┌──────────┐  ┌──────────┐  ┌────────────────┐ │
│  │deepseek  │  │  openai  │  │ 我的本地代理    │ │
│  │v4 flash  │  │  gpt-4o  │  │  Qwen3-4B      │ │
│  │deepseek  │  │  gpt-4o  │  │  Qwen3-VL      │ │
│  │chat      │  │  mini    │  │  (视觉模型)     │ │
│  └──────────┘  └──────────┘  └────────────────┘ │
│          模型 (Model)                             │
└─────────────────────────────────────────────────┘
```

- **提供商** — 谁给你提供 AI 服务？DeepSeek、OpenAI、还是你自己电脑上跑的模型？
- **连接** — 一个提供商 + 它的地址 + 你的 Key。比如「商汤 tokenplan 端点」
- **模型** — 那个连接上具体用哪个 AI 模型。比如 `deepseek-v4-flash`

> 💡 **一句话：** 你添加「连接」，里面选「模型」，点一下「切换」就生效。

### 安装

```bash
pip install git+https://github.com/dlamd/hermes-switch.git
```

装好后运行：

```bash
hermes-switch
```

浏览器自动打开 → 看到 Web UI 界面。

---

## 使用指南

### 第一步：打开 Web UI

```bash
hermes-switch           # 启动，浏览器自动打开
hermes-switch web 8080  # 指定端口
```

界面长这样：
- 顶栏：当前用的模型名 + 切换开关
- 卡片列表：你所有可用的 AI 连接
- 每个卡片有：测试、切换、编辑、删除按钮

### 第二步：添加你的 AI 连接

点「+ 添加端点」：

1. **名称** — 随便起个名字，比如 `我的DeepSeek`
2. **提供商** — 选 `deepseek`（内置的直接选，不用填地址）
3. **模型** — 点「获取」自动拉取可用模型列表，选一个
4. **保存**

内置的提供商不用填 Base URL 和 Key（Key 从环境变量读取）。

如果是自定义的（本地模型、第三方代理）：
- **Base URL** — 填 API 地址，比如 `http://127.0.0.1:8080/v1`
- **API Key** — 填你的 Key

### 第三步：切换

在卡片上点「切换」→ 选模型 → 确认。

然后在 Hermes 里输入 `/reset`，就生效了。

### 第四步（可选）：撤销

切错了？Web UI 顶栏有「撤销切换」按钮，一键恢复。

---

## 高级：如果你用了多个 Hermes Profile

> ⚠️ **大多数人不需要看这节。** 只有当你用 `hermes -p xxx` 启动时才需要。

Hermes 支持多套独立配置（叫 profile）。如果你平时这样启动：

```bash
hermes -p work    # 工作用配置
hermes -p home    # 家里用配置
```

那切换时也要指定操作哪个 profile：

```bash
hermes-switch use deepseek -p work      # 切换 work 的模型
hermes-switch use deepseek -p home      # 切换 home 的模型
```

Web UI 顶栏有个下拉框，选哪个 profile 就切换哪个的模型。不选就操作默认配置。

> 🤔 **Profile 是什么？** 就是 Hermes 的「独立配置账号」——每个 profile 有自己的模型设置、技能、聊天记录。一般人只用默认的（不指定 -p 启动），就不用管这个。

---

## CLI 命令速查

| 命令 | 作用 |
|------|------|
| `hermes-switch` | 启动 Web UI |
| `hermes-switch list` | 列出所有已添加的连接 |
| `hermes-switch current` | 看当前在用什么模型 |
| `hermes-switch use <名称>` | 切换到指定连接 |
| `hermes-switch use <名称> <模型>` | 切换到指定连接的指定模型 |
| `hermes-switch undo` | 撤销上次切换 |
| `hermes-switch remove <名称>` | 删除一个连接 |
| `hermes-switch rescan` | 重新扫描可用的连接 |

> 💡 CLI 也支持 `-p` 参数指定 profile，用法同上。

---

## 技术细节

### 配置文件

所有连接存储在 `endpoints.json`（在 Hermes 配置目录下），Web UI 自动管理，不用手动编辑。

### 切换原理

hermes-switch 修改 Hermes 的 `config.yaml` 文件中的 `model` 段：

```yaml
# 切换前
model:
  provider: deepseek
  default: deepseek-v4-flash

# 切换后（点了一下）
model:
  provider: custom
  base_url: https://token.sensenova.cn/v1
  api_key: sk-xxx
  default: sensenova-6.7-flash-lite
```

改完后在 Hermes 输入 `/reset` 重新加载配置，就切换成功。

### 撤销原理

每次切换前会自动备份当前的配置。点撤销就恢复备份文件的内容。

---

## License

MIT