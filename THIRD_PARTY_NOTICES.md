# Third-party notices

本项目的 macOS 微信辅助功能适配层参考并精简改造了
[BiboyQG/WeChat-MCP](https://github.com/BiboyQG/WeChat-MCP)。

本适配层对应的上游引用为 `master` 在 2026-09-13 查询到的提交
`cc470367ca6613b129f7e2bb742e6cc57df8c4d6`；上游分支继续变化时，需重新审查差异。

上游项目采用 MIT License，版权声明为：

```text
Copyright (c) 2025 Banghao Chi
```

本项目保留该来源说明和版权声明。当前适配层对应复用了
`wechat_accessibility.py` 的 AX 树遍历/应用查找能力、
`fetch_messages_by_chat_utils.py` 的消息列表读取思路，以及 MCP 服务的接口组织，
并将读取、导航和发送拆开；没有把上游会主动激活微信的入口原样作为后台读取接口。

上游完整许可文本同时随项目保存在
`licenses/BiboyQG-WeChat-MCP-MIT.txt`；来源仓库的许可证地址为：
https://github.com/BiboyQG/WeChat-MCP/blob/master/LICENSE
