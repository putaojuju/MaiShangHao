# 麦上号 (MaiShangHao)

麦麦离线消息同步 + AI做梦插件，让麦麦在启动时能够"看到"下线期间收到的消息，并在深夜生成荒诞梦境。

## 功能特性

### 📥 离线消息同步
- 启动时自动拉取 NapCat 群历史消息
- 智能去重：支持按消息ID或内容哈希去重
- 消息标记：在离线消息前后添加特殊标记
- 自动触发：同步完成后自动触发 planner 判断是否需要回复

### 💤 AI做梦功能
- 在指定时间段（如凌晨3-4点）自动生成梦境
- 梦境内容基于群聊历史，融入人物和话题
- 以转发消息形式发送，避免刷屏
- 与 planner 互斥，做梦期间不会触发回复

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

[dream]
enabled = true  # 启用做梦功能
groups = [123456789]  # 做梦的群号列表
times = ["03:00-04:00"]  # 做梦时间段
dreams_per_day = 1  # 每个群每天做梦次数
dream_interval_minutes = 60  # 多次做梦的最小间隔（分钟）
check_interval = 60  # 检查间隔（秒）
personality_traits = "此处填入你的bot人格"  # 梦境人格特质（必填！）
```

---

## 💤 做梦功能详解

### 什么是 AI 做梦？

AI 做梦是一个趣味功能，让麦麦在深夜"做梦"并分享梦境内容。梦境会：

1. **基于群聊历史**：从最近的聊天中提取人物、话题、关键词
2. **保持人格特质**：梦境内容符合麦麦的人格设定
3. **荒诞有趣**：像真正的梦一样逻辑跳跃、超现实
4. **转发消息发送**：以合并转发形式发送，不刷屏

### 示例梦境

```
💤 鈴的梦境记录

我梦见葡萄变成了代码，射命丸在用戳戳戳编译他。
DP和NEO在天上飞，我追着问它们是什么...
醒来后：还是没搞懂喵。
```

### 与 Planner 的互斥机制

做梦期间，插件会设置全局状态，Planner 会检测到并跳过回复判断，避免梦境生成与正常回复产生冲突。

### 配置人格特质

`personality_traits` 用于指导 AI 生成符合你 bot 人格的梦境内容。**这个配置非常重要**，如果留空或使用默认值，梦境可能不符合你 bot 的性格。

#### 如何填写？

1. **打开你的 `bot_config.toml`**（位于 `config/bot_config.toml`）

2. **找到 `[personality]` 部分**，查看 `personality` 字段：
   ```toml
   [personality]
   personality = "盐系、高冷、妈妈役、句尾加喵"
   ```

3. **提取关键人格特质**，用简洁的关键词描述：
   - ✅ 推荐：`"盐系、高冷、妈妈役、句尾加喵"`
   - ✅ 推荐：`"傲娇、毒舌、内心温柔、喜欢甜食"`
   - ❌ 不推荐：复制整个 personality 配置（太长会影响梦境生成效果）

4. **填写到插件配置**：
   ```toml
   [dream]
   personality_traits = "盐系、高冷、妈妈役、句尾加喵"
   ```

#### 也可以通过群聊命令修改

```
/dream set personality_traits 盐系、高冷、妈妈役、句尾加喵
```

### 多次做梦配置

通过配置可以实现每个群每天多次做梦：

```toml
[dream]
dreams_per_day = 3  # 每个群每天做3次梦
dream_interval_minutes = 30  # 两次做梦至少间隔30分钟
```

### 手动重置做梦计数

如果需要手动重置做梦计数（例如测试时），可以通过代码调用：

```python
from plugins.MaiShangHao.plugin import DreamHandler

# 获取实例
handler = DreamHandler.get_instance()
if handler:
    # 重置指定群的做梦计数
    handler.reset_dream_count("123456789")
    
    # 或重置所有群的做梦计数
    handler.reset_dream_count()
```

---

## 💻 群聊命令

插件提供了梦境管理命令，可以在群聊中直接使用：

### 命令列表

| 命令 | 说明 | 示例 |
|------|------|------|
| `/dream help` | 显示帮助 | `/dream help` |
| `/dream status` | 查看梦境状态 | `/dream status` |
| `/dream config` | 查看所有配置 | `/dream config` |
| `/dream config <项>` | 查看指定配置 | `/dream config groups` |
| `/dream enable` | 启用梦境功能 | `/dream enable` |
| `/dream disable` | 禁用梦境功能 | `/dream disable` |
| `/dream set <项> <值>` | 修改配置 | `/dream set dreams_per_day 3` |
| `/dream reset` | 重置所有群做梦计数 | `/dream reset` |
| `/dream reset <群号>` | 重置指定群做梦计数 | `/dream reset 123456789` |
| `/dream test` | 在当前群测试梦境 | `/dream test` |
| `/dream test <群号>` | 在指定群测试梦境 | `/dream test 123456789` |

### 配置项说明

| 配置项 | 类型 | 说明 |
|--------|------|------|
| `enabled` | bool | 是否启用梦境功能 |
| `groups` | list | 做梦的群号列表 |
| `times` | list | 做梦时间段 |
| `dreams_per_day` | int | 每天做梦次数 |
| `dream_interval_minutes` | int | 多次做梦间隔（分钟） |
| `check_interval` | int | 检查间隔（秒） |
| `personality_traits` | str | 梦境人格特质 |

### 权限控制

通过配置 `admin_users` 限制谁能使用梦境管理命令：

```toml
[dream]
admin_users = ["123456789", "987654321"]  # 只有这些用户可以使用命令
# admin_users = []  # 留空则没人可用（必须配置才能使用命令）
```

> ⚠️ **重要**：`admin_users` 为空时，梦境管理命令将无法使用。请务必配置至少一个管理员 QQ 号。

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
