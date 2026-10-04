# 职投档案

支持简体中文 / English、本机保存的个人求职管理工具，用于记录投递网页、JD、实际提交的 CV 与动机信、投递状态，以及关联的 Gmail 邮件。

**当前源码 / 本机构建版本 1.2.0**：Windows ZIP 解压后双击 `JobArchive.exe`。公开发布版本见 [Releases](https://github.com/YifanY96/jobarchive/releases)。应用使用独立 Windows 窗口，软件仅监听 `127.0.0.1`。源码仓库不包含 EXE、运行库或用户的个人档案。

`JobArchive.exe` 与 `_internal` 文件夹必须一起保留。桌面版自带 Python 运行环境，使用本机已有的 Microsoft Edge WebView2，不需要安装 Python、Node 或 Docker，也不需要管理员权限。关闭窗口即停止该实例的本地服务，记录已在保存时写入磁盘；重复启动会回到现有窗口。现有 `data` 文件夹继续使用，无需迁移。备份和附件下载通过 Windows「另存为」对话框保存。

## 语言显示修复

- 修复英文日期框出现中文“日”：统一显示 `YYYY-MM-DD`，月份、星期、选择日期和清空操作随界面语言切换。
- 修复英文设置标题中混入中文：English 显示 `Language`，简体中文显示「界面语言」。
- 所有四个日期输入框使用同一日期控件，仍按 ISO 日期保存，原有记录兼容。

## 1.2.0 更新

- 「备份与设置 → 界面语言（English 界面显示 Language）」选择简体中文或 English，立即切换并保存在本机 `data/preferences.json`，重启或改变本地端口后仍然生效。
- 导航、表单、状态、历史标签、提示与 CSV 字段可切换语言。JD、备注、邮件、原始文件名和附件内容保持原文，已有记录与备份继续兼容。日期输入和日历由软件控制语言；Windows 系统文件窗口的按钮可能跟随系统语言。
- 档案详情可直接更新状态，保留 JD、附件及历史版本；重复选择同一状态不会生成多余历史。
- 筛选显示匹配数量，可一键清除；隐藏记录时同时清除旧详情，快速切换档案不会显示上一条记录的内容。
- 关闭编辑表单前提醒未保存修改；抓取 JD 前确认替换，保留已填写的公司及职位。
- 支持 `Ctrl + K` 搜索、`Ctrl + N` 新建，改善英文长按钮及较小窗口的布局。

语言偏好属于本机设置，不随 ZIP 备份恢复而改变。

## 日常使用

1. 点击「新建投递」，填写公司、职位、网页、日期和状态。
2. 粘贴公开职位网页，点击「抓取 JD」，核对抓取结果再保存。优先提取网页 JobPosting 结构化数据；没有时提取正文。动态加载、登录限制或反爬网页可能失败，此时手动粘贴 JD。
3. 上传这次**实际提交**的 CV、动机信，或粘贴动机信正文。每次新上传都独立保存，不覆盖旧文件。单份 25 MB，一次最多 10 份上传；一次总请求上限 80 MB（包含编码体积，较大文件请分批）。支持 PDF、DOC、DOCX、TXT、MD、RTF。
4. 点击档案查看 JD、材料下载、邮件和更新历史；「编辑 / 归档材料」可手动改状态或补充新材料。提交日期和版本说明随新材料保存；旧 JD 保留在历史快照中。
5. 仅搜索公司名和职位名，不区分大小写，支持连续部分文字匹配；按状态、日期筛选与排序。
6. 在「备份与设置」导出 ZIP 或 CSV。ZIP 包含全部档案、文件、更新历史、已缓存邮件；CSV 只有投递字段。恢复前自动生成 `data/backups/恢复前_*.zip`，恢复替换当前记录和附件，保留当前 Gmail 连接配置。恢复压缩包和解压大小各限 400 MB，条目限 10000。

## Gmail 首次连接

这不是 Gmail 插件登录；工具使用你自己的 Google 桌面 OAuth 客户端。无需把密码填写到软件。

1. 在 [Google Cloud Console](https://console.cloud.google.com/) 创建/选择项目，启用 Gmail API。
2. 配置 Google Auth Platform/OAuth 同意屏幕；个人使用可保持测试模式，把自己的 Gmail 加入测试用户。
3. 创建 OAuth 客户端，应用类型选「桌面应用」，下载 JSON。
4. 在「求职邮箱」导入 JSON，点击「连接 Gmail」，在 Google 页面同意 Gmail **只读**权限，然后回来刷新连接状态。
5. 使用 Gmail 查询条件（默认 `newer_than:90d`）同步邮件，每批最多 30 封；「下一批」继续分页。查询可使用 `from:`、`subject:` 等 Gmail 搜索语法。
6. 打开邮件，选择投递并保存关联。关键词只提供状态建议，你核对邮件后点击确认更新。不会自动改状态、发送邮件或删除 Gmail 邮件。

官方参考：[桌面 OAuth 和 loopback 回调](https://developers.google.com/identity/protocols/oauth2/native-app)、[Gmail 消息查询](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list)、[只读权限](https://developers.google.com/workspace/gmail/api/auth/scopes)。Google 测试模式授权可能过期，出现授权失效可重新连接。客户端必须是桌面类型，不能使用 Web 应用客户端 JSON。

Gmail 凭据保存在 `data/gmail-credentials.dpapi`，使用 Windows 当前用户加密，不进入导出包。缓存邮件正文、JD、CV 和动机信以本机普通文件/数据库保存，备份也包含这些个人内容。换电脑恢复后需要重新绑定邮箱。断开会尝试撤销 Google 授权并清除本机缓存；若网络撤销失败，页面会提示在 Google 账号权限页撤销。

## 保存位置与运行

数据位于软件目录下的 `data`：数据库 `archive.sqlite3`、附件 `files`、恢复前备份 `backups`。文件实际名称使用 UUID，原始名称和 SHA-256 校验值记录在数据库中。请使用页面上的完整备份功能；不要只复制数据库而遗漏附件。

无需 Docker、Node、云服务或付费 AI API。桌面 EXE 已附带运行环境。仅在运行源码/旧浏览器版时需要 Python 3.12+；可直接运行：

```powershell
python server.py --open
```

端口默认自动选择。重复启动会回到已运行实例。桌面版关闭窗口会停止服务；旧浏览器版关闭网页不会停止服务，可在设置页点击「停止本地服务」。不修改系统 PATH，不创建开机自启。

## 重新构建桌面版

在独立构建环境中安装 `desktop-requirements.txt`，运行 `python build_desktop.py`。使用 [pywebview 官方桌面打包方案](https://pywebview.flowrl.com/guide/freezing.html) 和 [PyInstaller](https://pyinstaller.org/en/stable/usage.html)。本次构建使用 pywebview 6.2.1、PyInstaller 6.22.3 和 Python 3.12。默认产物在 `build/dist/JobArchive`，可用 `--output-dir` 指定构建目录。发布时保留 EXE 与 `_internal` 文件夹，不打包用户的 `data`。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r desktop-requirements.txt
.\.venv\Scripts\python.exe build_desktop.py
```

重新构建前关闭桌面版，再更新 EXE 和 `_internal`；保留 `data`。诊断日志在 `data/desktop.log`。

## 验证与限制

界面逻辑另有 5 项检查（需要 Node.js，仅开发验证使用）：`node --test test_frontend.cjs`，覆盖公司/职位搜索边界、英文显示与原始状态兼容、静态界面翻译覆盖、纯英文语言标题及日期有效性。1.2.0 中英文打包窗口均通过启动验证。

```powershell
python -m unittest test_server -v
```

已验证独立文件版本、记录历史、备份恢复及损坏备份拒绝、公开 JD 结构解析、内网抓取拒绝、邮件正文解码、Windows DPAPI 加密、API 访问限制，以及页面新增、状态编辑和搜索流程。测试数据位于开发工作目录，正式数据初始为空。

桌面构建环境运行 `python -m unittest discover -s . -p "test_*.py" -v`，14 项检查通过（包含语言持久化、原有记录兼容、快捷状态更新、英文 CSV，以及模拟原生保存窗口的 ZIP/CSV 导出、取消保存、错误令牌及外部页面拒绝）。打包 EXE 的 `--smoke-test --data-dir <测试目录>` 已验证实际 WebView2 窗口加载、本地接口以及 JavaScript/Python 导出桥接；使用独立测试档案，不影响用户记录。

真实 Gmail 授权和同步尚未验证，需要用户导入客户端 JSON 并授权。网页抓取不保证支持所有招聘站点。当前是单用户本机工具，没有自动投递、自动检查网页或后台定时收邮件；需手动点击抓取/同步。
