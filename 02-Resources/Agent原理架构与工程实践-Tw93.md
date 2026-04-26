# 你不知道的 Agent：原理、架构与工程实践

> **作者**: Tw93 | **日期**: 2026-03-21
> **链接**: [原文](https://tw93.fun/2026-03-21/agent.html) | [BestBlogs 转载](https://www.bestblogs.dev/article/58852dc5)
> **标签**: #Agent #AI架构 #上下文工程 #工具设计 #记忆系统

系统梳理了 Agent 架构的核心工程实践，涵盖 **Agent Loop、Harness、上下文工程、工具设计（ACI）、记忆系统、多 Agent 组织、评测与追踪**等关键技术维度，并结合 OpenClaw 开源实现展示设计原则的落地方式。

核心判断：更贵的模型带来的提升很多时候没有想象中大，反而 Harness 和验证测试质量对成功率的影响更大；调试 Agent 时应优先检查工具定义；评测系统本身的问题比 Agent 出问题更难发现。

## 深度扩展

- [[Agent评测体系深度解析]] — 基于本文评测模块 + Anthropic 评测架构图的深度拆解
