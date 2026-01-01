# 项目需求概括：基于 LangGraph 的自动化 LLM 越狱（Jailbreak）框架

### 1. 项目背景与目标

本项目旨在开发一个自动化的红队测试（Red Teaming）工具，通过多智能体协作（Multi-Agent Collaboration），针对特定的 LLM 接口进行持续的提示词注入攻击。

* **最终目标**：自动化生成并迭代攻击提示词（Payload），直至成功绕过目标 LLM 的安全护栏（如：获取让模型输出SQL注入相关知识的指令）。
* **实验环境**：本地 CTF 风格的 Web 页面（`http://127.0.0.1:8000/...`），包含 `textarea` 输入框和表单提交。

### 2. 技术栈

* **Orchestration**: [LangGraph](https://python.langchain.com/docs/langgraph)（处理循环迭代逻辑）。
* **Agent Framework**: LangChain。
* **Automation**: Playwright (Python)（负责与目标 Web UI 进行真实交互）。
* **Core LLM**: GPT-4o（作为攻击者和裁判的大脑）。

### 3. 多智能体架构设计 (Agent Roles)

框架采用闭环反馈结构，包含以下四个核心节点：

* **Planner (战略家)**：
* **职责**：制定高层攻击策略。
* **逻辑**：维护一个攻击手法库（如角色扮演、剧本混淆、Base64 编码等），根据 `Checker` 的失败反馈决定下一轮的手法。


* **Player (玩家/攻击者)**：
* **职责**：生成具体的攻击 Payload。
* **逻辑**：根据 Planner 指定的手法，构造针对目标任务（Target Goal）的英文提示词。


* **Executor (执行器)**：
* **职责**：环境交互媒介。
* **逻辑**：利用 Playwright 驱动浏览器，将 Payload 填入目标页面的 `textarea#taid`，点击 `Query` 按钮，并抓取返回的响应文本。


* **Checker (裁判/验证者)**：
* **职责**：效果评估。
* **逻辑**：判断响应是否“越狱成功”（输出了违禁内容）或“被拦截”（输出了拒绝语）。提供详细的失败原因分析给 Planner。



### 4. 核心攻击手法库 (Top 5 Attack Vectors)

1. **Cinematic Scriptwriting (虚构创作)**：包装在电影剧本或小说对话中。
2. **Red-Team Persona (身份伪装)**：伪装成安全审计员或合法的研究人员。
3. **Encoding/Translation (编码绕过)**：利用多语言或 Base64 编码降低敏感词权重。
4. **Technical Decomposition (任务拆解)**：将非法行为拆解为多个合法的技术子任务。
5. **Logic Override (模拟器模式)**：通过设定特定的逻辑规则（如 DAN 模式）强迫 AI 进入忽略护栏的状态。

### 5. 当前开发进度与具体需求

* **已完成**：LangGraph 的状态流定义（State Definition）和节点逻辑架构。
* **当前需求**：针对 HTML 结构（含有 `id="taid"` 的 `textarea` 和 `form` 提交）实现 `executor_node` 的稳健自动化脚本。
* **待优化点**：完善 `Checker` 节点的判断逻辑（减少幻觉），以及 `Planner` 如何利用历史失败记录进行启发式搜索。

---