# A股智能决策系统 — 文档站

基于 LangGraph 的多 Agent 辩论式量化交易决策框架。

> **风险提示**：仅供研究与辅助决策参考，不构成投资建议。

## 快速导航

| 页面 | 内容 |
|------|------|
| [使用说明](使用说明.md) | 安装、CLI、Python API、15 角色架构、MCP server 配置 |
| [English](README.en.md) | Condensed English guide + rating glossary |
| [Token 控制改进方案](Token控制改进方案.md) | 调研与降耗策略路线图（现状诊断 / 六大策略） |
| [改进路线图](改进路线图.md) | P0/P1/P2 全项目改进方向与完成状态 |

## 一分钟概览

```bash
pip install -e ".[dev]"
export DEEPSEEK_API_KEY=hdsk-...   # 任意 OpenAI 兼容 provider 的 key
astock-trader analyze 600519 --provider deepseek --date 2025-06-01
```

或作为 MCP 工具暴露（Claude Desktop 等）：

```json
{
  "mcpServers": {
    "astock-trading-agents": {
      "command": "python",
      "args": ["D:/Qoder/astock-trading-agents/mcp_server.py"]
    }
  }
}
```
