# Hermes Switch ⚡

**多端点快速切换器 for [Hermes Agent](https://github.com/NousResearch/hermes-agent)**

管理多个 API endpoint + 模型，一键切换。Web UI + CLI 双模式。

## 功能

- 🌐 **Web UI** — 浏览器管理所有端点，内置 Provider（DeepSeek/OpenAI/等）和自定义端点分组显示
- ⚡ **一键切换** — 选端点 → 选模型 → 切换，带撤销功能
- 🔍 **连通性测试** — 测试端点是否可用，自动缓存模型列表
- 📋 **CLI 命令** — `list|use|current` 分组显示
- 💾 **零依赖** — 只用 Python 标准库 + PyYAML
- 📱 **响应式 UI** — 自适应手机/平板/桌面，`rem` + `clamp()` 流体排版

## 安装

```bash
pip install git+https://github.com/dlamd/hermes-switch.git
# 或
git clone https://github.com/dlamd/hermes-switch.git
cd hermes-switch
pip install -e .
```

## 使用

### Web UI

```bash
hermes-switch          # 启动 Web UI，自动打开浏览器
hermes-switch web      # 同上
hermes-switch web 8080 # 指定端口
```

打开浏览器访问 `http://127.0.0.1:9020`

### CLI

```bash
hermes-switch list       # 列出所有端点（分组显示）
hermes-switch current    # 显示当前端点
hermes-switch use st     # 切换到 st 端点
hermes-switch use st deepseek-v4-flash  # 切换端点并指定模型
hermes-switch remove old # 删除端点
hermes-switch rescan     # 重新扫描发现端点
```

## 概念

| 层级 | 说明 | 示例 |
|------|------|------|
| **Provider** | API 服务商类型 | `deepseek`, `openai`, `custom` |
| **Endpoint** | 具体的 API 接入点 | `st` (token.sensenova.cn), `hc` (api.iamhc.cn) |
| **Model** | 端点上可用的具体模型 | `deepseek-v4-flash`, `Kimi-K2.6` |

- **内置 Provider**: DeepSeek/OpenAI 等，不用填 base_url，Key 从环境变量读取
- **自定义端点**: 手动填写 base_url + api_key，如 tokenplan、iamhc、本地代理

## 端点配置

端点存储在 `endpoints.json`（与 Hermes 同目录），Web UI 中自动管理。

格式示例：

```json
{
  "st": {
    "base_url": "https://token.sensenova.cn/v1",
    "api_key": "sk-xxx",
    "provider": "custom",
    "model": "deepseek-v4-flash",
    "note": "商汤日日新",
    "_models": ["deepseek-v4-flash", "sensenova-6.7-flash-lite"]
  },
  "deepseek": {
    "base_url": "",
    "provider": "deepseek",
    "model": "deepseek-chat",
    "note": "DeepSeek 官方（Key 从环境变量读取）"
  }
}
```

## 切换后

切换后需要 **`/reset`** 或重启 Hermes 才能生效。Web UI 有「撤销切换」按钮。

## License

MIT
