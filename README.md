# 微信通知处理 Skill 与 MCP

这是一个面向普通微信的半自动通知处理工具：通过 macOS 辅助功能读取可取得的群消息，保存消息和附件原件，读取消息中的网页/公众号图片并尝试本地 OCR，交给 Codex 的 `skills/wechat-notice/SKILL.md` 完成事项分类、总结和审核，再由用户决定是否转发。

首版不创建独立 App，不自动向微信群发送消息，也不创建真实的 Codex 自动化。提醒检查已经实现为可被 Codex 定时唤醒调用的幂等命令。

## 已实现的边界

- 默认收交提前天数为 2 天，只应用于班级统一收集、汇总并上交的文件。
- 上级原截止时间默认隐藏，可配置为展示。
- 提醒提前天数默认为 `[2, 1]`，提醒检查默认使用 Asia/Shanghai 每天 09:00。
- 每条通知可以单独关闭提醒；全局参数只影响未批准的草稿。
- 原件保存到 `data/`，不修改文件内容；状态和提醒使用 SQLite 事务保存。
- PDF、DOCX、XLSX、PPTX 解析为带来源位置的文本；PDF 空白页和图片会尝试本地 Tesseract OCR，失败仍进入视觉复核状态，加密文件和不支持格式会明确失败。
- WeChat-MCP 适配层默认只读，不激活窗口、不发全局鼠标键盘事件、不截图判断发送者。
- 发送接口要求同时提供审核授权和前台操作授权；文件发送暂标记为未验证。
- 生成通知包时输出通知润色版、省流版、Mermaid 源码、单屏优先的流程图 PNG、省流版 PNG 和审核说明；长事项自动按章节输出多张图，Mermaid CLI 不存在时使用本地 Pillow 备用渲染并保留 `.mmd`。

## 本地使用

首次运行先创建项目虚拟环境并安装依赖。MCP 当前使用 FastMCP v1 接口，因此依赖约束为 `mcp>=1.0,<2`：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[documents,mcp,macos,dev]'
```

检查核心逻辑：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

查看微信能力状态（不会激活微信）：

```bash
.venv/bin/python -m wechat_notice capabilities
```

检查提醒数据（可由 Codex 内置自动化调用）：

```bash
.venv/bin/python -m wechat_notice reminders --data-root data
```

用三条合成通知验收完整产出（不会启动微信）：

```bash
.venv/bin/python -m wechat_notice simulate --output-dir data/simulated
```

也可以直接从结构化事实生成通知包，或读取一个网页/公众号地址：

```bash
.venv/bin/python -m wechat_notice generate-package \
  --input examples/simulated_notices.json --output-dir data/artifacts
.venv/bin/python -m wechat_notice read-material --url 'https://example.org/notice'
```

`monitor-once` 用于把 MCP 或手动输入的一次消息窗口做增量去重；只有消息元数据中有稳定标识时才去重，没有稳定标识的消息会列为待核对，不按正文删除：

```bash
.venv/bin/python -m wechat_notice monitor-once \
  --input examples/monitor-window.json --data-root data
```

批次已经导入后，读取并保存其中消息链接的网页/公众号正文和图片 OCR 结果：

```bash
.venv/bin/python -m wechat_notice read-batch-materials \
  --batch-id batch-example-001 --data-root data
```

参数可以通过命令行调整：

```bash
.venv/bin/python -m wechat_notice settings --data-root data \
  --collection-advance-days 2 \
  --hide-original-deadline \
  --reminder-offsets 2,1 \
  --reminder-time 09:00
```

导入消息和附件的 JSON 示例见 `examples/batch.json`；创建通知草稿的示例见 `examples/notice.json`。Codex 自动化的唤醒提示见 `docs/codex-automation-prompt.md`。

启动 MCP 需要先安装项目的 `mcp` 和 macOS 依赖：

```bash
.venv/bin/python -m wechat_notice.wechat_mcp.server --transport stdio
```

将本地 MCP 注册给 Codex（只需执行一次）：

```bash
codex mcp add wechat-notice \
  --env 'WECHAT_NOTICE_DATA_ROOT=/Users/mac2/Documents/ChatGPT/微群Agent接入计划/data' \
  -- /Users/mac2/Documents/ChatGPT/微群Agent接入计划/.venv/bin/python \
  -m wechat_notice.wechat_mcp.server --transport stdio
```

HTTP/SSE 传输默认关闭，因为接口会接触群消息和本地原件；只有在受信本机明确设置
`WECHAT_NOTICE_ALLOW_NETWORK_MCP=1` 后才允许启用，项目本身不提供网络鉴权。

启动后可用的 MCP 工具为：

- `check_wechat_capabilities`：只读能力检查；
- `fetch_messages_by_chat`：读取当前可访问会话的消息，并返回完整性和缺失字段；
- `get_attachment_for_message`：查询已登记且仍存在的原件；当前 AX 不自动下载附件，缺失时返回明确失败；
- `send_reviewed_text`：要求通知 ID、批准版本、用户审核及允许前台操作后发送文字；
- 文件发送能力尚未验证，因此不注册文件发送 MCP 工具，交给用户使用微信原生转发。

通知审核过程还可用 `update-notice` 修改日期、目标群或提醒参数，
用 `cancel-notice` 取消事项及未发送提醒；两者都不会发送微信消息。

`fetch_messages_by_chat` 默认把本次读取结果保存为一个批次并返回 `batch_id`；
如只需做兼容性观察，可传 `persist=false`，不会写入批次数据。

## 目录

```text
src/wechat_notice/                 核心数据、存储、日期和文档处理
src/wechat_notice/wechat_mcp/      精简的 macOS AX/MCP 适配层
src/wechat_notice/material_reader.py 网页/公众号正文及图片 OCR
src/wechat_notice/notice_package.py  事实到通知包、章节 Mermaid 和图稿
src/wechat_notice/monitor.py         稳定消息标识增量监控
skills/wechat-notice/SKILL.md          Codex 通知处理 Skill
skills/wechat-notice-lite/SKILL.md     通知润色子 Skill，可独立润色用户提供的通知
skills/wechat-notice-diagram/SKILL.md  Mermaid 流程图与省流图片子 Skill
tests/                              不依赖微信的离线回归测试
data/                               运行时原件、批次和 SQLite（默认不入 Git）
```

项目优先保留可注入的材料读取接口；现有 baoyu URL-to-Markdown Skill 可作为后续抓取适配器，但本机 Bun/该 Skill 的依赖未就绪，本阶段不把它列为运行前提。`examples/simulated_notices.json` 只验证离线生成链路，不代表微信采集、真实公众号访问、OCR 准确率或发送已验收。真实微信读取、窗口遮挡、重复文本翻页、附件卡片及发送结果仍需在用户授权的测试环境中验证。未验证能力不会被接口标记为已支持。
