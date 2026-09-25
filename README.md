# 三模型分工协作的 LLM 智能路由系统

输入一个自然语言问题，系统自动判断它属于哪个领域，分发给最擅长的模型作答；也支持三模型圆桌会诊（实时直播辩论 + 主持人总结）、以及客观题的举手表决。支持多会话管理与历史记录持久化，关闭重开不丢。

接入的三家（均为 OpenAI 兼容接口）：

| 模型 | API 提供方 | 擅长领域（路由依据） |
|---|---|---|
| DeepSeek（deepseek-chat） | DeepSeek 官方 | 代码、数学、逻辑推理 |
| GLM（glm-4-flash） | 智谱 BigModel | 中文写作、文案、办公场景 |
| Kimi（kimi-k2.7-code-highspeed） | 月之暗面 Moonshot | 通用对话、长文理解、多语言 |

---

## 一、架构

```
                          ┌──────────────────────────┐
                          │        app.py (CLI)       │
                          │  python app.py "问题"      │
                          └─────────────┬────────────┘
                                        │ 按 mode 分发
             ┌──────────────────────────┼─────────────────────────┐
             ▼                          ▼                         ▼
       route 模式(默认)             all 模式                    vote 模式
       智能路由                    圆桌会诊                   举手表决
             │                          │                         │
             ▼                          └────────────┬────────────┘
      ┌─────────────┐                                │
      │  router.py   │  GLM 分类 + 关键词兜底          │ 三路并行
      │  分类 & 路由  │◄───────────────────────────────┘
      └──────┬──────┘
             │ 选中 1 个（或 3 个）
             ▼
      ┌─────────────┐          ┌──────────────────┐
      │  client.py   │◄─────────│    config.py      │
      │ OpenAI 兼容   │  httpx   │  MODELS + .env   │
      └──────┬──────┘          └──────────────────┘
             │
     ┌───────┼────────┬──────────┐
     ▼       ▼        ▼          ▼
  DeepSeek   GLM      Kimi      （三家 OpenAI 兼容 API）
  代码/数学  中文写作  通用/长文
```

目录结构：

```
三模型路由系统/
├── app.py          # CLI 入口
├── server.py       # FastAPI 服务（网页窗口 + API）
├── 三模型路由系统.html   # 网页窗口前端（由服务托管，勿直接双击打开）
├── 双击打开三ai 系统.command   # 双击启动窗口（macOS）
├── config.py       # 模型注册表 + .env 加载 + 标签映射
├── client.py       # OpenAI 兼容客户端（同步/异步/流式）
├── router.py       # 分类与路由（GLM 分类 + 关键词兜底）
├── modes.py        # 三种模式逻辑
├── council.py      # 圆桌会诊（三轮讨论 + SSE 事件流）
├── sessions.py     # 多会话存储与历史记录（持久化 .sessions.json）
├── history.py      # 本地日志（logs/history.jsonl）
├── test_smoke.py   # 冒烟测试（无需真实 key）
├── .env.example    # key 模板
└── README.md
```

---

## 二、安装依赖

需要 Python 3.10+。安装依赖：

```bash
pip install httpx python-dotenv fastapi uvicorn
```

> 若直连 PyPI 速度慢或安装被中断，可换阿里云镜像：
> `pip install -i https://mirrors.aliyun.com/pypi/simple httpx python-dotenv fastapi uvicorn`

依赖说明：核心运行只需 `httpx`（HTTP/流式/异步）与 `python-dotenv`（.env 解析）；`fastapi` + `uvicorn` 仅 `server.py` 需要，不跑服务可跳过。

---

## 三、配置 key

```bash
cp .env.example .env
# 编辑 .env，填入真实 key（至少填一个即可运行）
```

| 环境变量 | 对应模型 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek |
| `ZHIPU_API_KEY` | GLM |
| `MOONSHOT_API_KEY` | Kimi |

`.env` 已加入 `.gitignore`，不会误提交。

---

## 四、用法示例

```bash
# 1. 智能路由（默认）——自动判领域并选模型
python3 app.py "帮我用Python写一个快速排序"        # → 路由到 DeepSeek

# 2. 中文写作 → 路由到 GLM
python3 app.py "帮我写一条小红书风格的奶茶店开业文案"

# 3. 圆桌会诊 + DeepSeek 综合点评
python3 app.py --mode all "量子计算和经典计算的本质区别是什么"

# 4. 举手表决（客观题）
python3 app.py --mode vote "以下哪个是质数：A. 4  B. 9  C. 17  D. 21"

# 5. 强制指定模型
python3 app.py --model kimi "翻译成英文：今天天气不错"

# 6. 流式输出（路由模式）
python3 app.py --stream "写一个二分查找的Python实现"
```

每次回答末尾都会打印一行统计：

```
[DeepSeek] 耗时 3.42s | 输入 12 tokens | 输出 189 tokens
```

### 网页窗口（图形界面）

**方式一：双击启动（最简单）**

在访达里双击项目目录下的 `双击打开三ai 系统.command`，会自动启动服务并打开浏览器。首次双击若被 macOS 拦截，右键该文件 → 「打开」。

**方式二：手动命令**

```bash
python3 -m uvicorn server:app --host 127.0.0.1 --port 8000
```

然后浏览器打开 **http://127.0.0.1:8000**。

窗口里可以直接点右上角「⚙ 设置」填入三个 API key，点保存即写入 `.env`、立即生效（无需重启）；无需手动编辑 `.env`。界面支持三种模式：智能路由 / 圆桌会诊 / 举手表决，左侧边栏支持**多会话**——可新建、切换、删除会话，历史记录自动持久化，关闭重开不丢。

> 服务默认只监听 `127.0.0.1`（本机），不会把 key 暴露到局域网。

### API 接口（供二次开发）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 网页窗口 |
| GET | `/config` | 查询各模型 key 是否已配置 |
| POST | `/config` | 保存 key（body: `{"deepseek":"...","glm":"...","kimi":"..."}`） |
| GET | `/sessions` | 会话列表 |
| POST | `/sessions/new` | 新建会话 |
| GET | `/sessions/{id}` | 某会话完整历史 |
| POST | `/sessions/{id}/delete` | 删除某会话 |
| POST | `/ask` | 提问（body: `{"question":"...","mode":"route|vote","session_id":"..."}`） |
| POST | `/ask/stream` | 圆桌会诊（SSE 实时推送，body 同上） |
| GET | `/health` | 健康检查 |

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"帮我写个快排","mode":"route","session_id":"<会话id>"}'
```

---

## 五、如何更换 / 新增模型

所有模型相关配置集中在 `config.py` 的 `MODELS` 注册表里，新增一个模型只需两步：

1. 在 `MODELS` 加一条：

```python
"newmodel": {
    "name": "newmodel",
    "label": "NewModel",              # 展示名
    "base_url": "https://api.example.com/v1",
    "model": "example-model-id",
    "api_key_env": "EXAMPLE_API_KEY", # 对应的 .env 变量
    "description": "擅长领域描述",
}
```

2. 在 `MODEL_KEYS` 里加它的 key（该常量由 `MODELS.keys()` 自动生成，一般无需手动改），并按需在 `router.py` 的 `LABEL_TO_MODEL` 中把某个路由标签指向它。

> 只要该 provider 提供 OpenAI 兼容的 `/chat/completions` 接口，`client.py` 无需任何改动。

---

## 六、测试

无需真实 key，仅验证路由逻辑与解析（mock 分类结果）：

```bash
python3 test_smoke.py
```

覆盖：标签解析（纯标签 / JSON / 引号 / 夹杂文字）、关键词分类、标签→模型映射、无分类器时的兜底、GLM 分类可用/失败、解析失败重试一次。

---

## 七、日志

每次请求追加一条 JSON 到 `logs/history.jsonl`，含：时间戳、问题、模式、路由标签与来源、选中/实际使用模型、耗时、token 用量等，便于后续分析。

---

## 八、设计决策说明（需求未覆盖处的合理取舍）

1. **分类器温度**：路由分类与单模型作答用 `temperature=0.0`（追求确定性），综合点评用 `0.3`。
2. **token 统计**：非流式优先用 API 返回的 `usage` 字段；流式（部分 provider 不返回 usage）用字符估算兜底——CJK 1 字 ≈ 1 token，其余约 4 字符 ≈ 1 token。
3. **综合点评降级**：规格要求用 DeepSeek 点评；若 DeepSeek 缺 key，自动改用任意可用模型并提示。
4. **表决结论提取**：优先匹配模型输出中「最终答案：XXX」这一行，找不到则退回最后一行非空文本；多数票 = 票数严格过半，否则输出分歧详情；置信度 = 多数票数 / 有效票数。
5. **降级顺序**：路由选中模型不可用时，按 `MODEL_KEYS` 剩余顺序依次尝试；三个模型都不可用才报错。填错 key（请求返回 401 等）会在调用阶段捕获并降级，且明确打印降级原因。
6. **日志模块**：规格列出的文件之外新增了 `history.py`，把日志逻辑独立出来保持 `modes.py` 干净。
7. **超时**：请求超时 120s（连接超时 20s）。
8. **server.py**：提供网页窗口（`三模型路由系统.html`）+ JSON API，`POST /ask` 复用三种模式函数；默认只监听 `127.0.0.1`，避免 key 暴露到局域网。
9. **网页配 key**：窗口里保存的 key 写入本地 `.env`（明文），并同步到当前进程环境变量、立即生效；`GET /config` 只返回「是否已配置」的布尔值，不返回 key 明文。

## 九、验收对照

1. `app.py "帮我用Python写一个快速排序"` → 分类 `code_math` → 路由 DeepSeek 流式输出代码。✅
2. `app.py "帮我写一条小红书风格的奶茶店开业文案"` → 分类 `chinese_writing` → 路由 GLM。✅
3. `app.py --mode all "量子计算和经典计算的本质区别是什么"` → 三模型并行 + DeepSeek 综合点评。✅
4. 故意填错一个 key → 调用失败自动降级到可用模型并明确提示。✅

## 圆桌会诊（网页模式）

「圆桌会诊」为**默认模式**。选择后前端通过 `POST /ask/stream`（SSE）实时观看三轮讨论：

1. **各自亮观点**：三模型并行作答，各限 150 字；
2. **互评与修正**：互相可见首轮观点，指出分歧或公开修正立场；
3. **主持人总结**：DeepSeek（缺失时降级）融合三方观点，输出【共识与分歧】+ 一份完整可用的【最终答案】。

过程逐字直播，无黑盒等待；讨论结束自动折叠前两轮、只留总结卡，点「查看辩论过程」可展开回看全程；讨论中可随时点「停止」中断（后端会同步取消模型调用，省 token）。

---

## 十、开源许可与安全提示

### 许可证

本项目采用 [MIT License](LICENSE) 开源，可自由使用、修改、分发（需保留版权声明）。

### 安全提示

- **API Key 属于敏感信息**：你的 key 只存在本地 `.env`，该文件已加入 `.gitignore`，不会被提交；`GET /config` 也只返回「是否已配置」的布尔值，不返回 key 明文。
- 调用大模型会产生费用，费用由各模型服务商按用量收取，与本项目无关。
- 服务默认只监听 `127.0.0.1`，请勿改绑 `0.0.0.0`，以免把 key 暴露到局域网 / 公网。

### 贡献

欢迎提 Issue / PR。更换或新增模型只需改 `config.py` 的 `MODELS` 注册表（见「五、如何更换/新增模型」）。
