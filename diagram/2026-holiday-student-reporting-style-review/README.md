# 离校报备步骤图：三种样式审查版

这组图比较“电脑端/移动端离校报备步骤”的三种表达方式，不改变通知事实。三种布局均保留为 `wechat-notice-diagram` 的可选模式。

## 三种样式

1. `style-01-vertical-cards.mmd/png`：纵向步骤卡。每个端口独立向下串行，适合手机阅读。
2. `style-02-swimlanes.mmd/png`：双泳道时间线。电脑端和移动端各自从左到右推进，适合横向对照。
3. `style-03-decision-flow.mmd/png`：选择分支流程。从“选择办理端”分开，再按步骤完成，适合强调入口选择。
4. `summary.mmd/png`：极简省流版，仅保留两端路径和共同结果。

## 综合信息总览模板效果

`comprehensive-overview.mmd/png` 是新增 `template=comprehensive_overview` 的实际示例：它把来源、假期安排、办理入口、两端逐步操作、完成结果和补课安排放在一张图里；两端步骤仍然逐项串行，没有压缩成一个节点。

## 审查重点

- 是否要把电脑端和移动端放在同一张图中对照。
- 是否需要保留“选择办理端”这个分支节点。
- 步骤卡、泳道或分支流程中，哪一种更符合后续通知图的默认模式。

渲染使用 `@mermaid-js/mermaid-cli` 调用本机 Google Chrome；三种布局和完整 URL 显示规则已固化到 `wechat-notice-diagram` skill。
