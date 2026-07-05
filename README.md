<div align="center">
  <img src="./assets/logo.png" alt="EasyGEE" width="96" />
  <h1>EasyGEE</h1>

  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-0F766E?style=flat-square" /></a>
  <a href="./.codex-plugin/plugin.json"><img alt="Plugin" src="https://img.shields.io/badge/plugin-Codex%20%7C%20Claude-2563EB?style=flat-square" /></a>
  <a href="./.mcp.json"><img alt="MCP" src="https://img.shields.io/badge/MCP-stdio-111827?style=flat-square" /></a>

  **中文** · [English](./README_en.md)

  面向 AI Agent 的 Google Earth Engine / geemap 工作台插件。

  [能力](#能力) · [结构](#结构) · [使用](#使用) · [安全](#安全) · [致谢](#致谢)
</div>

## 能力

EasyGEE 把 Google Earth Engine、geemap、GeoMaster 方法知识和本地浏览器地图工作台打包成一个可复用插件。它的目标不是复刻 GEE 网页控制台，而是让 Agent 用一句自然语言完成数据查找、授权引导、配额检查、地图预览和本地/云端地理空间分析编排。

- 查找并解释 GEE 官方目录和 GEE Community Catalog 数据集，支持中英文任务描述。
- 标准化 Earth Engine / geemap 授权流程，不暴露 OAuth token、验证码、凭据文件或 service account key。
- 查询 Earth Engine 项目配额和用量，并把结果转成 Agent 可读的摘要。
- 生成轻量 EasyGEE Map Console，用于 AOI 绘制、图层叠加、底图切换和视觉检查。
- 内置 GeoMaster skill，覆盖 CRS、本地 GIS、遥感、机器学习、STAC/COG、科学领域方法和排错经验。

## 结构

```text
easygee/
├── .codex-plugin/       # Codex 插件元数据
├── .claude-plugin/      # Claude 插件元数据
├── assets/              # EasyGEE 图标与 logo
├── commands/            # Claude-style 命令入口
├── hooks/               # Hook 配置与轻量脚本
├── scripts/             # EasyGEE MCP server 启动入口
├── skills/
│   ├── easygee/         # GEE / geemap / 地图控制台工作流
│   └── geomaster/       # 本地 GIS 与遥感方法知识
└── adapters/            # Codex、Claude、Zcode、Qoder 适配说明
```

## 使用

### 1. 快速安装

给 Agent 的一句话安装：

```text
帮我安装这个插件：[Rimagination/easygee](https://github.com/Rimagination/easygee)
```

Agent 看到这句话后应完成四件事：克隆或更新仓库、写入个人 marketplace、校验插件、在可用时执行 `codex plugin add easygee@local-plugins`。

在 Windows 上也可以直接运行这一行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command '$p=Join-Path $HOME "plugins\easygee"; if(Test-Path $p){ git -C $p pull --ff-only } else { gh repo clone Rimagination/easygee $p }; & (Join-Path $p "scripts\install-easygee.ps1")'
```

默认安装位置是：

```text
%USERPROFILE%\plugins\easygee
```

安装脚本会把插件路径加入本地 marketplace。Codex 会从这里发现 EasyGEE：

```text
C:\Users\Liang\.agents\plugins\marketplace.json
```

安装脚本也会校验插件结构；手动校验命令是：

```powershell
python C:\Users\Liang\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py C:\Users\Liang\plugins\easygee
```

### 2. 快速使用

直接用自然语言告诉 Agent 你要做什么。下面这些例子覆盖了最常见的日常用法：

```text
帮我授权 geemap 到 example-ee-project-123456

打开 EasyGEE 地图，我想先看看北京朝阳公园附近，然后手动画一个 AOI

我想做北京朝阳公园 2024 年夏季 NDVI，帮我选择合适的 GEE 数据集并解释为什么

把 Sentinel-2 真彩色和 NDVI 叠加到地图上，我想在浏览器里检查云和植被情况

查看我的 Earth Engine 项目配额、用量层级和剩余额度

帮我把当前 AOI 的 NDVI 结果导出到 Google Drive，并告诉我导出参数是否合理

我有一个本地 GeoJSON，帮我判断应该用 GEE 处理还是本地 GIS 处理，并生成可运行脚本
```

## 安全

EasyGEE 默认把浏览器和凭据当作用户私有空间。Agent 可以生成授权计划、启动本地工具、查询安全摘要，但不能要求用户把 OAuth URL、验证码、token、credential 文件、service account key 或短期 access token 粘贴到聊天、日志、文档或提交里。

GeoMaster 以 skill snapshot 形式内置在插件中，而不是嵌套 git 仓库。这样插件保持自包含、轻量、离线可用，也避免把依赖目录、历史仓库状态或未知远端同步进插件包。

## 致谢

EasyGEE 参考并蒸馏了许多开放资料和项目经验。特别感谢：

- [Google Earth Engine 官方文档](https://developers.google.com/earth-engine)：认证、初始化、配额、导出、客户端/服务端模型和遥感工作流的主要依据。
- [Earth Engine Data Catalog](https://developers.google.com/earth-engine/datasets/) 与 [Earth Engine STAC Catalog](https://storage.googleapis.com/earthengine-stac/catalog/catalog.json)：EasyGEE 数据目录、数据集介绍和图层搜索的核心来源。
- [GEE Community Catalog](https://gee-community-catalog.org/) 与 [community_datasets.csv](https://github.com/sadassimov/geemu-skill/blob/main/awesome-gee-community-datasets/community_datasets.csv)：用于扩展官方目录之外的社区数据集。
- [geemap](https://geemap.org/) / [gee-community/geemap](https://github.com/gee-community/geemap)：GEE Python 交互式地图、Notebook 工作流、导出工具和数据集探索模式的重要参考。
- [Qiusheng Wu 的 Earth-Engine-Catalog](https://github.com/giswqs/Earth-Engine-Catalog)：轻量机器可读 GEE 数据目录索引。
- [OpenGeoAgent / GeoAgent](https://github.com/opengeos/GeoAgent)、[GeoLibre](https://github.com/opengeos/GeoLibre)、[leafmap](https://leafmap.org/) 与 [anymap](https://github.com/opengeos/anymap)：启发了 EasyGEE 的地图优先、Agent 驱动和本地优先 GIS 工作台设计。
- [Insight Maps](https://map.insightmaps.app/)：参考了其紧凑地图工具栏、图层目录和专业 Web GIS 交互风格。
- [netease-youdao/LobsterAI](https://github.com/netease-youdao/LobsterAI)：README 首屏结构、徽章和语言切换排版的参考。

更完整的来源与归因记录见 [skills/easygee/references/SOURCES.md](./skills/easygee/references/SOURCES.md)。
