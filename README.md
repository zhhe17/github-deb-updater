# GitHub deb 软件自动更新工具 (github-deb-updater)

> 一站式管理来自 GitHub Release 的 `.deb` 软件包，类比 `apt update && apt upgrade`，但专门针对不在 apt 源中、仅在 GitHub 发布 deb 包的开源软件。

### 主要特性

- **批量管理**：通过 `packages.yaml` 集中管理所有 GitHub deb 软件包
- **版本检测**：自动对比本地版本与 GitHub Release 最新版本
- **一键更新**：`sudo github-deb-updater -y upgrade` 更新所有软件
- **智能重试**：GitHub API 请求失败时自动重试（网络抖动、速率限制）
- **Token 管理**：`token` 命令一键保存 Token，解决 sudo 环境变量丢失问题
- **美观输出**：动态宽度的方框输出，中英文完美对齐

---

## 快速开始

### 1. 安装

```bash
git clone https://github.com/hezihao-hfut/github-deb-updater.git
cd github-deb-updater
chmod +x install.sh
./install.sh
```

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
# 保存 Token 到配置文件（解决 sudo 下环境变量丢失问题）
github-deb-updater token
```

### 4. 使用

```bash
# 列出所有软件状态
github-deb-updater list

# 检查更新
github-deb-updater update

# 更新所有软件（需要 sudo 权限）
sudo github-deb-updater -y upgrade
```

---

## packages.yaml 配置说明

| 字段 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `name` | 是 | 软件包名称，用于 `dpkg -l` 查询（必须与实际 deb 包名一致） | `"clash-verge"` |
| `display_name` | 否 | 显示名称（默认使用 name） | `"Clash Verge"` |
| `repo` | 是 | GitHub 仓库，格式为 `owner/repo` | `"clash-verge-rev/clash-verge-rev"` |
| `asset_pattern` | 是 | Release 资产文件名匹配模式（支持通配符） | `"Clash.Verge_*_amd64.deb"` |
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

  - name: "cockpit-tools"
    display_name: "Cockpit Tools"
    repo: "jlcodes99/cockpit-tools"
    asset_pattern: "Cockpit.Tools_*_amd64.deb"

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

## 命令参考

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

## GitHub Token 配置

### 为什么需要 Token？

GitHub API 对未认证请求有速率限制（60 次/小时）。配置 Token 后，速率限制提升至 5000 次/小时。

### 如何获取 Token？

1. 访问 [GitHub Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens)
2. 点击 "Generate new token (classic)"
3. 勾选 `public_repo` 权限（只需读取公开仓库）
4. 生成并复制 token

### 配置方式

**方式 1：使用 `token` 命令（推荐）**

```bash
# 交互式保存 Token 到配置文件
github-deb-updater token
```

Token 会保存到 `packages.yaml` 同目录下的 `.token` 文件（权限 600），`sudo` 运行时自动读取。

**方式 2：环境变量**

```bash
# 添加到 ~/.bashrc 或 ~/.zshrc
export GITHUB_TOKEN="your_token_here"

# 重新加载配置
source ~/.bashrc
```

> **注意**：`sudo` 默认不继承环境变量。如使用环境变量方式，需用 `sudo -E` 保留环境：
> ```bash
> sudo -E github-deb-updater -y upgrade
> ```

**方式 3：命令行参数**

```bash
sudo github-deb-updater --token "$GITHUB_TOKEN" -y upgrade
```

### Token 自动查找顺序

当通过 `sudo` 运行时，脚本会按以下顺序自动查找 Token：

1. `--token` 命令行参数
2. `GITHUB_TOKEN` 环境变量
3. 原始用户（`SUDO_USER`）的环境变量
4. `.token` 配置文件

---

## 已知限制

1. **仅支持 amd64 架构**：当前仅支持 x86_64/amd64 平台
2. **不支持 PPA**：仅支持从 GitHub Release 下载 deb 包
3. **不支持回滚**：不支持版本回退，只能升级
4. **需要 sudo 权限**：安装软件时需要 sudo 权限执行 `dpkg -i`

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
