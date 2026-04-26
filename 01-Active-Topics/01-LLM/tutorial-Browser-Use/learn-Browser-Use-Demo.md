# 参考文档
Browser Use Doc:https://docs.browser-use.com/customize/system-prompt

# Browser Use Quickstart

## Prepare the environment

```shell
uv venv --python 3.11

# For Mac/Linux:
source .venv/bin/activate

# For Windows:
.venv\Scripts\activate

# 也可以直接 pip
uv pip install browser-use

# 安装 playwright
playwright install

```

## Create Agent
Create a Agent use DeepSeek
```python
from langchain_openai import ChatOpenAI  
from browser_use import Agent  
from pydantic import SecretStr  
import asyncio  
  
# Initialize the model  
llm=ChatOpenAI(base_url='https://api.deepseek.com/v1', model='deepseek-chat', api_key=SecretStr('api_key'))  
  
# Create agent with the model  
  
  
async def main():  
    agent = Agent(  
    task="Compare the difference of RAG and Agent",  
    llm=llm,  
    use_vision=False  
    )  
  
    result = await agent.run()  
    print(result)  
  
asyncio.run(main())
```

## Run Agent

![image.png](https://r2.hecodex.me/obsidian/20250311233652199.png)

![image.png](https://r2.hecodex.me/obsidian/20250311233822408.png)

## Questioin Result

The differences between RAG and Agent are as follows:
1. RAG combines retrieval-based methods with generation-based methods to produce accurate, contextually relevant responses. AI Agents focus on interaction, decision-making, and task execution.
2. RAG systems focus on gathering and generating information, while AI Agents are designed to interact, make decisions, and perform tasks.
3. RAG enhances text generation through retrieval, while AI Agents bring autonomy and decision-making to AI systems.
4. RAG focuses on augmenting LLMs with external knowledge, while AI Agents empower LLMs to interact with the world through actions and tools.
5. RAG chatbots are ideal for knowledge base responses, while AI Agents are better for decision-making and task execution.
6. RAG retrieves information from live sources, while AI Agents interact with users and perform tasks like booking.
7. AI Agents are purpose-built for real-world interaction, perceiving their environment and taking actions, unlike LLMs and RAG models.
8. RAG and Agents are distinct but related approaches used to enhance the capabilities and outputs of large language models (LLMs).
9. Traditional RAG suits basic Q&A and research, while Agentic RAG excels in dynamic, data-intensive applications like real-time analysis and enterprise systems.
