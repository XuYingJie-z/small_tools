# 微信 ClawBot 通知

使用服务器上的 Python 脚本，通过微信 ClawBot 给自己的微信发送文本通知。服务器需要能够访问微信接口。接口细节可参考[腾讯微信接口协议](https://github.com/Tencent/openclaw-weixin/blob/main/docs/protocol_zh_CN.md)。

- 注意！！！：必须使用脚本生成二维码，不能在网页端操作
- 也可以看 notion 的 codex 笔记
> 用 uv 的 pdf_process 环境

## 第一步 wechat_clawbot.py

此脚本负责扫码绑定、更新会话凭据和发送微信通知。

### 1. 设置命令路径

在服务器终端执行：

```bash
WX_PY=/dssg/home/acct-bioxsyy/bioxsyy-xyj/xyj/software/uv_env/pdf_process/.venv/bin/python
WX_SCRIPT=/dssg/home/acct-bioxsyy/bioxsyy-xyj/xyj/software/wechat_notify/wechat_clawbot.py
```

这两个变量只在当前终端中有效；打开新终端或编写独立任务脚本时，需要重新设置，或者使用完整路径。

### 2. 首次扫码绑定

首次使用或机器人凭据失效时运行：

```bash
"$WX_PY" "$WX_SCRIPT" login
```

1. 保持终端运行，用手机微信扫描终端显示的二维码，并在手机上确认。如果提示输入验证码，按照终端提示输入。
2. 终端显示“扫码绑定成功”后，向微信中的 ClawBot 发一条任意消息。
3. 终端显示“会话已建立，可以发送通知”后，绑定完成。

已有有效凭据时不需要重复扫码。如果扫码成功但获取会话失败，可以按照第 4 节单独刷新会话。

### 3. 发送通知

先发送一条测试消息，并在微信 ClawBot 会话中确认是否收到：

```bash
"$WX_PY" "$WX_SCRIPT" send "测试：服务器微信通知"
```

终端中的“微信接口已接受请求”表示接口已接受发送请求，最终请以微信实际收到的消息为准。

也可以在任务成功后发送通知：

```bash
python your_script.py && "$WX_PY" "$WX_SCRIPT" send "分析任务已完成"
```

上面的通知仅在 `your_script.py` 成功退出时发送。也支持省略 `send`，直接使用 `"$WX_PY" "$WX_SCRIPT" "消息内容"`。

### 4. 刷新会话

会话凭据可能过期。如果通知发送失败，可以运行：

```bash
"$WX_PY" "$WX_SCRIPT" refresh
```

看到终端提示后，向微信 ClawBot 再发一条任意消息，等待终端提示会话已建立，然后重试发送。如果机器人本身的登录凭据也已失效，需要重新运行 `login` 并扫码。

### 5. 凭据文件

绑定信息保存在脚本同目录下：

```text
/dssg/home/acct-bioxsyy/bioxsyy-xyj/xyj/software/wechat_notify/.wechat_clawbot.json
```

其中包含扫码取得的 `bot_token`、微信账号标识、接口地址、消息游标和获取到的 `context_token`。脚本保存时将文件权限设为 `600`；凭据不要分享或提交到代码仓库。

### 6. 常见问题

- **手机扫码后一直加载**：保持终端运行，查看是否显示“已检测到微信扫码”。二维码可能过期；可按 `Ctrl+C` 结束命令，重新运行 `login` 并扫描新二维码。也可以尝试将手机切换到移动网络。
- **终端显示查询扫码状态超时**：脚本会在整体等待时间内自动重试。若最终仍未成功，请检查服务器网络和代理，再重新登录。
- **没有 OpenCV**：脚本会输出临时绑定链接，可尝试在手机微信中打开；发送通知本身不需要 OpenCV。当前脚本不会自动保存二维码图片。
- **找不到凭据文件**：确认运行的是本笔记中 `wechat_notify` 目录下的脚本，然后执行 `login`。
- **发送失败或微信未收到消息**：先检查服务器是否能访问微信接口，再按第 4 节刷新会话并重试。

## codex_wechat_hook.py

此脚本由 Codex Hook 启动，读取事件信息，再调用 `wechat_clawbot.py` 发送提醒。需要先完成上面的扫码绑定和会话建立。

### 通知事件

| Codex 事件 | 微信提醒 | 说明 |
| --- | --- | --- |
| `Stop` | 本轮回复已结束 | 每轮回复结束时触发；回复中包含提问时也可能触发，并不表示整个对话或任务已经结束。 |
| `PermissionRequest` | 正在请求操作权限 | 对受支持的权限请求发送提醒，仍需回到 Codex 确认；脚本不会自动批准。 |
| `PreToolUse` | 请求补充信息 | 尝试匹配 `request_user_input` 和 `request_user_input_async` 工具；是否能捕获取决于当前界面和工具路径，需要实测。 |

普通回复中的文字提问没有独立的 Hook 事件，但一轮回复结束时仍可能收到 `Stop` 提醒。同一轮对话也可能收到多条提醒。

### 配置和启用 Hook

本机已启用的用户级配置位于 `~/.codex/hooks.json`，配置示例保存在脚本同目录的 `codex_hooks.example.json`。如果需要在本机重新配置，且 `~/.codex/hooks.json` 不存在，可以运行：

```bash
cp -n \
  /dssg/home/acct-bioxsyy/bioxsyy-xyj/xyj/software/wechat_notify/codex_hooks.example.json \
  ~/.codex/hooks.json
```

`cp -n` 不会覆盖已有文件。如果 `~/.codex/hooks.json` 已存在，应将示例文件 `hooks` 下的事件配置合并到现有文件；对于已有的同名事件，把示例中的配置项追加到该事件的数组中。

示例配置为三个事件调用同一个脚本，其中 `PreToolUse` 的匹配规则为 `request_user_input(_async)?$`。每个 Hook 都设置为后台运行（`async: true`），超时时间为 30 秒。配置中的 Python 和脚本路径是当前服务器的绝对路径，迁移位置后需要相应修改。

重启 Codex 后，在 CLI 中输入 `/hooks`，检查并信任新增或修改过的 Hook。随后可让 Codex 回复一条消息，检查微信是否收到 `Stop` 提醒；权限和补充信息提醒需要在相应事件实际触发时验证。

### 通知内容

通知包含当前会话的工作目录、任务名称和事件类型，例如：

```text
~/xyj/software · 微信实现推送消息

Codex 本轮回复已结束，请查看对话。

回复末行：分析结果已保存。
```


## 路境内的其他内容

- qq_mail_notify.py : 如果 clawbot 用不了，这里尝试用 qq 邮箱进行通知，但是还没做测试
 

