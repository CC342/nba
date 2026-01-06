# 🏀 NBA Live Stream Proxy (Hugging Face Edition)

![Python](https://img.shields.io/badge/Python-3.9-blue?style=flat-square&logo=python)
![Flask](https://img.shields.io/badge/Flask-2.x-green?style=flat-square&logo=flask)
![Docker](https://img.shields.io/badge/Docker-Enabled-blue?style=flat-square&logo=docker)
![License](https://img.shields.io/badge/License-MIT-orange?style=flat-square)

这是一个运行在 **Hugging Face Spaces** 上的轻量级 NBA 流媒体代理服务。

它采用 **Docker** 部署，后端使用 **Flask** 进行 M3U8 路径重写，前端采用精美的 **iOS 磨砂玻璃 (Glassmorphism)** 风格设计，并支持动态球队 Logo 展示。

---

## ✨ 主要功能 (Features)

* **⚡️ 直连模式 (Direct Mode)**：
    * 服务器仅解析和修复 M3U8 列表路径。
    * **视频流量 (TS 切片) 由客户端直接向源站请求**。
    * **优势**：速度极快，不消耗 Hugging Face 带宽配额，支持高并发。
* **🎨 iOS 风格 UI**：
    * 采用 Apple 风格的磨砂玻璃背景。
    * 沉浸式 NBA 深色球馆背景图。
    * 响应式设计，完美适配手机和 PC。
* **🛡️ 智能路径修复**：
    * 自动处理源站的相对路径（`../`）和伪装后缀（`.jpeg` / `.png`）。
    * 利用 `urljoin` 生成绝对路径，确保播放器（VLC/PotPlayer）能稳定连接。
* **⛹️ 动态 Logo 展示**：
    * 选择球队时，自动从 ESPN/NBA 官方 CDN 获取高清 Logo 并带有弹跳动画效果。

---

## 🛠 部署指南 (Deployment)

只需简单几步即可拥有你自己的 NBA 转播站。

### 1. 创建 Space
在 Hugging Face 上创建一个新的 Space：
* **SDK**: 选择 `Docker` (必须)
* **Template**: 选择 `Blank`
* **Hardware**: 选择 `Free` (2 vCPU, 16GB RAM)

### 2. 上传文件
请确保你的文件结构如下所示：

```text
.
├── app.py                # Flask 后端逻辑 & 球队列表配置
├── Dockerfile            # 容器构建文件 (开放 7860 端口)
├── requirements.txt      # 依赖库 (flask, requests, urllib3)
├── README.md             # 说明文档
└── templates
    └── index.html        # 前端 HTML 页面 (iOS UI)
