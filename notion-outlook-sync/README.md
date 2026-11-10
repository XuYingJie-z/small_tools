# Notion databases → Outlook Calendar（单向同步）

这个脚本把多个 Notion data source 中带日期的页面，同步到 Outlook Calendar。它不会读取 Notion Calendar 这个聚合界面，而是逐个读取其底层 data source。

## 能做什么

- 多个 Notion data source → 一个 Outlook 日历
- 创建、更新 Outlook 事件
- Notion 状态变成“取消”或取消同步时删除 Outlook 事件
- SQLite 保存 `Notion page ID → Outlook event ID`，避免重复创建
- 支持全天日程、带时间日程、标题、备注、地点和来源前缀
- Dry-run 安全预览

## 前置条件

- Python 3.11+
- 一个 Notion internal integration token。在 https://app.notion.com/developers/connections 左边的 connection 申请，可以设置 connection 的权限和能访问的页面
- 每个底层 Notion database/data source 都已分享给该 integration
- 一个 Microsoft Entra 公共客户端应用，委派权限：
  - `Calendars.ReadWrite`
  - `User.Read`
- 在应用的 Authentication 设置中启用 **Allow public client flows**


## microsoft 微软 api

Default Directory - Microsoft Azure[https://portal.azure.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/Overview]

- microsoft azure 创建学生账户，然后左上角展开选项，点击「Microsoft Entra ID」
  - 没有学生账户的话就需要有万事达那种银行卡。真没有的话用 google 日历可能更好用。或者什么飞书 wps，没试过
- 点添加 → 应用注册 → 名称：Notion Outlook Sync
- **支持的账户类型（Supported account types）** 中选择：任何组织目录中的帐户 以及个人 Microsoft 帐户
- 复制 Client ID
- 开启设备代码登录:

```python
身份验证（Authentication）
→ 高级设置（Advanced settings）
→ 允许公共客户端流（Allow public client flows）
→ 是（Yes）
→ 保存
```

- 添加 Outlook 日历权限

```python
API 权限
→ 添加权限
→ Microsoft Graph
→ 委托的权限（Delegated permissions）

添加：
Calendars.ReadWrite
User.Read
```

### 再次打开 microsoft azure 如何找到刚注册的应用程序

portal.azure.com/  最顶部搜索 应用程序名称，好像只有这个办法，无法看到所有创建的应用程序


## 1. 安装

- 这里直接用 wsl 的 uv 环境，因为后面需要浏览器登陆验证，需要安装一下 requirements.txt

```bash
python -m venv .venv
pip install -r requirements.txt
```

##  获取 Notion data source ID

打开原始数据库页面，在数据库设置中进入 **Manage data sources**，使用 **Copy data source ID**。每个数据库都要添加到 Notion integration 的内容访问范围，或通过数据库右上角菜单的 **Add connections** 分享给它。
- notion api 建立： 随便一个 notion 页面右上角， connection -> manage connection -> go to develop portal -> make new connection 然后起名，管理能访问的页面 


##  配置

复制模板，参考模板里面是怎样写的：

```bash
## 复制为隐藏文件, 在 .gitignore 配置了隐藏文件不会上传到 github 仓库
cp env.example .env   
cp config.example.json .config.json
```

编辑 `.env`，输入各种凭据：

- `NOTION_TOKEN`：Notion internal integration token
- `MICROSOFT_CLIENT_ID`：Microsoft Entra 应用的 Application (client) ID
- `OUTLOOK_CALENDAR_ID`：留空即默认日历
- 首次保留 `DRY_RUN=true`

编辑 `config.json`，决定推送的内容项目。必填字段：

- `name` 可以自己定义
- `data_source_id`  前面获取 Notion data source ID
- `title_property` 这个是 outlook 日历任务的类型，例如 名称， 日程
- `date_property`

可选字段：

- `status_property` + `cancelled_values`
- `description_property`
- `location_property`
- `title_prefix` ：在名称前加前缀，例如 工作
- `sync_only_when`：例如只有“同步到 Outlook”复选框为 true 才同步
- `show_as`：`free`、`tentative`、`busy`、`oof`、`workingElsewhere`、`unknown`
- `sensitivity`：`normal`、`personal`、`private`、`confidential`

若不需要 `sync_only_when`，请从该 source 中删除整个对象，不要保留不存在的字段名。



## 4. 首次运行

```bash
python notion_outlook_sync.py --dry-run --verbose
```

检查日志中的 CREATE / UPDATE / DELETE 计划。确认字段名没有错误后：

1. 将 `.env` 中 `DRY_RUN=false`
2. 正式执行：

```bash
python notion_outlook_sync.py
```

首次正式执行会显示 Microsoft 设备登录网址和验证码。浏览器授权后，令牌会缓存到 `msal_token_cache.json`，以后通常无需重复登录。

只同步某一个配置源：

```bash
python notion_outlook_sync.py --source "工作任务"
```

## 5. 删除策略

默认 `DELETE_MISSING_EVENTS=false`，避免误删。

即使保持 false，以下情况仍会删除已映射的 Outlook 事件：

- 状态命中 `cancelled_values`
- `sync_only_when` 不再满足
- 日期字段被清空

设置 `DELETE_MISSING_EVENTS=true` 后，若某页面不再由一个**成功查询完成**的 data source 返回，脚本也会删除对应 Outlook 事件。这可处理 Notion 页面被删除/移入回收站，但建议完成测试后再开启。

## 6. 定时运行

Windows 任务计划程序可每 10 分钟运行：

```text
程序：C:\path\to\.venv\Scripts\python.exe
参数：C:\path\to\notion_outlook_sync.py
起始位置：C:\path\to\notion-outlook-sync
```

Linux/macOS cron 示例：

```cron
*/10 * * * * cd /path/to/notion-outlook-sync && .venv/bin/python notion_outlook_sync.py >> sync.log 2>&1
```

## 重要行为

- 这是单向同步：Outlook 中的手动修改会在下一次 Notion 内容变化时被覆盖。
- 脚本不会同步 Notion 的重复日程规则；每个 Notion 页面会成为一个普通 Outlook 事件。
- 全天范围默认按 Notion UI 的“结束日包含在范围内”处理，并转换成 Outlook 的排他结束时间。可将 `notion_all_day_end_is_inclusive` 改为 false。
- SQLite 和 MSAL token cache 必须保存在持久化磁盘上。
- 不要提交 `.env`、SQLite 或 token cache 到 Git。
