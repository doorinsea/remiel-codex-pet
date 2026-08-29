# 蕾米埃尔 Codex 桌宠

![蕾米埃尔](assets/readme/ramiel.jpg)

一只会实时反映 Codex 工作状态的 Windows 桌面宠物，基于“桌宠公开版”全模型改造。
多项目并行时自动聚合状态：只要有任务在思考就保持 `think`，任一任务完成弹出
`happy` 并显示微信风格气泡，点击气泡或宠物即可收回；Codex 征求权限时弹出粉色
审批窗口，可直接“允许 / 总是允许 / 拒绝”。右键单击打开**本地插件控制台**，
可在桌面预览区拖动插件示例调整其在真实桌面上的相对位置、开关插件、配置
DeepSeek 余额档位等。

## 下载

[![Download](https://img.shields.io/badge/Download-remiel--codex--pet%20v1.0.0-FF7FA3?style=for-the-badge&logo=github)](https://github.com/doorinsea/remiel-codex-pet/releases/latest/download/remiel-codex-pet-v1.0.0.zip)

⬇️ **免安装版（解压即用）**：[下载 v1.0.0](https://github.com/doorinsea/remiel-codex-pet/releases/latest/download/remiel-codex-pet-v1.0.0.zip)
—— Windows，无需安装 Python，解压后双击 `蕾米埃尔codex桌宠.exe` 即可。也可到
[Releases](https://github.com/doorinsea/remiel-codex-pet/releases) 页面选择版本，
或点右上角 **Code → Download ZIP** 获取源码。

## 状态图鉴

![状态图鉴](assets/readme/gallery.jpg)

## 状态语义与素材设计思路

| 桌宠状态 | Codex 触发时机 | 素材文件 | 设计思路 |
| --- | --- | --- | --- |
| silent | 默认待机 | silent.gif | 安静循环，不打扰 |
| think | 任意会话 `task_started` / `user_message` | think.gif | 思考锁定：只允许完成时切到 happy，单击、键盘连击等都不会打断 |
| happy | 任一任务 `final_answer` / `task_complete` | happy.gif | 完成庆祝，保持 5 秒；单击可提前收回；若仍有任务在思考则回 think，否则回 silent |
| work | 键盘 2 秒内连击 8 次 | work.gif | 手动唤醒动画，与 Codex 状态无关；停止敲击 1 秒后自动回 silent |
| afterclick | 单击宠物（非思考/完成状态） | afterclick.gif | 单击反馈，播放一次回 silent，不打开任何窗口 |

## 素材使用途径

- `素材/*.gif`：桌宠 5 个状态动画，由 `silent_pet.py` 运行时加载并循环播放，随宠物窗口缩放重渲染。
- `assets/readme/`：README 宣传图与状态图鉴（`ramiel.jpg` 为本项目宣传图）。

Codex 桌面应用由程序在双击打开时**自动探测**（`Get-StartApps` → 已知 AppID），
任何电脑 clone 下来都开箱即用，无个人硬编码路径。

## 快速开始

### 运行

1. Windows + Python 3.10+，依赖 `pillow`、`pynput`。
2. 直接运行：`python silent_pet.py`；或跑 `build_pet.bat` 打包出 `蕾米埃尔codex桌宠.exe`
   （脚本自动使用 PATH 里的 `py -3` / `python`，也可用环境变量 `PYEXE` 指定）。
3. 单实例：重复启动会自动退出。

### 配置 config.json（可选）

把 `config.example.json` 复制为 `config.json`（放在 exe / 脚本同目录，或用环境变量
`CODEX_PET_CONFIG` 指定位置）。可选字段：

| 字段 | 说明 |
| --- | --- |
| deepseek_api_key | DeepSeek API Key（余额插件使用；不填则徽章不显示） |
| deepseek_balance_tiers | 余额档位三个界限（默认 20 / 50 / 80），也可在控制台里直接改 |
| plugin_positions | 插件相对桌宠中心的位置偏移（由控制台预览区拖动生成，一般无需手改） |

`config.json` 已被 .gitignore 排除，不会进仓库。

## 交互

- 左键单击：收回气泡（happy 时）/ 播放单击动画（其余状态）
- 左键双击：收起气泡与审批窗，并打开 Codex（自动探测桌面应用，未运行则启动）
- 按住拖拽：移动宠物，气泡与审批窗跟随
- 右键单击：打开本地插件控制台（浏览器）
- 右下角缩放把手：按住拖动实时调整大小（120~400px），以桌宠中心为锚点，
  插件整体跟随缩放，相对位置不变
- 右键双击：退出桌宠
- 键盘 2 秒内连击 8 次：work 动画
- 思考中（think）状态锁定：单击、键盘连击等不会切换到其它状态，直到思考完成转 happy

## 气泡

Codex 完成思考后，宠物上方弹出**微信风格白色圆角气泡**（粉色不透明），文案为
“爱思考先生/小姐，你的任务已经完成了~”。默认保持 5 秒自动收起（期间单击可提前收回）；
多条会话并行时，只要还有任务在思考，气泡收起后宠物会回到 think。气泡跟随宠物拖拽移动。

## 审批窗口

Codex 征求权限时，宠物弹出**粉色不透明审批窗口**，只显示授权原因，可直接点击：

- 允许 → 点回 Codex 应用里的 Allow
- 总是允许 → 点回 Always allow
- 拒绝 → 点回 Deny

通过 Windows UI 自动化把决定点回 Codex 应用的审批卡片（按钮中英文都匹配，未渲染时自动重试；
右键点审批窗可临时关掉，不做任何决定）。命令被批准/拒绝后窗口自动关闭。

“Approve for me（自动审批）”模式下：升级命令出现后先观察 3 秒，并用 UI 自动化探测应用里
是否真的出现审批卡片，**有卡片才弹窗**；自动批准但执行较慢的命令不会误弹。桌宠启动时
不重放历史未决审批。

## 插件系统与本地控制台

桌宠内置轻量插件系统（`plugins/` 目录，每个子目录 = 一个插件），并提供一个本地
Web 控制台（仅监听 127.0.0.1 随机端口）。**右键单击桌宠**即可在浏览器打开。

### DeepSeek 余额（喧响值风格）

实时显示 DeepSeek 账户余额，采用绝区零“喧响值”风格**反向嘲讽档位**——余额越少等级越高：

| 档位 | 余额 | 样式 |
| --- | --- | --- |
| 极 | < 20 | 金色 + “极”汉字 |
| 特 | 20 ~ 50 | 黄色 + “特”汉字 |
| 喧 | 50 ~ 80 | 蓝青色 + “喧”汉字 |
| 基础 | ≥ 80 | 普通样式，无汉字 |

档位界限默认 20 / 50 / 80，可在控制台里填写三个数字实时修改；切换档位时徽章
周边闪一次白光。数字与英文评级词（MAXIMUM / BLASTING / UPROAR）随档位染色。

### 控制台功能

- **桌面预览区**：1:1 展示桌宠与已打开插件的相对位置；拖动插件示例、松手即把
  真实桌面上的插件移到对应位置（以桌宠中心为参照；桌宠缩放时插件整体跟随缩放，
  相对位置不偏移）。支持一键“重置位置”。
- **插件开关**：打开 / 关闭插件，即时生效。
- **档位设置与示例**：DeepSeek 余额卡片内可直接配置三个档位界限，并附四档样式示例图。

## Codex 状态检测原理

后台线程轮询 `~/.codex/sessions` 下的 `rollout-*.jsonl` 会话日志（支持多线并行）。
只跟踪**真实用户任务**，忽略 Codex 内部自动审批评估线程（guardian）：

- 任意会话 `task_started` / `user_message` → think（思考中）
- 任意会话 `agent_message(phase=final_answer)` / `task_complete` → happy + 气泡（5 秒）
- `function_call` 带 `sandbox_permissions=require_escalated` → 观察 3 秒 + 探测审批卡片，
  确认需人工授权才弹窗；直到对应 `function_call_output` 出现才视为已处理
- 思考中判定：会话处于 busy 且日志文件 **5 分钟内有新写入**；中断/漏写完成标记的
  陈旧会话自动失效，避免“全部完成仍卡 think”

## 项目结构

```
蕾米埃尔codex桌宠/
├── silent_pet.py          # 主程序
├── console_server.py      # 本地插件控制台（HTTP 服务）
├── uia_approval.ps1       # 审批窗口 UI 自动化脚本
├── build_pet.bat          # 一键打包 exe
├── config.example.json    # 配置模板（API Key / 档位 / 插件位置）
├── README.md
├── 素材/                  # 状态动画 GIF
├── plugins/               # 插件（DeepSeek 余额等）
└── assets/readme/         # README 宣传图与状态图鉴
```

## 已知限制

- 只能感知写入本机 `~/.codex` 的会话（Codex 桌面版与 Windows 命令行版）；WSL 里跑的
  Codex 会话看不到。可用环境变量 `CODEX_PET_SESSIONS` 指向其它会话目录。
- “完成”判定依赖会话日志中的 `final_answer` / `task_complete`；异常中断的会话靠
  5 分钟无新写入自动失效。
- 代码仅支持 Windows（依赖 Tk 透明窗口、Win32 API 与 UI 自动化）。

## 素材来源与版权

- 状态动画与菜单图标基于“桌宠公开版”素材整理；仅限个人学习与非商业展示使用，
  再分发请保留原作者署名并遵守原仓库授权范围。
- `assets/readme/ramiel.jpg` 为本项目宣传图，版权归项目作者所有。
- 本项目为个人非官方项目，与 OpenAI / Codex 官方无关，不存在隶属、合作或赞助关系。

## 与公开版的区别

- 去掉“单击打开对话窗 + API 配置”整套功能与右键应用菜单；
- `happy` 由“播一次”改为“保持 5 秒，单击可提前收回”；
- `think` / `happy` 由 Codex 会话状态驱动，支持多会话并行聚合；
- 新增微信风格气泡与“单击收回”交互；
- 新增审批窗口：Codex 征求权限时弹出，可直接允许 / 总是允许 / 拒绝；
- 忽略 Codex 内部自动审批评估线程（guardian），避免误报“任务完成”；
- 新增插件系统与本地控制台（预览区拖动定位、档位配置、插件开关）；
- 缩放以桌宠中心为锚点，插件整体跟随缩放，相对位置不偏移；
- 双击打开 Codex 时运行时自动探测桌面应用，无个人硬编码路径，可直接公开分享。
