# GitHub deb 软件自动更新工具 (github-deb-updater)

> 一站式管理来自 GitHub Release 和软件官方网站的 `.deb` 软件包，类比 `apt update && apt upgrade`，但专门针对不在 apt 源中、通过 GitHub 或官网 CDN 发布 deb 包的开源软件。

## 版本说明

本项目提供两个版本：

- **CLI 版本**：命令行工具，适合终端用户
- **Web 版本**：浏览器界面，提供图形化管理

## 支持的软件来源

每个软件包通过 `source` 字段声明"最新 deb 指针"的获取方式：

| source | 机制 | 适用场景 |
|--------|------|----------|
| `github`（默认） | GitHub API 定位 Release 资产 | 在 GitHub 发布 deb 的项目 |
| `url` | 官网固定的 latest 下载链接 | 提供"永远指向最新版"直链的官网（如微信） |
| `feed` | 厂商 JSON 配置接口 + 取值路径 | 有版本配置接口的厂商（如 QQ 的 pcConfig.json） |
| `scrape` | 抓取下载页面，按通配符筛选链接 | 下载页 HTML 直接列出 deb 链接的官网（如 ZCode、QQ 音乐） |

不同来源共用同一套核心管线：下载/Range 部分读取 → 校验 deb 内部 `Package`/`Version`/`Architecture` → `dpkg` 版本比较 → 安装与装后复核。**版本号一律以 deb 内部字段为准**，来源侧的标签、文件名只用于展示。

对需要签名才能下载的渠道（如 QQ 需经 `GetSign` 接口换取临时链接、WPS CDN 的 `t/k` 防盗链参数），通过可选的 `sign_command` 钩子接入：工具通过环境变量 `SIGN_URL` 传入原始链接，命令向 stdout 输出签名后的链接（参考 `scripts/sign-qq.sh`、`scripts/sign-wps.sh`）。

### 已验证的官网来源示例

```yaml
packages:
  # 官网固定 latest 链接（最简单、最稳定）
  - name: wechat
    display_name: 微信
    source: url
    url: "https://dldir1v6.qq.com/weixin/Universal/Linux/WeChatLinux_x86_64.deb"

  # 厂商 JSON 配置接口 + 签名钩子
  - name: linuxqq
    display_name: QQ
    source: feed
    feed_url: "https://qq-web.cdn-go.cn/im.qq.com_new/latest/rainbow/pcConfig.json"
    feed_path: "Linux.x64DownloadUrl.deb"
    sign_command: "scripts/sign-qq.sh"

  # 下载页面抓取
  - name: zcode
    display_name: ZCode
    source: scrape
    page_url: "https://zcode.z.ai"
    asset_pattern: "ZCode-*-linux-x64.deb"

  # 厂商下载信息接口（页面 JS 调用的 webapi，参数可静态化）
  - name: wemeet
    display_name: 腾讯会议
    source: feed
    feed_url: "https://meeting.tencent.com/web-service/query-download-info?q=%5B%7B%22package-type%22%3A%22app%22%2C%22channel%22%3A%220300000000%22%2C%22platform%22%3A%22linux%22%2C%22arch%22%3A%22x86_64%22%2C%22decorators%22%3A%5B%22deb%22%5D%7D%5D&nonce=0123456789abcdef&c_os=web"
    feed_path: "info-list.0.url"

  # 服务端渲染页面抓取 + CDN 防盗链签名钩子（签名算法可从页面内联 JS 逆出）
  - name: wps-office
    display_name: WPS Office
    source: scrape
    page_url: "https://linux.wps.cn/"
    asset_pattern: "wps-office_*_amd64.deb"
    sign_command: "scripts/sign-wps.sh"
```

---

## 快速开始

### 1. 安装

```bash
git clone https://github.com/hezihao-hfut/github-deb-updater.git
cd github-deb-updater
chmod +x install.sh
./install.sh
```

安装程序会询问安装类型：
- `1` - 仅 CLI 版本
- `2` - 仅 Web 版本
- `3` - 全部安装（默认）

### 2. 配置软件包列表

编辑 `packages.yaml`，添加你要管理的软件：

```yaml
packages:
  - name: "clash-verge"
    display_name: "Clash Verge"
    repo: "clash-verge-rev/clash-verge-rev"
    asset_pattern: "Clash.Verge_*_amd64.deb"
```

### 3. 配置 GitHub Token（推荐）

```bash
# CLI 版本
github-deb-updater token

# Web 版本
# 在设置页面中配置
```

### 4. 使用

**CLI 版本：**
```bash
# 列出所有软件状态
github-deb-updater list

# 检查更新
github-deb-updater update

# 更新所有软件（需要 sudo 权限）
sudo github-deb-updater -y upgrade
```

**Web 版本：**
```bash
# 启动服务
sudo systemctl start github-deb-updater

# 访问界面
# http://localhost:8000
```

---

## Web 版本功能

### 主要特性

- **图形化界面**：直观的卡片式软件包展示
- **一键更新**：点击按钮即可更新软件
- **批量操作**：支持一键更新所有软件
- **实时进度**：WebSocket 实时显示下载和安装进度
- **设置管理**：在界面上配置 Token 和添加软件包
- **API 文档**：自动生成的 API 文档（/docs）

### 版本与 Release 标签

Release 标签只用于找到匹配的 deb 资产，不参与更新大小判断。程序会读取候选 deb 内部的 `Package`、`Version` 和 `Architecture`，首页“最新版本”展示其中的 `Version`，再使用 `dpkg --compare-versions` 与本地 dpkg 版本比较。

因此不同软件无需各自维护比较器，epoch、`+build`、Debian revision、四段版本和 `~` 预发布版本都遵循同一套 Debian 规则。例如 PiliPlus 的 Release `2.1.2.3` 可以对应 deb `2.1.2+5281`，二者不会再被直接比较。

版本格式非法、dpkg 比较失败、本地版本查询失败或安装状态异常时，会报告错误，不再按“已是最新”或“未安装”处理。

Web 与 CLI 会将已验证的候选包名、版本和架构保存到缓存目录的 `metadata/` 中。GitHub 资产按仓库、资产 ID、大小、更新时间和下载 URL 区分；官网/CDN 资产按重定向解析后的稳定路径加 ETag、Last-Modified、Content-Length 区分（签名链接的 sign 参数每次都变，不参与身份计算），因此 CLI 与 Web 共享同一份缓存。资产未变时无需重新下载。清理旧 deb 不会删除这些元数据。缓存损坏或资产变化会触发重新读取，安装前仍需取得并校验实际 deb 文件；CLI 的 `--no-cache` 会绕过元数据缓存。

### 检查更新为什么不需要下载完整安装包

所有受支持的 CDN 都支持 HTTP Range 请求。检查更新时工具只按 deb 的 ar 头定位并读取 control 段（通常几百 KB）即可得到 `Package`/`Version`/`Architecture` 并写入元数据缓存；完整下载只发生在真正安装时。zstd 压缩的 control 段依赖系统 `zstd` 命令行工具（缺失时自动回退全量下载）。

如果 Range 部分读到的元数据与配置不符（厂商重传资产后 CDN 边缘节点可能短暂返回新旧不同构建），工具不会轻信也不会误装，而是自动回退完整下载复核，仍不一致才报错。

### 界面截图

![软件包列表](docs/images/package-list.png)

### 系统要求

- Python 3.10+
- root 权限（用于安装 deb 包）

---

## packages.yaml 配置说明

| 字段 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `name` | 是 | 软件包名称，用于 `dpkg -l` 查询（必须与 deb 内部包名一致，区分大小写） | `"clash-verge"` |
| `display_name` | 否 | 显示名称（默认使用 name） | `"Clash Verge"` |
| `source` | 否 | 来源类型：`github`（默认）/ `url` / `feed` / `scrape` | `"url"` |
| `repo` | github 来源必填 | GitHub 仓库，格式为 `owner/repo` | `"clash-verge-rev/clash-verge-rev"` |
| `asset_pattern` | github/scrape 来源必填 | 资产文件名匹配模式（支持通配符） | `"Clash.Verge_*_amd64.deb"` |
| `url` | url 来源必填 | 固定指向最新 deb 的下载链接 | `"https://dldir1v6.qq.com/.../WeChatLinux_x86_64.deb"` |
| `feed_url` | feed 来源必填 | 厂商 JSON 配置接口地址 | `"https://qq-web.cdn-go.cn/.../pcConfig.json"` |
| `feed_path` | feed 来源必填 | JSON 点分取值路径（支持数组下标） | `"Linux.x64DownloadUrl.deb"` |
| `page_url` | scrape 来源必填 | 包含 deb 链接的下载页面 | `"https://zcode.z.ai"` |
| `sign_command` | 否 | 签名命令：环境变量 `SIGN_URL` 收原始链接，stdout 出签名链接 | `"scripts/sign-qq.sh"` |
| `pre_install` | 否 | 安装前执行的命令 | `"echo '准备安装'"` |
| `post_install` | 否 | 安装后执行的命令 | `"echo '安装完成'"` |

### 完整示例

```yaml
packages:
  - name: "clash-verge"
    display_name: "Clash Verge"
    repo: "clash-verge-rev/clash-verge-rev"
    asset_pattern: "Clash.Verge_*_amd64.deb"

  - name: "cc-switch"
    display_name: "CC-Switch"
    repo: "farion1231/cc-switch"
    asset_pattern: "CC-Switch-v*-Linux-x86_64.deb"

  - name: "localsend"
    display_name: "LocalSend"
    repo: "localsend/localsend"
    asset_pattern: "LocalSend-*-linux-x86-64.deb"

  - name: "rustdesk"
    display_name: "RustDesk"
    repo: "rustdesk/rustdesk"
    asset_pattern: "rustdesk-*-x86_64.deb"

  - name: "hiddify"
    display_name: "Hiddify"
    repo: "hiddify/hiddify-app"
    asset_pattern: "Hiddify-Debian-x64.deb"
```

---

## CLI 命令参考

### 命令

| 命令 | 说明 |
|------|------|
| `update` | 检查所有软件的更新（默认命令） |
| `upgrade` | 更新所有有新版本的软件 |
| `upgrade <name>` | 仅更新指定软件 |
| `list` | 列出名单中所有软件及其当前状态 |
| `add` | 交互式向 packages.yaml 添加新软件 |
| `token` | 保存 GitHub Token 到配置文件（用于 sudo 场景） |
| `version` | 显示工具本身的版本信息 |

### 选项

| 选项 | 说明 |
|------|------|
| `--config <path>` | 指定 packages.yaml 路径（默认：脚本同级目录） |
| `--dry-run` | 仅检查版本，不执行安装 |
| `--yes`, `-y` | 跳过所有确认提示，自动确认 |
| `--token <token>` | 指定 GitHub Token（也可通过 GITHUB_TOKEN 环境变量） |
| `--no-cache` | 下载前强制清除对应缓存 |
| `--verbose` | 显示详细调试信息 |
| `-h`, `--help` | 显示帮助信息 |

### 示例

```bash
# 列出所有软件状态
github-deb-updater list

# 检查更新
github-deb-updater update

# 更新所有软件（需要 sudo）
sudo github-deb-updater -y upgrade

# 仅更新指定软件
sudo github-deb-updater -y upgrade clash-verge

# 模拟更新，不实际安装
github-deb-updater --dry-run upgrade

# 使用指定的配置文件
github-deb-updater --config /path/to/my-packages.yaml list

# 显示详细调试信息
github-deb-updater --verbose update

# 保存 GitHub Token（解决 sudo 下环境变量丢失问题）
github-deb-updater token
```

---

## Web API 参考

启动 Web 服务后，访问 http://localhost:8000/docs 查看完整的 API 文档。

### 主要 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/packages/` | 软件包列表页面 |
| GET | `/packages/api/list` | 获取软件包列表（JSON） |
| GET | `/packages/api/check` | 检查更新 |
| POST | `/packages/api/add` | 添加软件包 |
| DELETE | `/packages/api/{name}` | 删除软件包 |
| POST | `/updates/api/upgrade/{name}` | 更新单个软件包 |
| POST | `/updates/api/upgrade-all` | 批量更新 |
| WebSocket | `/updates/ws/upgrade/{name}` | 实时更新进度 |
| GET | `/settings/` | 设置页面 |
| POST | `/settings/api/token` | 设置 GitHub Token |

---

## GitHub Token 配置

### 为什么需要 Token？

GitHub API 对未认证请求有速率限制（60 次/小时）。配置 Token 后，速率限制提升至 5000 次/小时。

### 如何获取 Token？

1. 访问 [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens)
2. 点击 "Generate new token (classic)"
3. 勾选 `public_repo` 权限（只需读取公开仓库）
4. 生成并复制 token

### 配置方式

**方式 1：Web 界面（推荐）**

访问 http://localhost:8000/settings/，在设置页面中配置 Token。

**方式 2：CLI 命令**

```bash
# 交互式保存 Token 到配置文件
github-deb-updater token
```

**方式 3：环境变量**

```bash
# 添加到 ~/.bashrc 或 ~/.zshrc
export GITHUB_TOKEN="your_token_here"

# 重新加载配置
source ~/.bashrc
```

**方式 4：配置文件**

编辑 `config.yaml`：
```yaml
github_token: "your_token_here"
```

---

## 已知限制

1. **仅支持 amd64 架构**：当前仅支持 x86_64/amd64 平台
2. **不支持 PPA / apt 源**：支持 GitHub Release 与官网 deb 下载；厂商提供了官方 apt 源的软件建议直接用 apt 管理
3. **不支持回滚**：不支持版本回退，只能升级
4. **需要 sudo 权限**：安装软件时需要 sudo 权限执行 `dpkg -i`
5. **scrape 来源依赖页面结构**：官网改版可能导致解析失败（工具会显式报错，不会误装），需更新 `asset_pattern`
6. **root 服务与普通用户 CLI 混用**：缓存条目固定以 0644 写入，双方都能读取；若历史上遗留过 root 属主的 `cache/metadata/` 目录（内部文件 600），将其改名或 `sudo chown -R $(id -u):$(id -g) cache` 一次性迁移即可

---

## 贡献指南

### 如何提交新软件到名单

1. Fork 本仓库
2. 在 `packages.yaml` 中添加新软件条目
3. 提交 Pull Request，说明软件用途和仓库地址

### 提交格式

```yaml
  - name: "software-name"           # 必须与 dpkg -l 显示的包名一致
    display_name: "Software Name"
    repo: "owner/repo"
    asset_pattern: "software_*_amd64.deb"
```

### 注意事项

- 确保 GitHub 仓库是公开的
- 确保 Release 中有可用的 amd64 deb 包
- 确保 `name` 字段与实际 deb 包名一致（可用 `dpkg -l | grep 软件名` 查看）
- 确保 `asset_pattern` 能准确匹配目标文件

---

## 许可证

MIT License
