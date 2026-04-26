# douyin-mcp-server 深度技术解析
# 地址
[douyin-mcp-server](https://github.com/yzfly/douyin-mcp-server?tab=readme-ov-file)

## 目录

- [项目概述](#项目概述)
- [技术架构](#技术架构)
- [核心模块解析](#核心模块解析)
- [关键技术实现](#关键技术实现)
- [WebUI 技术详解](#webui-技术详解)
- [数据流程分析](#数据流程分析)
- [技术亮点](#技术亮点)
- [潜在优化方向](#潜在优化方向)
- [总结](#总结)

---

## 项目概述

**douyin-mcp-server** 是一个基于 Python 的短视频文案提取工具，通过三种使用方式为用户提供服务：

| 使用方式 | 目标用户 | 技术特点 |
|---------|---------|---------|
| **WebUI** | 普通用户 | FastAPI + Alpine.js，浏览器操作 |
| **MCP Server** | Claude Desktop 用户 | FastMCP 协议集成 |
| **命令行工具** | 开发者 | argparse，支持批量处理 |

### 核心功能

- **无水印视频下载** - 解析抖音分享链接，获取原始视频下载地址
- **AI 语音识别** - 使用硅基流动 SenseVoice API 自动提取视频文案
- **大文件智能分段** - 自动处理超过 1 小时或 50MB 的音频文件
- **多入口访问** - 统一核心逻辑，支持多种使用场景

---

## 技术架构

### 整体分层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户入口层                               │
├──────────────┬──────────────┬───────────────────────────────────┤
│  WebUI       │  MCP Server  │  命令行工具                        │
│  (FastAPI)   │  (FastMCP)   │  (argparse)                       │
└──────┬───────┴──────┬───────┴───────────────────────────────────┘
       │              │
       └──────┬───────┴────────────────┐
              ▼                        ▼
    ┌─────────────────────────────────────────┐
    │        DouyinProcessor 核心处理类         │
    ├─────────────────────────────────────────┤
    │  • parse_share_url()   解析分享链接      │
    │  • download_video()    下载视频          │
    │  • extract_audio()     提取音频          │
    │  • split_audio()       音频分段          │
    │  • transcribe_single() 单段转录          │
    └─────────────────────────────────────────┘
              │
              ▼
    ┌─────────────────────────────────────────┐
    │            外部服务层                    │
    ├─────────────────────────────────────────┤
    │  • 抖音视频服务         HTTP 请求         │
    │  • FFmpeg              音视频处理        │
    │  • 硅基流动 API         AI 语音识别       │
    └─────────────────────────────────────────┘
```

### 技术栈总览

| 层级 | 技术选型 | 版本要求 | 用途 |
|------|---------|---------|------|
| **运行环境** | Python | 3.10+ | 核心开发语言 |
| **Web 框架** | FastAPI + Uvicorn | - | 高性能异步 Web 服务 |
| **MCP 协议** | FastMCP | 1.0.0+ | Claude Desktop 集成 |
| **前端** | Alpine.js + Tailwind CSS | 3.x | 轻量级响应式 UI |
| **模板引擎** | Jinja2 | - | HTML 模板渲染 |
| **音视频处理** | ffmpeg-python | - | 音频提取与分割 |
| **AI 语音识别** | 硅基流动 SenseVoice | - | ASR 转录服务 |
| **HTTP 客户端** | requests | - | 流式下载 |
| **包管理** | uv | - | Python 依赖管理 |

---

## 核心模块解析

### 1. DouyinProcessor 核心类

所有功能的核心处理类，负责视频信息的解析、下载、音频处理等操作。

```python
class DouyinProcessor:
    def __init__(self, api_key: str = "", api_base_url: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key
        self.api_base_url = api_base_url or DEFAULT_API_BASE_URL
        self.model = model or DEFAULT_MODEL
        self.temp_dir = Path(tempfile.mkdtemp())  # 临时目录管理
```

**设计亮点：**
- 使用 `tempfile.mkdtemp()` 创建独立临时目录
- `__del__` 方法自动清理临时文件，防止磁盘占用
- 支持自定义 API 端点和模型，便于扩展

### 2. 链接解析模块

#### 核心原理

抖音视频的元数据直接嵌入在 HTML 页面中，通过正则表达式提取：

```python
pattern = re.compile(
    pattern=r"window\._ROUTER_DATA\s*=\s*(.*?)</script>",
    flags=re.DOTALL,
)
find_res = pattern.search(response.text)
json_data = json.loads(find_res.group(1).strip())
```

#### 解析流程

```python
# 1. 从分享文本中提取 URL
urls = re.findall(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', share_text)

# 2. 访问分享链接获取重定向后的 video_id
share_response = requests.get(share_url, headers=HEADERS)
video_id = share_response.url.split("?")[0].strip("/").split("/")[-1]

# 3. 构造视频页面 URL
share_url = f'https://www.iesdouyin.com/share/video/{video_id}'

# 4. 获取页面内容并解析 JSON
response = requests.get(share_url, headers=HEADERS)

# 5. 从 JSON 中提取视频信息
data = json_data["loaderData"]["video_(id)/page"]["videoInfoRes"]["item_list"][0]

# 6. 获取无水印链接（关键步骤）
video_url = data["video"]["play_addr"]["url_list"][0].replace("playwm", "play")
```

**关键技术点：**
- 模拟移动端 User-Agent 绕过某些检测
- 将 `playwm` 替换为 `play` 获取无水印链接
- 支持视频和图集两种类型的解析

### 3. 音频处理模块

#### 音频提取

使用 FFmpeg 从视频中提取高质量音频：

```python
def extract_audio(self, video_path: Path) -> Path:
    audio_path = video_path.with_suffix('.mp3')
    (
        ffmpeg
        .input(str(video_path))
        .output(str(audio_path), acodec='libmp3lame', q=0)  # q=0 最高质量
        .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
    )
    return audio_path
```

#### 智能分段处理

```python
def split_audio(self, audio_path: Path, segment_duration: int = 600) -> list:
    """
    将音频分割成多个片段
    参数:
        segment_duration: 每段时长（秒），默认 10 分钟
    """
    audio_info = self.get_audio_info(audio_path)
    duration = audio_info['duration']

    segments = []
    segment_index = 0
    current_time = 0

    while current_time < duration:
        segment_path = self.temp_dir / f"segment_{segment_index}.mp3"
        (
            ffmpeg
            .input(str(audio_path), ss=current_time, t=segment_duration)
            .output(str(segment_path), acodec='libmp3lame', q=0)
            .run(capture_stdout=True, capture_stderr=True, overwrite_output=True)
        )
        segments.append(segment_path)
        current_time += segment_duration
        segment_index += 1

    return segments
```

**分段策略：**
- API 限制：1 小时 / 50MB
- 项目采用 9 分钟（540 秒）分段，留有安全余量
- 自动检测音频信息，仅超限时才执行分段

### 4. AI 语音识别模块

#### 单文件转录

```python
def transcribe_single_audio(self, audio_path: Path) -> str:
    files = {
        'file': (audio_path.name, open(audio_path, 'rb'), 'audio/mpeg'),
        'model': (None, self.model)
    }
    headers = {
        "Authorization": f"Bearer {self.api_key}"
    }
    response = requests.post(self.api_base_url, files=files, headers=headers)
    result = response.json()
    return result['text']
```

#### 大文件处理流程

```python
def extract_text_from_audio(self, audio_path: Path) -> str:
    # 1. 检查文件大小和时长
    audio_info = self.get_audio_info(audio_path)
    max_duration = 3600  # 1 小时
    max_size = 50 * 1024 * 1024  # 50MB

    # 2. 判断是否需要分段
    need_split = audio_info['duration'] > max_duration or audio_info['size'] > max_size

    if not need_split:
        return self.transcribe_single_audio(audio_path)

    # 3. 分段处理
    segments = self.split_audio(audio_path, segment_duration=540)

    # 4. 逐段转录
    all_texts = []
    for i, segment_path in enumerate(segments):
        text = self.transcribe_single_audio(segment_path)
        all_texts.append(text)
        self.cleanup_files(segment_path)  # 清理分段文件

    # 5. 合并结果
    return ''.join(all_texts)
```

---

## 关键技术实现

### 1. 流式视频下载

```python
def download_video(self, video_info: dict, output_dir: Optional[Path] = None) -> Path:
    response = requests.get(video_info['url'], headers=HEADERS, stream=True)
    total_size = int(response.headers.get('content-length', 0))

    with open(filepath, 'wb') as f:
        downloaded = 0
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if total_size > 0:
                    progress = downloaded / total_size * 100
                    print(f"\r下载进度: {progress:.1f}%", end="", flush=True)
```

**技术要点：**
- `stream=True` 启用流式下载，避免大文件内存溢出
- `chunk_size=8192` 平衡 I/O 效率
- 实时显示下载进度，提升用户体验

### 2. 请求头伪装

```python
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1'
}
```

模拟移动端访问，获取移动端专属的视频链接（通常质量更高且无水印）。

### 3. 临时文件管理

```python
def __del__(self):
    """清理临时目录"""
    if hasattr(self, 'temp_dir') and self.temp_dir.exists():
        shutil.rmtree(self.temp_dir, ignore_errors=True)
```

使用 Python 析构函数自动清理，无需手动管理临时文件。

---

## WebUI 技术详解

### 前端架构

```html
<!-- CDN 引入，无需构建工具 -->
<script src="https://cdn.tailwindcss.com"></script>
<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
```

**技术选型理由：**
- **Alpine.js** - 仅 ~15KB，提供 Vue/React 式的响应式体验
- **Tailwind CSS** - 实用优先，无需编写自定义 CSS
- **无构建流程** - 直接打开 HTML 即可使用

### API 设计

```
POST /api/video/info
    功能：获取视频信息（无需 API Key）
    请求体：{"url": "分享链接"}
    响应：{"success": true, "video_id": "", "title": "", "download_url": ""}

POST /api/video/extract
    功能：提取视频文案
    请求体：{"url": "分享链接", "api_key": "sk-xxx"}
    响应：{"success": true, "video_id": "", "title": "", "text": "", "download_url": ""}

GET /api/video/download?url=xxx&filename=xxx
    功能：代理下载视频（解决跨域和请求头问题）
    响应：video/mp4 流式响应

GET /api/health
    功能：健康检查
    响应：{"status": "ok", "api_key_configured": true}
```

### 代理下载实现

```python
@app.get("/api/video/download")
async def download_video(url: str, filename: str = "video.mp4"):
    download_headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 ...',
        'Referer': 'https://www.douyin.com/',
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'identity',
        'Connection': 'keep-alive',
    }

    response = requests.get(url, headers=download_headers, stream=True)

    def iter_content():
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                yield chunk

    return StreamingResponse(
        iter_content(),
        media_type="video/mp4",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
```

**解决的核心问题：**
1. **跨域限制** - 浏览器无法直接请求抖音服务器
2. **请求头限制** - 浏览器无法自定义 Referer 等关键请求头
3. **流式传输** - 使用 `StreamingResponse` 避免服务器内存溢出

### API Key 管理

```javascript
// 浏览器本地存储
localStorage.setItem('douyin_api_key', apiKey);

// 请求时携带
const response = await fetch('/api/video/extract', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
        url: videoUrl,
        api_key: localStorage.getItem('douyin_api_key') || ''
    })
});
```

**设计考虑：**
- 优先使用前端传入的 API Key
- 回退到环境变量中的 API Key
- 浏览器本地存储，刷新页面不丢失

---

## 数据流程分析

### 完整处理流程

```
┌─────────────┐
│ 抖音分享链接 │
└──────┬──────┘
       │ 1. 正则提取 URL
       ▼
┌─────────────────────────┐
│  访问分享链接            │
│  获取重定向后的 video_id │
└──────┬──────────────────┘
       │ 2. 构造视频页面 URL
       ▼
┌─────────────────────────┐
│  解析 HTML              │
│  提取 window._ROUTER_DATA│
└──────┬──────────────────┘
       │ 3. 解析 JSON 数据
       ▼
┌─────────────────────────┐
│  获取无水印链接          │
│  playwm → play          │
└──────┬──────────────────┘
       │ 4. 流式下载视频
       ▼
┌─────────────────────────┐
│  FFmpeg 提取音频         │
│  video.mp4 → audio.mp3   │
└──────┬──────────────────┘
       │ 5. 检查文件信息
       ▼
┌─────────────────────────┐
│  判断是否超过限制        │
│  (1h / 50MB)            │
└──────┬──────────────────┘
       │
   ┌───┴────┐
   │        │
   ▼        ▼
┌──────┐  ┌─────────────────┐
│ 直接 │  │ FFmpeg 分段     │
│ 转录 │  │ (9分钟/段)      │
└──┬───┘  └────────┬────────┘
   │               │
   │        ┌──────┴────────┐
   │        │ 逐段调用 API   │
   │        │ 转录          │
   │        └──────┬────────┘
   │               │
   └───────┬───────┘
           ▼
┌─────────────────────────┐
│  合并文本结果           │
└──────┬──────────────────┘
       │ 6. 保存文件
       ▼
┌─────────────────────────┐
│  Markdown 格式输出       │
│  transcript.md          │
└─────────────────────────┘
```

### MCP 调用示例

```json
// Claude Desktop 配置
{
  "mcpServers": {
    "douyin-mcp": {
      "command": "uvx",
      "args": ["douyin-mcp-server"],
      "env": {
        "API_KEY": "sk-xxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

```text
用户: 帮我提取这个视频的文案 https://v.douyin.com/xxxxx/

Claude: 我来帮你提取视频文案...
[调用 extract_douyin_text 工具]
解析抖音分享链接...
正在从视频中提取文本...
文本提取完成!

提取完成，文案内容如下：
[视频文案内容]
```

---

## 技术亮点

### 1. 零依赖解析

无需抖音官方 API，纯 HTML 解析实现：

- 模拟移动端访问
- 从嵌入的 JSON 数据中提取信息
- 简单的字符串替换获取无水印链接

### 2. 智能分段处理

自动检测并处理大文件：

```python
audio_info = self.get_audio_info(audio_path)
need_split = audio_info['duration'] > 3600 or audio_info['size'] > 50 * 1024 * 1024
```

- 检测音频时长和文件大小
- 自动判断是否需要分段
- 分段转录后自动合并结果

### 3. 流式下载

```python
response = requests.get(url, headers=HEADERS, stream=True)
for chunk in response.iter_content(chunk_size=8192):
    f.write(chunk)
```

- 避免大文件内存溢出
- 实时显示下载进度
- 支持进度条展示

### 4. 多入口设计

```
核心处理逻辑 (DouyinProcessor)
        │
    ┌───┼────────────┐
    ▼   ▼            ▼
  CLI  WebUI        MCP
```

- 统一的核心处理类
- 不同的入口适配各自的交互模式
- 代码复用率高，维护成本低

### 5. 临时目录自动管理

```python
def __del__(self):
    shutil.rmtree(self.temp_dir, ignore_errors=True)
```

- 自动清理临时文件
- 防止磁盘空间泄漏
- 用户无需手动干预

---

## 潜在优化方向

### 1. API 兼容性

**现状：** 硬编码硅基流动 API

**建议：** 抽象 ASR 接口

```python
class ASRProvider(Protocol):
    def transcribe(self, audio_path: Path) -> str: ...

class SiliconFlowASR:
    def transcribe(self, audio_path: Path) -> str: ...

class AliyunASR:
    def transcribe(self, audio_path: Path) -> str: ...
```

### 2. HTML 解析鲁棒性

**现状：** 使用正则表达式解析，容易因页面结构变化而失效

**建议：** 使用 BeautifulSoup

```python
from bs4 import BeautifulSoup

soup = BeautifulSoup(response.text, 'html.parser')
script_tag = soup.find('script', string=re.compile('window._ROUTER_DATA'))
```

### 3. 并发处理

**现状：** 同步下载和处理

**建议：** 使用 asyncio 或多线程

```python
async def download_multiple_videos(urls: List[str]):
    tasks = [download_video(url) for url in urls]
    return await asyncio.gather(*tasks)
```

### 4. 缓存机制

**现状：** 无缓存，重复请求浪费资源

**建议：** 添加 Redis 或本地缓存

```python
@lru_cache(maxsize=1000)
def parse_share_url(share_text: str) -> dict:
    # 先查缓存，未命中再请求
    ...
```

### 5. 错误处理增强

**现状：** 基础的异常捕获

**建议：** 添加重试机制和详细日志

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def transcribe_with_retry(self, audio_path: Path) -> str:
    return self.transcribe_single_audio(audio_path)
```

### 6. Docker 化部署

**现状：** 需要手动安装依赖

**建议：** 提供 Docker 镜像

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y ffmpeg
COPY . /app
RUN pip install -e .
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8080"]
```

---

## 总结

**douyin-mcp-server** 是一个设计精巧的短视频文案提取工具，具有以下特点：

### 核心优势

1. **技术选型务实** - Alpine.js + Tailwind CSS 无需构建，FastAPI 高性能异步
2. **架构设计清晰** - 核心逻辑与入口分离，易于维护和扩展
3. **用户体验友好** - 流式下载、进度显示、智能分段
4. **多入口支持** - CLI、WebUI、MCP 三种方式满足不同用户需求

### 适用场景

- 内容创作者快速提取视频文案
- 开发者批量处理短视频
- AI 应用（如 Claude Desktop）集成视频解析能力

### 技术价值

- 展示了 MCP 协议的实际应用
- 提供了短视频解析的完整解决方案
- 可作为类似项目的参考架构

---

**作者：** yzfly
**项目地址：** https://github.com/yzfly/douyin-mcp-server
**许可证：** Apache License 2.0 / MIT

# 实践
!![[Pasted image 20260227223402.webp]]