# Key Concepts
![image.png](https://r2.hecodex.me/obsidian/20250227002300579.png)


（1） **将文本嵌入为向量**：嵌入将文本转换为数字向量表示。

（2） **测量相似性**：可以使用简单的数学运算来比较嵌入向量。


# Historical context
多年来，嵌入模型的前景发生了重大变化。2018 年，当 Google 推出 [BERT（来自 Transformers 的双向编码器表示）](https://www.nvidia.com/en-us/glossary/bert/)时，出现了一个关键时刻。BERT 应用 transformer 模型将文本嵌入为简单的向量表示，从而在各种 NLP 任务中实现前所未有的性能。但是，BERT 并未针对有效生成句子嵌入进行优化。这一限制刺激了 [SBERT （Sentence-BERT）](https://www.sbert.net/examples/training/sts/README.html) 的创建，它调整了 BERT 架构以生成语义丰富的句子嵌入，很容易通过余弦相似度等相似性指标进行比较，大大减少了查找相似句子等任务的计算开销。如今，嵌入模型生态系统是多样化的，许多提供商都提供了自己的实施。为了驾驭这种多样性，研究人员和从业者通常会求助于像 Massive Text Embedding Benchmark （MTEB[） 这样的](https://huggingface.co/blog/mteb)基准进行客观比较。

# LangChain Interface
 `embed_documents`：用于嵌入多个文本（文档）

 `embed_query`：用于嵌入单个文本（查询）
``` python
from langchain_openai import OpenAIEmbeddings
embeddings_model = OpenAIEmbeddings()
embeddings = embeddings_model.embed_documents(
    [
        "Hi there!",
        "Oh, hello!",
        "What's your name?",
        "My friends call me World",
        "Hello World!"
    ]
)
len(embeddings), len(embeddings[0])
(5, 1536)
```

# Measure similarity

每个嵌入(embedding)本质上都是一组坐标，通常在高维空间中。在此空间中，每个点的位置 （嵌入） 反映了其相应文本的含义。就像相似的单词在同义词库中可能彼此靠近一样，相似的概念在此嵌入空间中最终也会彼此靠近。这允许在不同的文本片段之间进行直观的比较。通过将文本简化为这些数字表示形式，我们可以使用简单的数学运算来快速测量两段文本的相似程度，而不管它们的原始长度或结构如何。一些常见的相似性指标包括：

- **余弦相似度**：测量两个向量之间角度的余弦值。
- **欧几里得距离**：测量两点之间的直线距离。
- **点积**：测量一个向量到另一个向量的投影。
