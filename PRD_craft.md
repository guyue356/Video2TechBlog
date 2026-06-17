
# Video2TechBlog

Slogan：

> Transform Technical Videos into Publication-Ready Technical Articles

---

# 一、PRD（产品需求文档）

# Video2TechBlog 产品需求文档（PRD）

## 1. 产品定位

帮助开发者、研究人员、技术博主将技术视频自动转化为高质量结构化技术博客。

目标输出不是会议纪要，而是可直接发布的技术文章。

---

## 2. 目标用户

### P0

* AI开发者
* 开源项目作者
* 技术博主
* 技术社区运营者

### P1

* 科研人员
* 研究生
* 企业技术培训团队

### P2

* B站UP主
* YouTube技术频道

---

## 3. 核心场景

### 场景1

用户上传：

Agentic RAG分享视频

系统输出：

公众号级技术文章

---

### 场景2

用户上传：

AI大会演讲视频

系统输出：

会议解读文章

---

### 场景3

用户上传：

Github项目介绍视频

系统输出：

项目技术分析博客

---

## 4. MVP范围

输入：

* MP4
* MOV
* AVI

输出：

* Markdown
* HTML

包含：

* 标题
* 摘要
* 章节
* 架构图
* 核心观点
* 技术总结

---

## 5. 非目标

第一阶段不支持：

* 视频剪辑
* 多人协作
* 多语言翻译
* SEO优化
* 知识图谱生成
* Mermaid 架构图自动生成
* 质量自动评估

后续迭代支持。

---

## 6. 成功指标

博客生成成功率 > 95%

平均生成时间 < 5分钟

用户编辑率 < 30%

用户满意度 > 4.5/5

技术博客可发布率 > 70%

---

# 二、产品架构设计

## 核心理念

传统方案：

```text
Video
 ↓
Transcript
 ↓
Summary
```

这是错误路线。

正确路线：

```text
Video
 ↓
Transcript
 ↓
Knowledge Graph
 ↓
Topic Understanding
 ↓
Technical Writing
 ↓
Blog
```

---

# 三、Agent架构设计

建议采用 LangGraph。

```text
Video Upload

      ↓

Video Analyzer

      ↓

ASR Agent

      ↓

Topic Segmentation Agent

      ↓

Knowledge Extraction Agent

      ↓

Technical Writer Agent

      ↓

Markdown Export
```

---

# 四、技术开发文档

# Video2TechBlog 技术设计文档

## 技术栈

Frontend

* Next.js 15
* TailwindCSS
* shadcn/ui

Backend

* FastAPI

Workflow

* LangGraph
* LangGraph Callbacks → SSE 实时推送处理进度和中间结果

LLM

* Gemini 2.5 Pro

ASR

* Faster Whisper Large V3

Storage

* 本地文件系统（视频、音频、Markdown/HTML 输出）

Database

* SQLite（本地开发，零配置）

Cache

* 不需要（本地演示无需缓存层）

Queue

* 不需要（LangGraph 内置异步流式编排）

Deployment

* 纯本地开发 & 演示
* 前端 `next dev` + 后端 `uvicorn` 即可跑通
* 无需 Docker / Cloudflare / Railway

---

## 数据流（Phase 1 + Phase 2）

视频上传

↓

提取音频

↓

Whisper转录

↓

章节识别

↓

知识抽取

↓

[SSE 实时推送每步中间结果]

↓

技术博客生成

↓

导出Markdown

> 注意：知识图谱构建、Mermaid 架构图生成、质量评估属于 Phase 3+，Phase 1/2 不做。

---

## 实时进度机制

整个处理链通过 **SSE (Server-Sent Events)** 向前端实时推送进度和中间内容：

### 事件类型

| 事件 | payload | 说明 |
|------|---------|------|
| `step_start` | `{step_name}` | 步骤开始 |
| `step_progress` | `{step_name, progress_pct, detail}` | 步骤进度（如转录 45%） |
| `step_result` | `{step_name, data}` | 步骤中间结果（实时展示内容） |
| `step_error` | `{step_name, message}` | 步骤错误 |
| `complete` | `{blog_id}` | 全流程完成 |

### 前端实时展示布局

```
+- 步骤条 --------------------+  +- 实时内容面板 -------------------+
| (已完成) 视频上传 (2s)         |  |                                  |
| (已完成) 音频提取 (5s)         |  |  [当前步骤的中间结果]              |
| (已完成) Whisper 转录 (45s)   |  |  实时流式显示的转录文本...          |
| (进行中) 章节识别 ........... |  |  第1章: Agentic RAG 概述          |
| (等待) 知识抽取               |  |  第2章: LangGraph 架构            |
| (等待) 博客生成               |  |  第3章: ...                      |
| (等待) 导出                   |  |                                  |
+-----------------------------+  +----------------------------------+
|
+- 最终预览 ------------------------------------------------------+
   ## Agentic RAG 深度解析

   本文基于视频分享，系统梳理 Agentic RAG 的核心概念...
```

### 实时可见内容（Phase 1 + Phase 2 覆盖）

- **上传阶段**：文件名、大小、上传进度条
- **音频提取**：进度百分比，预计耗时
- **Whisper 转录**：逐段流式展示转录文本
- **章节识别**：实时展示识别到的章节标题和分段
- **知识抽取**：实时展示 Concept / Method / Framework / Tool
- **博客生成**：流式输出 Markdown，类似 ChatGPT 的打字效果
- **导出**：Markdown / HTML 文件生成完成，可下载

---

## 数据结构

Video

id

title

duration

status

created_at

---

Transcript

video_id

start_time

end_time

text

speaker

---

Topic

video_id

title

summary

importance_score

---

Concept

topic_id

name

type

description

---

Blog

video_id

title

abstract

markdown

html

quality_score

---

## API设计

POST /api/upload

上传视频，启动异步处理链，返回 task_id

---

GET /api/task/{id}

查询任务状态

---

GET /api/task/{id}/stream

SSE 端点，实时推送处理进度和中间结果

---

GET /api/task/{id}/events

获取已完成步骤的事件列表（用于页面刷新后回放）

---

GET /api/blog/{id}

获取最终博客

---

POST /api/export/md

导出Markdown

---

POST /api/export/html

导出HTML

---

GET /api/concepts

获取知识点

---

GET /api/topics

获取章节结构

---

# 五、最关键的技术创新

很多人会做成：

```text
视频
↓
Whisper
↓
GPT
↓
博客
```

质量很差。

真正的核心模块应该是：

### Knowledge Reconstruction Engine

内部包含：

```text
Concept Extractor

Method Extractor

Framework Extractor

Tool Extractor

Paper Extractor

Code Extractor

Insight Extractor
```

例如视频内容：

```text
Agentic RAG
```

不是直接写文章。

而是先抽取：

```json
{
  "concepts": [
    "Agentic RAG"
  ],
  "frameworks": [
    "LangGraph"
  ],
  "methods": [
    "Reflection",
    "Planning"
  ]
}
```

再生成博客。

---

# 六、Vibe Coding开发路线

如果用 Codex + Claude Code 开发：

### Phase 1（3天）

本地 Demo，全流程实时可见：

```text
上传视频 → 前端实时展示上传进度
音频提取 → 可见进度条
Whisper 转录 → SSE 流式展示转录文本
Markdown 生成 → SSE 流式输出原始文章
```

可本地跑通完整 Demo，所有处理步骤和中间内容前端实时可见。

---

### Phase 2（1周）

在 Phase 1 基础上，本地实时可见：

```text
章节识别 → SSE 实时展示识别的章节结构
知识抽取 → SSE 实时展示 Concept / Method / Framework
结构化知识驱动的博客生成 → 流式输出最终文章
```

达到本地可用，处理链路完整可视化。

---

### Phase 3（2周，后续）

完成：

```text
知识图谱构建
Mermaid 架构图生成
关联图谱可视化展示
代码块自动标注与引用
质量评估与打分
```

达到作品集级别。

---

### Phase 4（1个月，后续）

完成：

```text
Agent Workflow
多模型协同
自动引用Github
自动引用论文
```

达到真正产品级。

对于你的背景（AI产品 + 技术主题识别研究），我会把这个项目进一步升级成：

```text
Video → Structured Knowledge → Technical Blog → Personal Knowledge Base
```

这样不仅是一个博客生成器，而是一个“技术知识生产 Agent”，在求职 AI 产品经理或 Agent 产品方向时会更有辨识度。
