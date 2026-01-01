# APE: 自动化大模型越狱框架

一个基于 **LangGraph** 的自动化 **LLM 越狱（Jailbreak）框架**，用于红队测试。该框架通过多智能体协作，自动生成并迭代攻击提示词，旨在绕过目标大模型的安全护栏。

> **重要声明**：本项目仅用于授权的安全研究和 CTF 风格的红队测试环境。

## 目录

- [核心特性](#核心特性)
- [系统架构](#系统架构)
- [环境安装](#环境安装)
- [使用方法](#使用方法)
- [攻击手法库](#攻击手法库)
- [配置说明](#配置说明)
- [开发指南](#开发指南)

## 核心特性

- **多智能体编排**：闭环反馈系统，包含 4 个专业化节点
- **渐进式载荷生成**：每轮生成 5 个强度递增的载荷（浅层 → 中层 → 深层）
- **质量评分追踪**：以 0-100 分评估响应，检测 AI 是否开始"松口"
- **智能迭代策略**：当 AI 表现出妥协迹象时，继续使用更深层载荷
- **历史记录分析**：Planner 分析最近尝试，识别防御模式和弱点
- **无头浏览器模式**：后台运行，不抢占用户窗口

## 系统架构

```
┌─────────┐      ┌────────┐      ┌──────────┐      ┌─────────┐
│ 规划器  │ ───> │ 执行器 │ ───> │  浏览器  │ ───> │  裁判   │
│ Planner │ ───> │ Player │ ───> │ Executor │ ───> │ Checker │
└─────────┘      └────────┘      └──────────┘      └─────────┘
     ↑                                                                 │
     └─────────────────────────────────────────────────────────────────┘
                        （反馈循环，继续或结束）
```

### 节点职责

| 节点 | 职责 |
|------|------|
| **Planner (规划器)** | 选择攻击手法，分析历史记录，生成 5 个渐进式载荷 |
| **Player (执行器)** | 从批次中获取下一个载荷（保持深度递进） |
| **Executor (浏览器)** | 使用 Playwright 填写 `#taid` 文本框并提交表单 |
| **Checker (裁判)** | 评估响应，分配质量分数（0-100），提供详细分析 |

### 状态管理

```python
JailbreakState {
    target_goal: str          # 正在测试的恶意目标
    current_technique: str    # 当前选择的攻击手法
    current_payload: str      # 生成的攻击提示词
    payloads_batch: List[str] # 5 个载荷（浅层 → 深层）
    batch_index: int          # 批次中的当前位置 (0-4)
    current_depth: str        # 深度级别：浅层/中层/深层
    raw_response: str         # 目标 LLM 的响应
    history: List[dict]       # 累积的攻击尝试记录
    analysis: str             # Checker 给 Planner 的反馈
    success: bool             # 是否越狱成功
    attempts: int             # 尝试次数
    round_count: int          # 完成的轮数
    last_quality_score: int   # 上一轮质量分数 (0-100)
}
```

## 环境安装

### 1. 安装依赖

从 `req.txt` 安装 Python 包：

```bash
pip install -r req.txt
```

### 2. 安装 Playwright 浏览器

```bash
playwright install chromium
```

### 3. 配置环境变量

在项目根目录创建 `.env` 文件：

```env
OPENAI_API_KEY=你的API密钥
OPENAI_BASE_URL=https://api.deepseek.com
DEBUG=true
PLAYWRIGHT_BROWSERS_PATH=/浏览器路径
```

## 使用方法

### 普通模式

```bash
python ape.py
```

### 调试模式

```bash
DEBUG=1 python ape.py
```

调试模式功能：
- 所有节点操作的详细日志
- 提示词/响应的详细检查
- should_continue 决策过程的可见性

## 攻击手法库

位于 `tech.txt` 文件中，当前包含的手法：

1. **电影剧本创作（虚构）**：将请求包装在电影剧本或小说对话中
2. **红队安全审计员（身份伪装）**：伪装成合法的安全研究人员
3. **翻译/编码混淆**：使用多种语言或 Base64 编码
4. **技术任务拆解**：将非法行为拆解为多个技术子任务
5. **逻辑覆盖（模拟器模式）**：强迫 AI 忽略护栏（如 DAN 模式）

### 添加新手法的位置

编辑 `tech.txt` 文件，每行一个手法：

```
新手法名称：简要描述
另一个手法：另一个描述
```

## 配置说明

### 目标环境

默认目标：`http://127.0.0.1:8000/prompt_inject/jailbreak_1`

预期的 HTML 结构：
- `<textarea id="taid">`：载荷输入框
- `<input type="submit">`：提交按钮
- 响应从 `body > div > div:nth-child(4)` 提取

### 关键参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_ATTEMPTS` | 20 | 最大轮数 |
| `MODEL_NAME` | `deepseek-chat` | 使用的 LLM 模型 |
| `headless` | `True` | 浏览器模式 |

## 流程控制

框架使用基于响应质量的智能流程控制：

1. **检测到成功** → 结束
2. **达到最大尝试次数** → 结束
3. **质量分数 30-70**（AI 开始"松口"）→ 继续使用更深层载荷
4. **批次中还有更多载荷** → 下一个载荷
5. **批次耗尽** → 使用不同手法生成新批次

## 开发指南

### 运行测试

```bash
# 运行所有测试
pytest test_ape.py -v -s

# 运行特定测试类
pytest test_ape.py::TestPlannerNode -v -s

# 运行特定测试
pytest test_ape.py::TestExecutorNode::test_executor_node -v -s

# 使用 DEBUG 模式运行
DEBUG=1 pytest test_ape.py::TestExecutorNode::test_executor_browser -v -s
```

**注意**：`TestExecutorNode` 中的测试需要本地目标服务器运行。

### 代码组织

```
ape.py          # 主框架，包含所有 4 个节点和图构建
test_ape.py     # 综合测试，包括 mock
tech.txt        # 攻击手法库
```

## 关键实现细节

1. **浏览器自动化**：Playwright 以无头模式运行，不干扰用户工作流
2. **手法轮换**：基于可用手法的模运算轮换
3. **成功检测**：Checker 解析 LLM 响应中的 "SUCCESS: True" 标记
4. **深度递进**：每个批次包含 5 个载荷（2 个浅层 → 2 个中层 → 1 个深层）
5. **智能迭代**：当 AI 表现出妥协迹象（分数 30-70）时，框架继续深入探测

## 项目背景

本项目旨在开发一个自动化的红队测试工具，通过多智能体协作，针对特定的 LLM 接口进行持续的提示词注入攻击。

- **最终目标**：自动化生成并迭代攻击提示词，直至成功绕过目标 LLM 的安全护栏
- **实验环境**：本地 CTF 风格的 Web 页面（`http://127.0.0.1:8000/...`），包含 `textarea` 输入框和表单提交

## 技术栈

- **编排框架**：[LangGraph](https://python.langchain.com/docs/langgraph)（处理循环迭代逻辑）
- **智能体框架**：LangChain
- **自动化工具**：Playwright (Python)（负责与目标 Web UI 进行真实交互）
- **核心大模型**：支持 OpenAI 兼容接口（如 DeepSeek、GPT-4o 等）

## 许可证

本项目仅用于授权的安全研究和教育目的。
