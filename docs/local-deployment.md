# BettaFish 本地化部署指南

本指南介绍如何把 BettaFish（微舆）的全部组件跑在自己的机器上：**不需要任何云端大模型 API Key，也不需要 Tavily / Bocha / Anspire 搜索 API Key**。

## 1. 部署后的组成

| 组件 | 原方案（云端） | 本地化方案 | 容器名 |
|------|----------------|------------|--------|
| 主程序（Flask + 3 个 Streamlit Agent + ForumEngine + ReportEngine） | — | 从本仓库源码构建 | `bettafish` |
| 大模型（7 个 Agent / 角色） | Kimi、Gemini、DeepSeek、Qwen 等云 API | **Ollama**（OpenAI 兼容接口），也可换成 vLLM / LM Studio / Xinference | `bettafish-ollama` |
| 网络搜索（Query Agent） | Tavily | **SearXNG**（自建元搜索，聚合百度 / 360 / 搜狗 / Bing 等） | `bettafish-searxng` |
| 网络搜索（Media Agent） | Bocha / Anspire | **SearXNG** | 同上 |
| 舆情数据库（Insight Agent） | 自备 MySQL / PostgreSQL | **PostgreSQL 15** | `bettafish-db` |
| 情感分析模型 | 首次运行从 HuggingFace 下载 | 下载后缓存在 `./data/hf_cache` | — |

> SearXNG 本身是自建的，但它仍然需要访问外部搜索引擎来获取网页结果；"本地化"指的是不依赖任何第三方付费 API、数据不出你的服务器。

所有运行时数据都在仓库目录的 `./data/` 下（数据库、模型、缓存），已加入 `.gitignore` 与 `.dockerignore`。

## 2. 硬件建议

大模型是资源消耗的主体。默认模型是千问 `qwen3.8:27b`（Ollama 标签，约 18 GB，256K 上下文）：

| 配置 | 说明 |
|------|------|
| 24 GB 以上显存（如 RTX 3090/4090），或 32 GB 以上统一内存的 Apple 芯片 Mac | 推荐，速度与质量都合适 |
| 16 GB 显存 | 显存不够，部分层会放到内存里，速度明显变慢 |
| 只有 CPU | 能跑，但一份完整报告要很久，只适合试用 |

Apple 芯片的 Mac 建议在宿主机原生安装 Ollama，使用 `qwen3.8:27b-mlx`（见第 4 节）。Docker 在 Mac 上无法使用 GPU，容器里的 Ollama 只能用 CPU 运行。

qwen3.8 默认开启思考模式：Ollama 会把思考内容单独返回，本项目也会去掉混进正文的 `<think>` 内容，所以不影响 JSON 解析，只是每次调用会慢一些。需要更快时，可以把 Keyword Optimizer、Forum Host 这类轻量角色换成更小的模型。

**报告生成慢**：Report Agent 每写一个章节，都会把三份引擎报告和整段论坛讨论记录送进模型，论坛记录常有几十万字。本地模型读这么长的输入，单次调用可能要十几分钟，还可能超出上下文。`.env.local.example` 默认设置 `REPORT_FORUM_LOG_MAX_CHARS=30000`，只保留最新的 3 万字讨论；设为 0 则不限制。

Report Agent 对模型能力要求最高。如果最终报告出现图表空白、段落异常，可以单独给 `REPORT_ENGINE_*` 配一个更强的模型（本地或云端都行）。

磁盘：镜像约 10 GB（含 PyTorch 与 Chromium），加上模型文件。

## 3. 快速开始

前置条件：Docker 与 Docker Compose v2.20+（`docker compose version` 查看）。使用 NVIDIA 显卡需另装 [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)，并在 `docker-compose.local.yml` 中取消 `ollama` 服务的 `deploy` 段注释。

```bash
git clone https://github.com/longcheng19771120-ai/BettaFish.git
cd BettaFish

# 1. 生成配置（已预填好本地数据库、Ollama、SearXNG 地址）
cp .env.local.example .env
#    按需修改：LOCAL_LLM_MODEL 与各 *_MODEL_NAME、数据库密码、SEARXNG_SECRET
#    国内网络建议同时修改 PIP_INDEX_URL 和 HF_ENDPOINT（见第 6 节）

# 2. 构建并启动全部服务（首次会构建镜像并自动拉取 LOCAL_LLM_MODEL）
docker compose -f docker-compose.local.yml up -d --build

# 3. 查看模型下载进度，出现 success 即完成
docker compose -f docker-compose.local.yml logs -f ollama-pull
```

启动后：

- 主界面：http://localhost:5000
- SearXNG 调试页面：http://127.0.0.1:8888 （可直接搜索，确认各搜索源可用）
- 数据库：`127.0.0.1:5444`，用户 / 密码 / 库名默认都是 `bettafish`

在主界面点击开始后，系统会自动建表并启动三个 Agent。

### 自检命令

```bash
# 模型是否已就绪（应看到 LOCAL_LLM_MODEL）
docker compose -f docker-compose.local.yml exec ollama ollama list

# SearXNG JSON 接口是否可用（results 不为空即正常）
curl "http://127.0.0.1:8888/search?q=测试&format=json"

# 从 BettaFish 容器内访问模型与搜索
docker compose -f docker-compose.local.yml exec bettafish \
  python -c "import requests;print(requests.get('http://ollama:11434/v1/models').json())"
```

## 4. 使用已有的模型服务

如果宿主机或局域网已经运行了 Ollama / vLLM / LM Studio 等 OpenAI 兼容服务：

1. 在 `.env` 中删除 `COMPOSE_PROFILES=ollama` 这一行（不再启动内置 Ollama 容器）；
2. 把所有 `*_BASE_URL` 改成你的服务地址，并把 `*_MODEL_NAME` 改成该服务中的模型名：

| 服务所在位置 | BASE_URL 示例 |
|--------------|---------------|
| 宿主机 Ollama | `http://host.docker.internal:11434/v1` |
| 宿主机 vLLM | `http://host.docker.internal:8000/v1` |
| 局域网服务器 | `http://192.168.1.20:8000/v1` |

宿主机上的 Ollama 默认只监听 `127.0.0.1`，需要设置 `OLLAMA_HOST=0.0.0.0` 后重启才能被容器访问。

也可以混合使用：例如其余 Agent 用本地模型，只给 `REPORT_ENGINE_*` 填一个云端 API 来提升报告质量。每个 Agent 的 KEY / BASE_URL / MODEL_NAME 都是独立的。

## 5. 准备舆情数据（Insight Agent）

Insight Agent 分析的是本地数据库里的社媒数据，数据库初始为空，需要用 MindSpider 爬虫采集。爬虫需要扫码登录各平台，建议在**宿主机**上运行，并连接 compose 中的数据库：

```bash
git submodule update --init --recursive   # 拉取 MediaCrawler 子模块
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && playwright install chromium

# 让宿主机上的爬虫连接容器中的数据库与模型（环境变量优先于 .env）
export DB_HOST=127.0.0.1 DB_PORT=5444 MINDSPIDER_BASE_URL=http://127.0.0.1:11434/v1

cd MindSpider
python main.py --setup
python main.py --broad-topic                         # 抓取热点话题与关键词
python main.py --deep-sentiment --platforms wb xhs dy  # 按关键词深度爬取（需扫码登录）
```

详细参数见 [MindSpider 使用说明](../MindSpider/README.md)。没有爬取数据时，Query Agent 与 Media Agent 仍可基于网络搜索正常工作。

## 6. 国内网络加速

| 环节 | 配置 |
|------|------|
| pip 依赖（镜像构建） | `.env` 中 `PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` |
| 情感分析模型下载 | `.env` 中 `HF_ENDPOINT=https://hf-mirror.com` |
| Docker 镜像 | 在 Docker 守护进程中配置 registry mirror |
| SearXNG 访问外部搜索引擎需要代理 | 修改 `deploy/searxng/settings.yml` 中 `outgoing.proxies` |

SearXNG 默认启用了百度、360、搜狗、Bing、Bing News、Bing Images 等搜索源。如需增减，编辑 `deploy/searxng/settings.yml` 的 `engines` 段后执行 `docker compose -f docker-compose.local.yml restart searxng`。

## 7. 切换回云端搜索

`SEARCH_TOOL_TYPE` 取值：

| 值 | Query Agent | Media Agent |
|----|-------------|-------------|
| `SearXNG` | SearXNG | SearXNG |
| `AnspireAPI` | Tavily | Anspire |
| `BochaAPI` | Tavily | Bocha |

也可以在 Web 界面的「外部检索工具」配置中直接切换。

## 8. 已知限制

- SearXNG 没有 Bocha 的 AI 总结和"模态卡"（天气、股票等结构化卡片），`search_for_structured_data` 会退化为普通网页搜索。
- SearXNG 不支持任意日期区间，按日期搜索时会先取覆盖起始日期的时间范围，再按发布日期过滤（无发布日期的结果会保留）。
- 本地小模型的报告质量明显低于推荐的云端大模型，若出现 JSON 解析失败或报告结构异常，请先换更大的模型。
- 生成的 HTML 报告通过 CDN 加载图表库，完全断网环境下查看报告时图表可能无法显示。

## 9. 常见问题

**SearXNG 容器启动后反复重启，日志出现 `Address family not supported by protocol`**
机器未启用 IPv6。compose 已通过 `GRANIAN_HOST=0.0.0.0` 处理；如自行部署 SearXNG，请同样设置。

**搜索没有结果，日志中出现 SearXNG 403**
SearXNG 没有开启 JSON 输出。确认 `deploy/searxng/settings.yml` 中 `search.formats` 包含 `json`。

**`curl` 搜索返回的 `unresponsive_engines` 很多**
SearXNG 访问不到对应的搜索引擎，检查服务器网络或配置 `outgoing.proxies`。

**Agent 报 `model not found`**
模型尚未拉取完成，或 `.env` 中的模型名与 `ollama list` 不一致。

**修改 `.env` 后不生效**
`.env` 以文件形式挂载进容器，修改后执行 `docker compose -f docker-compose.local.yml restart bettafish`。
