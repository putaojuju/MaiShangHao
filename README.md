# 麦上号 (MaiShangHao)

麦麦离线消息同步插件，让麦麦在启动时能够"看到"下线期间收到的消息。

## 功能特性

- 📥 **离线消息同步**：启动时自动拉取 NapCat 群历史消息
- 🔄 **智能去重**：支持按消息ID或内容哈希去重，避免重复存储
- 🏷️ **消息标记**：在离线消息前后添加特殊标记，让 planner 和 replyer 识别
- 🤖 **自动触发**：同步完成后自动触发 planner 判断是否需要回复
- ⚙️ **灵活配置**：支持配置同步群列表、消息数量、延迟时间等

## 安装方法

1. 将插件文件夹放入 `plugins/` 目录
2. 确保 NapCat 开启了 HTTP API
3. 修改 `config.toml` 配置文件
4. 重启 MaiBot

## 配置说明

```toml
[plugin]
enabled = true  # 启用插件

[napcat]
http_url = "http://127.0.0.1:3000"  # NapCat HTTP API 地址
access_token = ""  # NapCat access_token（如有）

[sync]
groups = [123456789, 987654321]  # 需要同步的群号列表
message_count = 50  # 每个群同步的消息数量
delay_seconds = 5  # 启动后延迟同步的秒数
trigger_planner = true  # 是否触发 planner
add_markers = true  # 是否添加离线消息标记
```

## NapCat HTTP API 配置

确保 NapCat 的 HTTP API 已开启：

1. 打开 NapCat 配置目录（通常在 `%APPDATA%\NapCat\config`）
2. 编辑 `onebot11_<QQ号>.json` 文件
3. 确认以下配置：

```json
{
  "http": {
    "enable": true,
    "host": "0.0.0.0",
    "port": 3000,
    "secret": ""
  }
}
```

## 离线消息标记

当 `add_markers = true` 时，离线消息会显示为：

```
【离线消息开始】以下是你下线期间收到的消息：
... 离线消息内容 ...
【离线消息结束】以上是你下线期间收到的消息。
```

这样 planner 和 replyer 就能清楚地知道这些是离线期间的消息。

## 依赖

- aiohttp

## 许可证

MIT License

## 作者

putaojuju (葡萄)

## 版本历史

- v1.0.0 - 初始版本
