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
2. 首次启动后，插件会自动生成 `config.toml` 配置文件
3. 确保 NapCat 开启了 HTTP API（详见下方教程）
4. 修改 `config.toml` 配置文件
5. 重启 MaiBot

> 💡 **提示**：如果需要参考配置示例，可以查看 `config.example.toml`

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

---

## 📖 小白教程：如何获取 NapCat HTTP API 地址

### 方法一：通过 NapCat WebUI 查看（推荐 ✨）

**第一步：打开 NapCat WebUI**

在浏览器中访问 NapCat 管理界面：
- 默认地址：`http://127.0.0.1:6099`
- 如果你是用一键包，启动时控制台会显示 WebUI 地址

**第二步：登录 WebUI**

输入你的 WebUI 密码登录（密码在首次启动时设置，或查看配置文件）。

**第三步：进入网络配置**

1. 点击左侧菜单 **「机器人」**
2. 找到你登录的 QQ 账号，点击 **「配置」** 或 **「网络配置」**
3. 在网络配置页面找到 **「HTTP 服务」** 区域

**第四步：查看或创建 HTTP 服务**

如果已有 HTTP 服务：
- 直接查看端口号（如 `3000`、`5700` 等）
- 记下 `token`（如果有设置）

如果没有 HTTP 服务：
1. 点击 **「添加 HTTP 服务」**
2. 填写配置：
   - **名称**：随便填，如 `MaiShangHao`
   - **主机**：`127.0.0.1` 或 `localhost`
   - **端口**：填一个未占用的端口，如 `3000`
   - **Token**：可留空，或设置一个密码
3. 点击 **「保存」** 或 **「启用」**

**第五步：填写插件配置**

假设你看到的 HTTP 端口是 `3000`，token 是 `abc123`：

```toml
[napcat]
http_url = "http://127.0.0.1:3000"
access_token = "abc123"  # 没有设置 token 就留空
```

---

### 方法二：通过配置文件查看

**第一步：找到配置文件**

NapCat 的配置文件位置：

| 情况 | 路径 |
|------|------|
| 一键包 | `MaiBotOneKey\modules\napcat\versions\<版本号>\resources\app\napcat\config\` |
| 独立安装 | `%APPDATA%\NapCat\config\` 或 NapCat 目录下的 `config\` |

**第二步：打开 OneBot 配置文件**

找到名为 `onebot11_<你的QQ号>.json` 的文件，用记事本打开。

**第三步：查看 HTTP 服务配置**

找到 `httpServers` 部分：

```json
{
  "network": {
    "httpServers": [
      {
        "enable": true,
        "name": "我的HTTP服务",
        "host": "localhost",
        "port": 3000,
        "token": ""
      }
    ]
  }
}
```

关键信息：
- `enable`: 必须为 `true`
- `port`: 这就是 HTTP 端口号
- `token`: 如果有值，填入 `access_token`

**第四步：如果没有 HTTP 服务**

在 `httpServers` 数组中添加：

```json
{
  "enable": true,
  "name": "MaiShangHao HTTP",
  "host": "localhost",
  "port": 3000,
  "token": ""
}
```

保存后重启 NapCat。

---

### 方法三：通过启动日志查看

NapCat 启动时，控制台会显示类似信息：

```
[HTTP] HTTP服务已启动: http://localhost:3000
```

这里的 `3000` 就是 HTTP 端口。

---

## ⚠️ 常见问题

### Q: 提示"远程计算机拒绝网络连接"

**原因**：NapCat 的 HTTP API 未开启或端口错误

**解决方法**：
1. 确认 NapCat 正在运行
2. 按照上面的教程找到正确的 HTTP 端口
3. 确保 HTTP 服务已开启（`enable: true`）
4. 检查端口是否被其他程序占用

### Q: 如何测试 HTTP API 是否正常？

在浏览器中访问：`http://127.0.0.1:你的端口/get_login_info`

正常返回：
```json
{
  "status": "ok",
  "data": {
    "user_id": "123456789",
    "nickname": "你的昵称"
  }
}
```

异常返回：
```json
{
  "status": "failed",
  "message": "..."
}
```

### Q: 需要配置 access_token 吗？

如果你在 NapCat 的 HTTP 服务中设置了 `token`，就需要在 `config.toml` 中填写相同的值：

```toml
[napcat]
http_url = "http://127.0.0.1:你的端口"
access_token = "你的token"
```

如果没有设置 `token`，留空即可。

### Q: 一键包用户如何快速查看？

如果你使用的是 MaiBotOneKey 一键包：

1. 打开一键包目录下的 `modules\napcat\versions\<版本号>\resources\app\napcat\config\`
2. 找到 `onebot11_<你的QQ号>.json`
3. 查看 `httpServers` 部分的 `port` 和 `token`

---

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
