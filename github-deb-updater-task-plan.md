# 任务计划书：GitHub deb 软件自动更新工具（github-deb-updater）

**版本：** v1.0  
**目标执行者：** AI Agent（具备 bash 执行、文件读写、网络访问能力）  
**目标平台：** Ubuntu 22.04 / 24.04 LTS（amd64）

---

## 一、项目概述

开发一个命令行工具 `github-deb-updater`，用于管理和自动更新来自 GitHub Release 的 `.deb` 软件包。功能类比 `apt update && apt upgrade`，但专门针对不在 apt 源中、仅在 GitHub 发布 deb 包的开源软件。

工具需支持：
- 维护一份本地"更新名单"（软件名 + GitHub 仓库地址）
- 检测每款软件的本地已安装版本
- 请求 GitHub API 获取最新 Release 版本号
- 比较版本号，若有新版则下载并安装
- 提供清晰的日志输出与错误处理

---

## 二、项目目录结构

执行完成后，项目目录结构应如下：

```
github-deb-updater/
├── github-deb-updater.sh       # 主执行脚本
├── packages.yaml               # 软件更新名单（用户维护）
├── lib/
│   ├── version.sh              # 版本比较函数库
│   ├── github.sh               # GitHub API 交互函数库
│   ├── installer.sh            # 下载与安装函数库
│   └── logger.sh               # 日志输出函数库
├── cache/                      # 临时下载缓存目录（自动创建）
├── logs/
│   └── update.log              # 更新历史日志
├── install.sh                  # 一键安装脚本（注册到系统路径）
└── README.md                   # 使用说明
```

---

## 三、软件更新名单格式（packages.yaml）

文件使用 YAML 格式，字段说明如下：

```yaml
packages:
  - name: "cc-switch"                                 # 软件名（用于 dpkg -l 查询）
    display_name: "CC-Switch"                         # 显示名称（可选）
    repo: "farion1231/cc-switch"                      # GitHub 仓库（owner/repo）
    asset_pattern: "CC-Switch-v*-Linux-x86_64.deb"    # Release asset 文件名匹配模式（glob）
    pre_install: ""                                   # 安装前执行的命令（可选）
    post_install: ""                                  # 安装后执行的命令（可选）

  - name: "clash"
    display_name: "Clash Verge"
    repo: "clash-verge-rev/clash-verge-rev"
    asset_pattern: "Clash.Verge_*_amd64.deb"

```

> **约定：** `asset_pattern` 支持 glob 通配符，用于在 Release 资产列表中匹配正确的 deb 文件。若一个 Release 有多个匹配文件，取第一个。

---

## 四、详细任务步骤

### 任务 1：初始化项目结构

**操作：**
1. 在当前目录创建 `github-deb-updater/` 及子目录（`lib/`、`cache/`、`logs/`）
2. 所有 shell 脚本文件赋予可执行权限（`chmod +x`）
3. `cache/` 目录加入 `.gitignore`

**验证标准：** `tree github-deb-updater/` 输出与预期目录结构一致。

---

### 任务 2：编写日志函数库（lib/logger.sh）

**功能要求：**
- `log_info "[消息]"` — 输出蓝色 INFO 信息，同时写入 `logs/update.log`（带时间戳）
- `log_success "[消息]"` — 输出绿色 SUCCESS 信息
- `log_warn "[消息]"` — 输出黄色 WARN 信息
- `log_error "[消息]"` — 输出红色 ERROR 信息，写入 stderr
- 日志文件每条记录格式：`[YYYY-MM-DD HH:MM:SS] [LEVEL] 消息`

**示例输出：**
```
[2025-06-01 10:23:45] [INFO]    检查 Visual Studio Code 更新...
[2025-06-01 10:23:46] [SUCCESS] code 已是最新版本 (1.89.1)
[2025-06-01 10:23:50] [INFO]    发现新版本: gh 2.49.0 -> 2.50.0，开始下载...
[2025-06-01 10:24:10] [SUCCESS] gh 更新完成 (2.50.0)
```

---

### 任务 3：编写 GitHub API 函数库（lib/github.sh）

**函数列表及说明：**

#### `github_get_latest_release_tag <owner/repo>`
- 调用 GitHub API：`https://api.github.com/repos/{owner}/{repo}/releases/latest`
- 提取 `tag_name` 字段（如 `v1.89.1`）
- 去除前缀 `v`，返回纯版本号（如 `1.89.1`）
- 若 API 返回 HTTP 403/429（速率限制），输出提示并退出当前软件检查，不中断整体流程
- 若仓库不存在（404），记录错误并跳过

**请求头处理：**
- 若环境变量 `GITHUB_TOKEN` 存在，则在请求中加入 `Authorization: Bearer $GITHUB_TOKEN` 头，提升 API 速率限制（未认证：60次/小时；认证：5000次/小时）

#### `github_get_asset_url <owner/repo> <asset_pattern>`
- 调用 GitHub API 获取最新 Release 的 assets 列表
- 遍历 assets，用 `fnmatch` 风格匹配 `asset_pattern`
- 返回匹配文件的 `browser_download_url`
- 若无匹配，返回空字符串并记录警告

---

### 任务 4：编写版本比较函数库（lib/version.sh）

**函数列表及说明：**

#### `get_installed_version <package_name>`
- 执行 `dpkg -l <package_name> 2>/dev/null`
- 解析输出，提取版本号（第3列）
- 处理 epoch 前缀（如 `2:1.89.1` → `1.89.1`）
- 若软件未安装，返回空字符串

#### `version_compare <version_a> <version_b>`
- 比较两个语义化版本号（支持 `major.minor.patch.build` 格式）
- 返回值：`0`（相等）、`1`（a > b）、`2`（a < b）
- 实现方式：使用 `sort -V` 进行自然版本排序，无需依赖 Python

#### `is_update_needed <installed_version> <latest_version>`
- 封装调用 `version_compare`，若 latest > installed 则返回 `true`，否则返回 `false`
- 若 `installed_version` 为空（未安装），也返回 `true`（视为需要安装）

---

### 任务 5：编写下载与安装函数库（lib/installer.sh）

**函数列表及说明：**

#### `download_deb <url> <package_name> <version>`
- 下载目标：`cache/<package_name>_<version>.deb`
- 使用 `curl -fsSL --progress-bar -o <目标路径> <url>` 下载
- 下载完成后用 `dpkg-deb --info <文件>` 验证 deb 包完整性
- 若验证失败，删除损坏文件并返回错误码 1
- 若文件已存在于缓存且完整，跳过下载（断点续传语义）

#### `install_deb <deb_path> <pre_install_cmd> <post_install_cmd>`
- 若 `pre_install_cmd` 非空，先执行前置命令
- 执行 `sudo dpkg -i <deb_path>`
- 若 dpkg 报告缺少依赖，自动执行 `sudo apt-get install -f -y` 修复依赖
- 若 `post_install_cmd` 非空，执行后置命令
- 返回最终安装结果（成功/失败）

#### `cleanup_cache`
- 删除 `cache/` 目录下 7 天前的 `.deb` 文件（`find cache/ -name "*.deb" -mtime +7 -delete`）

---

### 任务 6：编写主脚本（github-deb-updater.sh）

**命令行接口：**

```bash
github-deb-updater [命令] [选项]

命令：
  update              检查所有软件的更新（默认命令，类比 apt update）
  upgrade             更新所有有新版本的软件（类比 apt upgrade）
  upgrade <name>      仅更新指定软件
  list                列出名单中所有软件及其当前状态
  add                 交互式向 packages.yaml 添加新软件
  version             显示工具本身的版本信息

选项：
  --config <path>     指定 packages.yaml 路径（默认：脚本同级目录）
  --dry-run           仅检查版本，不执行安装
  --yes, -y           跳过所有确认提示，自动确认
  --token <token>     指定 GitHub Token（也可通过 GITHUB_TOKEN 环境变量）
  --no-cache          下载前强制清除对应缓存
  --verbose           显示详细调试信息
  -h, --help          显示帮助信息
```

**主流程（`upgrade` 命令）：**

```
1. 解析 packages.yaml，读取软件列表
2. 对每个软件：
   a. 调用 get_installed_version 获取本地版本
   b. 调用 github_get_latest_release_tag 获取最新版本
   c. 调用 is_update_needed 判断是否需要更新
   d. 若需要更新：
      - 调用 github_get_asset_url 获取 deb 下载链接
      - 若 --dry-run 则仅打印信息，跳过下载安装
      - 若非 --yes，提示用户确认此次安装
      - 调用 download_deb 下载安装包
      - 调用 install_deb 执行安装
      - 记录结果到日志
3. 输出汇总报告：已更新 N 个，跳过 M 个，失败 K 个
4. 调用 cleanup_cache 清理旧缓存
```

**汇总报告格式示例：**
```
╔══════════════════════════════════════╗
║         更新完成 - 汇总报告          ║
╠══════════════════════════════════════╣
║  ✅ 已更新: 2 个                     ║
║     • gh: 2.49.0 → 2.50.0           ║
║     • cursor: 0.42.0 → 0.43.1       ║
║  ⏭  已跳过: 2 个（已是最新版）       ║
║  ❌ 失败: 0 个                       ║
╚══════════════════════════════════════╝
```

---

### 任务 7：编写解析 packages.yaml 的辅助函数

由于纯 bash 不原生支持 YAML，采用以下策略：

**方案 A（优先）：** 检测系统是否安装 `python3`，若有则用以下 Python 一行式解析 YAML：
```bash
python3 -c "import yaml,sys; data=yaml.safe_load(open('packages.yaml')); ..."
```
若系统无 `python3-yaml`，使用 `pip3 install pyyaml --quiet` 安装，或回落到方案 B。

**方案 B（降级）：** 使用 `grep`/`sed`/`awk` 实现简单 YAML 解析，仅支持本项目所需的固定字段格式，不依赖外部库。

> Agent 应优先尝试方案 A，失败时自动切换方案 B，并在日志中记录当前使用的解析方式。

---

### 任务 8：编写一键安装脚本（install.sh）

**功能：**
1. 检测依赖：`curl`、`dpkg`、`sudo`（若缺少则提示安装命令后退出）
2. 将 `github-deb-updater.sh` 符号链接到 `/usr/local/bin/github-deb-updater`（需 sudo）
3. 创建默认配置目录 `~/.config/github-deb-updater/`，并将 `packages.yaml` 复制到该目录（若不存在）
4. 输出安装完成提示，显示使用示例

**卸载方式（在 README 中说明）：**
```bash
sudo rm /usr/local/bin/github-deb-updater
```

---

### 任务 9：编写 README.md

README 必须涵盖以下章节：

1. **项目简介** — 一句话说明用途
2. **快速开始** — 安装 + 最简使用示例（3步以内）
3. **packages.yaml 配置说明** — 字段表格 + 完整示例
4. **命令参考** — 所有命令和选项的表格
5. **GitHub Token 配置** — 为何需要、如何配置（`~/.bashrc` 或 `.env`）
6. **已知限制** — 仅支持 amd64，不支持 PPA，不支持回滚等
7. **贡献指南** — 如何提交新软件到名单（PR 流程）

---

### 任务 10：端到端集成测试

执行以下测试用例，所有用例须通过后方视为任务完成：

| 测试编号 | 测试场景 | 预期结果 |
|----------|----------|----------|
| T-01 | 运行 `./github-deb-updater.sh list`（packages.yaml 含3条有效记录） | 输出3条软件状态，无报错 |
| T-02 | 运行 `./github-deb-updater.sh update`（网络正常） | 成功获取所有软件最新版本号，日志写入正常 |
| T-03 | 运行 `./github-deb-updater.sh upgrade --dry-run` | 输出待更新列表，不执行实际下载/安装 |
| T-04 | 版本比较：`version_compare 2.50.0 2.49.1` | 返回 `1`（a > b） |
| T-05 | 版本比较：`version_compare 1.0.0 1.0.0` | 返回 `0`（相等） |
| T-06 | `github_get_latest_release_tag cli/cli` | 返回非空版本号字符串 |
| T-07 | `get_installed_version dpkg`（dpkg必然已安装） | 返回非空版本号 |
| T-08 | `get_installed_version nonexistent-pkg-xyz` | 返回空字符串，无报错 |
| T-09 | packages.yaml 中含无效仓库名 | 跳过该软件，记录错误，其余正常继续 |
| T-10 | GitHub API 无认证时触发速率限制（模拟） | 输出友好提示，建议配置 GITHUB_TOKEN |

---

## 五、非功能性要求

- **无需 root 启动：** 工具本身以普通用户运行，仅 `dpkg -i` 步骤使用 `sudo`（由 installer.sh 内部调用）
- **幂等性：** 重复运行不应产生副作用（已安装最新版时跳过，不重复安装）
- **离线友好：** 网络不通时输出明确错误，不崩溃退出
- **零外部依赖（工具本身）：** 主脚本仅依赖 `bash`、`curl`、`dpkg`、`awk`、`grep`，这些均为 Ubuntu 默认安装
- **可移植性：** 不使用 bashism 以外的特性，兼容 bash 4.x+

---

## 六、交付物清单

Agent 执行完毕后，以下文件必须存在且内容完整：

- [ ] `github-deb-updater/github-deb-updater.sh`（主脚本，可执行）
- [ ] `github-deb-updater/packages.yaml`（含至少4条示例软件记录）
- [ ] `github-deb-updater/lib/logger.sh`
- [ ] `github-deb-updater/lib/github.sh`
- [ ] `github-deb-updater/lib/version.sh`
- [ ] `github-deb-updater/lib/installer.sh`
- [ ] `github-deb-updater/install.sh`（可执行）
- [ ] `github-deb-updater/README.md`
- [ ] 任务 10 所有测试用例输出结果（可附在日志或独立 `test-report.txt`）

---

## 七、执行约束与注意事项

1. **不得修改系统 apt 源**，所有操作仅限 dpkg 层面
2. **不得硬编码 GitHub Token**，必须通过环境变量或命令行参数传入
3. **下载的 deb 文件必须经过完整性校验**后再安装，防止损坏文件导致系统问题
4. **sudo 密码缓存依赖系统设置**，脚本不得存储或传递明文密码
5. **错误不得静默吞没**，每个函数必须有明确的错误返回码和日志记录
6. `cache/` 目录不得无限增长，每次运行结束须清理 7 天以上的旧 deb 文件

---

*文档结束 — 请 Agent 按照上述步骤顺序执行，完成后提交交付物清单中的所有文件。*
