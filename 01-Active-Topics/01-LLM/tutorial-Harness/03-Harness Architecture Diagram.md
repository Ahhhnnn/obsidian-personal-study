# Harness Engineering 架构图

## 核心公式

$$\text{Agent} = \text{Model} + \text{Harness}$$

---

## 整体架构图

```mermaid
graph TB
    subgraph Human["👤 人机协作层 (Human Steering)"]
        H1["📋 AI代码审查清单"]
        H2["🚨 升级/人工介入策略"]
        H3["🔄 Harness 持续迭代"]
    end

    subgraph Harness["🏗️ Harness 驾驭层"]
        direction TB

        subgraph Feedforward["📡 前馈控制 (Feedforward Guides)"]
            direction LR
            F1["📄 规则文档<br/>AGENTS.md / CLAUDE.md"]
            F2["📐 架构设计文档<br/>API契约 / 编码规范"]
            F3["🛠️ Skills / How-tos<br/>引导脚本"]
            F4["🔧 Codemods<br/>代码迁移工具"]
        end

        subgraph Feedback["🔍 反馈控制 (Feedback Sensors)"]
            direction LR
            B1["⚡ Linter / 类型检查<br/>(计算型 · 快速)"]
            B2["🧪 测试套件 / 结构测试<br/>(计算型 · 确定性)"]
            B3["🤖 AI Review Agent<br/>(推理型 · 语义分析)"]
            B4["📊 覆盖率 / 变异测试<br/>(计算型 · 深度)"]
        end

        subgraph Context["🧠 上下文工程 (Context Engineering)"]
            direction LR
            C1["📑 静态上下文<br/>仓库文档 / 规范"]
            C2["🔄 动态上下文<br/>目录映射 / CI状态"]
            C3["🔗 知识库集成<br/>MCP Server"]
        end

        subgraph ArchConstraints["🏛️ 架构约束 (Architectural Constraints)"]
            direction LR
            A1["📐 分层依赖规则<br/>Types→Config→Service→UI"]
            A2["🔍 自定义Linter<br/>自动标记违规"]
            A3["🧱 结构化测试<br/>ArchUnit 边界检查"]
            A4["🪝 Pre-commit Hooks<br/>提交前自动检查"]
        end

        subgraph Entropy["🧹 熵管理 / 垃圾回收 (Entropy Management)"]
            direction LR
            E1["📄 文档一致性Agent"]
            E2["🔎 约束违规扫描"]
            E3["🔄 模式执行Agent"]
            E4["📦 依赖审计"]
        end

        subgraph Observability["👁️ 可观测性 (Observability)"]
            direction LR
            O1["📈 Agent行为监控<br/>成功率/Token消耗"]
            O2["⏱️ 运行时反馈<br/>SLO 延迟/错误率"]
            O3["🏥 Harness健康度<br/>规则是否过时/矛盾"]
        end
    end

    subgraph Model["🤖 AI 模型层"]
        M1["LLM<br/>(Claude / GPT / Gemini)"]
    end

    %% 前馈 → Agent
    Feedforward -->|"行动前预防"| M1
    Context -->|"提供正确信息"| M1
    ArchConstraints -->|"强制执行边界"| M1

    %% Agent → 反馈
    M1 -->|"生成代码"| Feedback
    Feedback -->|"自我纠正"| M1

    %% 熵管理
    Entropy -->|"定期清扫代码库"| M1

    %% 可观测性
    Observability -.->|"监控"| Harness
    Observability -.->|"监控"| M1

    %% 人机协作
    Human -->|"Steer"| Feedforward
    Human -->|"Steer"| Feedback
    Human -->|"Steer"| Observability

    %% 样式
    classDef human fill:#FFF3E0,stroke:#FF9800,stroke-width:2px,color:#333
    classDef harness fill:#E3F2FD,stroke:#1976D2,stroke-width:2px,color:#333
    classDef feedforward fill:#E8F5E9,stroke:#4CAF50,stroke-width:1px,color:#333
    classDef feedback fill:#FFF3E0,stroke:#FF9800,stroke-width:1px,color:#333
    classDef context fill:#F3E5F5,stroke:#9C27B0,stroke-width:1px,color:#333
    classDef arch fill:#E0F7FA,stroke:#00BCD4,stroke-width:1px,color:#333
    classDef entropy fill:#FCE4EC,stroke:#E91E63,stroke-width:1px,color:#333
    classDef obs fill:#F5F5F5,stroke:#9E9E9E,stroke-width:1px,color:#333
    classDef model fill:#FFEBEE,stroke:#F44336,stroke-width:2px,color:#333

    class Human human
    class Harness harness
    class Feedforward feedforward
    class Feedback feedback
    class Context context
    class ArchConstraints arch
    class Entropy entropy
    class Observability obs
    class Model model
```

---

## 数据流架构图

```mermaid
flowchart LR
    subgraph 输入层
        CXT["🧠 上下文工程"]
        GUIDE["📡 前馈控制"]
        ARCH["🏛️ 架构约束"]
    end

    subgraph 执行层
        AGENT["🤖 AI Agent"]
    end

    subgraph 验证层
        COMP["⚡ 计算型反馈<br/>Linter / 测试"]
        INFER["🤖 推理型反馈<br/>AI Review"]
    end

    subgraph 维护层
        GC["🧹 熵管理Agent"]
        OBS["👁️ 可观测性"]
    end

    subgraph 决策层
        HUMAN["👤 人工审查"]
    end

    CXT --> AGENT
    GUIDE --> AGENT
    ARCH --> AGENT
    AGENT -->|"输出代码"| COMP
    AGENT -->|"输出代码"| INFER
    COMP -->|"通过 ✓"| HUMAN
    COMP -->|"失败 ✗"| AGENT
    INFER -->|"建议修改"| AGENT
    HUMAN -->|"Merge ✅"| GC
    HUMAN -->|"反馈优化"| GUIDE
    GC -->|"定期清扫"| OBS
    OBS -->|"发现问题"| GUIDE

    classDef input fill:#E8F5E9,stroke:#4CAF50,color:#333
    classDef exec fill:#FFEBEE,stroke:#F44336,color:#333
    classDef verify fill:#FFF3E0,stroke:#FF9800,color:#333
    classDef maintain fill:#F3E5F5,stroke:#9C27B0,color:#333
    classDef decide fill:#E3F2FD,stroke:#1976D2,color:#333

    class CXT,GUIDE,ARCH input
    class AGENT exec
    class COMP,INFER verify
    class GC,OBS maintain
    class HUMAN decide
```

---

## 三大支柱详解

```mermaid
graph TD
    HE["🏗️ Harness Engineering"]

    HE --> CE["🧠 上下文工程<br/>Context Engineering"]
    HE --> AC["🏛️ 架构约束<br/>Architectural Constraints"]
    HE --> EM["🧹 熵管理<br/>Entropy Management"]

    CE --> CE1["静态上下文<br/>AGENTS.md / 架构文档"]
    CE --> CE2["动态上下文<br/>目录映射 / CI状态"]
    CE --> CE3["知识库集成<br/>MCP Server"]

    AC --> AC1["分层依赖<br/>Types→Config→Service→UI"]
    AC --> AC2["自定义Linter<br/>自动标记违规"]
    AC --> AC3["结构化测试<br/>边界检查"]
    AC --> AC4["Pre-commit Hooks<br/>提交前拦截"]

    EM --> EM1["文档一致性Agent<br/>文档与代码匹配"]
    EM --> EM2["违规扫描Agent<br/>漏网违规检测"]
    EM --> EM3["模式执行Agent<br/>偏离模式修复"]
    EM --> EM4["依赖审计Agent<br/>循环/无用依赖"]

    classDef root fill:#1976D2,stroke:#0D47A1,color:#fff,stroke-width:2px
    classDef pillar fill:#E3F2FD,stroke:#1976D2,color:#333,stroke-width:2px
    classDef leaf fill:#F5F5F5,stroke:#BDBDBD,color:#333

    class HE root
    class CE,AC,EM pillar
    class CE1,CE2,CE3,AC1,AC2,AC3,AC4,EM1,EM2,EM3,EM4 leaf
```

---

## 一句话总结

> **给信息（上下文）→ 定边界（架构约束）→ 抓错误（反馈回路）→ 清垃圾（熵管理）→ 看全局（可观测性）→ 人兜底（协作层）**
